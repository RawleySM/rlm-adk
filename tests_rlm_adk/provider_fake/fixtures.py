"""Fixture loader and scenario router for the fake Gemini provider."""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Matcher helpers for declarative expected_state assertions
# ---------------------------------------------------------------------------

def _is_operator_dict(d: Any) -> bool:
    """Return True if *d* is a matcher operator dict (all keys start with ``$``)."""
    return isinstance(d, dict) and bool(d) and all(
        isinstance(k, str) and k.startswith("$") for k in d
    )


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *overrides* into *base* (mutates *base*).

    Nested dicts are merged, **except** when the override value is a matcher
    operator dict (all keys start with ``$``), which fully replaces the base.
    """
    for key, value in overrides.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
            and not _is_operator_dict(value)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _match_value(
    actual: Any,
    spec: Any,
) -> tuple[bool, str]:
    """Match *actual* against a matcher *spec*.

    Returns ``(ok, detail)`` where *detail* describes the mismatch (empty
    string on success).

    If *spec* is a plain value (not a dict with ``$`` operator keys), exact
    equality is checked.  If *spec* is a dict whose keys all start with
    ``$``, each operator is evaluated and results are ANDed.
    """
    # Plain equality shortcut
    if not isinstance(spec, dict) or not all(
        isinstance(k, str) and k.startswith("$") for k in spec
    ):
        ok = actual == spec
        return ok, "" if ok else f"expected {spec!r}, got {actual!r}"

    # Operator dict — every operator must pass
    for op, operand in spec.items():
        if op == "$gt":
            if actual is None or actual <= operand:
                return False, f"${op}: expected > {operand}, got {actual!r}"
        elif op == "$gte":
            if actual is None or actual < operand:
                return False, f"${op}: expected >= {operand}, got {actual!r}"
        elif op == "$lt":
            if actual is None or actual >= operand:
                return False, f"${op}: expected < {operand}, got {actual!r}"
        elif op == "$lte":
            if actual is None or actual > operand:
                return False, f"${op}: expected <= {operand}, got {actual!r}"
        elif op == "$not_none":
            if operand and actual is None:
                return False, "$not_none: got None"
        elif op == "$not_empty":
            if operand:
                if actual is None:
                    return False, "$not_empty: got None"
                if hasattr(actual, "__len__") and len(actual) == 0:
                    return False, f"$not_empty: got empty {type(actual).__name__}"
        elif op == "$has_key":
            if not isinstance(actual, dict):
                return False, f"$has_key: expected dict, got {type(actual).__name__}"
            if operand not in actual:
                return False, f"$has_key: key {operand!r} not in {list(actual.keys())}"
        elif op == "$type":
            type_map = {
                "list": list, "dict": dict, "str": str,
                "int": int, "float": float, "bool": bool,
            }
            expected_type = type_map.get(operand)
            if expected_type is None:
                return False, f"$type: unknown type {operand!r}"
            if not isinstance(actual, expected_type):
                return False, f"$type: expected {operand}, got {type(actual).__name__}"
        elif op == "$contains":
            if not isinstance(actual, str):
                return False, f"$contains: expected str, got {type(actual).__name__}"
            if operand not in actual:
                return False, f"$contains: {operand!r} not in {actual!r}"
        elif op == "$len_gte":
            if actual is None or not hasattr(actual, "__len__"):
                return False, f"$len_gte: expected sized, got {type(actual).__name__}"
            if len(actual) < operand:
                return False, f"$len_gte: expected len >= {operand}, got {len(actual)}"
        elif op == "$len_eq":
            if actual is None or not hasattr(actual, "__len__"):
                return False, f"$len_eq: expected sized, got {type(actual).__name__}"
            if len(actual) != operand:
                return False, f"$len_eq: expected len == {operand}, got {len(actual)}"
        elif op == "$oneof":
            if not isinstance(operand, list):
                return False, f"$oneof: operand must be a list, got {type(operand).__name__}"
            if actual not in operand:
                return False, f"$oneof: {actual!r} not in {operand!r}"
        elif op == "$absent":
            # Handled by caller — should not reach here, but be safe
            pass
        else:
            return False, f"unknown operator {op!r}"

    return True, ""


def _match_structure(
    actual: Any,
    spec: Any,
    path: str = "value",
) -> tuple[bool, str]:
    """Recursively match *actual* against *spec*."""
    if isinstance(spec, dict):
        if all(isinstance(k, str) and k.startswith("$") for k in spec):
            return _match_value(actual, spec)

        if not isinstance(actual, dict):
            return False, f"{path}: expected dict, got {type(actual).__name__}"

        for key, child_spec in spec.items():
            child_path = f"{path}.{key}"
            if isinstance(child_spec, dict) and child_spec.get("$absent"):
                if key in actual:
                    return False, f"{child_path}: key should be absent"
                continue
            if key not in actual:
                return False, f"{child_path}: key missing"
            ok, detail = _match_structure(actual[key], child_spec, child_path)
            if not ok:
                return False, detail
        return True, ""

    if isinstance(spec, list):
        if not isinstance(actual, list):
            return False, f"{path}: expected list, got {type(actual).__name__}"
        if len(actual) != len(spec):
            return False, f"{path}: expected len {len(spec)}, got {len(actual)}"
        for idx, (actual_item, spec_item) in enumerate(zip(actual, spec)):
            ok, detail = _match_structure(actual_item, spec_item, f"{path}[{idx}]")
            if not ok:
                return False, detail
        return True, ""

    return _match_value(actual, spec)


def _preview(body: dict[str, Any] | None, max_len: int = 200) -> str:
    """Extract first text content from a request/response body, truncated."""
    if not body:
        return ""
    # Try candidates (response) first
    for candidate in body.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "text" in part:
                text = part["text"]
                return text[:max_len] + ("..." if len(text) > max_len else "")
    # Try contents (request) — first content, first part
    for content in body.get("contents", []):
        for part in content.get("parts", []):
            if "text" in part:
                text = part["text"]
                return text[:max_len] + ("..." if len(text) > max_len else "")
    return ""


@dataclasses.dataclass
class ContractResult:
    """Structured result from running a fixture through the contract runner."""

    fixture_path: str
    scenario_id: str
    passed: bool
    checks: list[dict[str, Any]]       # [{field, expected, actual, ok}, ...]
    call_summary: list[dict[str, Any]]  # from request_log
    total_elapsed_s: float
    captured_requests: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    captured_metadata: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def diagnostics(self) -> str:
        """Multi-line human-readable diagnostic report."""
        lines = [
            f"{'PASS' if self.passed else 'FAIL'}: {self.scenario_id}  ({self.fixture_path})",
            f"  elapsed: {self.total_elapsed_s:.2f}s",
            "",
            "  Checks:",
        ]
        for c in self.checks:
            mark = "ok" if c["ok"] else "MISMATCH"
            detail = c.get("detail", "")
            detail_suffix = f"  ({detail})" if detail else ""
            lines.append(
                f"    [{mark}] {c['field']}: expected={c['expected']!r}  actual={c['actual']!r}{detail_suffix}"
            )
        lines.append("")
        lines.append(f"  Call log ({len(self.call_summary)} calls):")
        for entry in self.call_summary:
            preview = entry.get("first_content_preview", "")
            model = entry.get("model", "?")
            lines.append(
                f"    #{entry['call_index']}  model={model}  "
                f"sys={entry.get('has_system_instruction', '?')}  "
                f"contents={entry.get('contents_count', '?')}  "
                f"preview={preview[:80]!r}"
            )
        return "\n".join(lines)

    def summary_line(self) -> str:
        """One-liner for batch output."""
        status = "PASS" if self.passed else "FAIL"
        failed = [c["field"] for c in self.checks if not c["ok"]]
        detail = f"  mismatches: {', '.join(failed)}" if failed else ""
        return f"[{status}] {self.scenario_id} ({self.total_elapsed_s:.2f}s){detail}"


class ScenarioRouter:
    """Sequential response router with fault injection overlay.

    Responses are consumed in FIFO order. If ``call_index`` matches a
    fault injection entry, the fault response is returned instead of
    advancing the normal response pointer.
    """

    def __init__(self, fixture: dict[str, Any]) -> None:
        self.scenario_id: str = fixture["scenario_id"]
        self.description: str = fixture.get("description", "")
        self.config: dict[str, Any] = fixture.get("config", {})
        self.expected: dict[str, Any] = fixture.get("expected", {})
        self.expected_state: dict[str, Any] = fixture.get("expected_state", {})
        self.expected_contract: dict[str, Any] = fixture.get("expected_contract", {})
        self._litellm_overrides: dict[str, Any] = fixture.get("litellm_overrides", {})

        self._responses: list[dict[str, Any]] = fixture.get("responses", [])
        self._faults: dict[int, dict[str, Any]] = {
            f["call_index"]: f for f in fixture.get("fault_injections", [])
        }

        self._call_index: int = 0
        self._response_pointer: int = 0
        self._lock = threading.Lock()
        self._request_log: list[dict[str, Any]] = []
        self._captured_requests: list[dict[str, Any]] = []
        self._captured_metadata: list[dict[str, Any]] = []
        self._fixture_exhausted_calls: list[int] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> ScenarioRouter:
        """Load a fixture from a JSON file."""
        with open(path) as f:
            return cls(json.load(f))

    @property
    def call_index(self) -> int:
        return self._call_index

    @property
    def request_log(self) -> list[dict[str, Any]]:
        return list(self._request_log)

    @property
    def captured_requests(self) -> list[dict[str, Any]]:
        return list(self._captured_requests)

    @property
    def captured_metadata(self) -> list[dict[str, Any]]:
        return list(self._captured_metadata)

    @property
    def fixture_exhausted_calls(self) -> list[int]:
        return list(self._fixture_exhausted_calls)

    def next_response(
        self,
        request_body: dict[str, Any] | None = None,
        request_meta: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """Return ``(status_code, response_body)`` for the next call.

        Thread-safe: multiple worker calls may arrive concurrently.

        Args:
            request_body: The parsed JSON request body (optional).
            request_meta: Extra metadata from the server handler, e.g.
                ``{"model": "gemini-fake"}``.  Merged into the request log
                entry for diagnostics.
        """
        with self._lock:
            idx = self._call_index
            self._call_index += 1

            # Log the request (sanitised — drop large content arrays)
            log_entry: dict[str, Any] = {
                "call_index": idx,
                "has_system_instruction": bool(
                    request_body.get("systemInstruction") if request_body else False
                ),
                "contents_count": len(request_body.get("contents", [])) if request_body else 0,
                "model": (request_meta or {}).get("model", "unknown"),
                "first_content_preview": _preview(request_body),
            }
            self._request_log.append(log_entry)

            if request_body is not None:
                self._captured_requests.append(copy.deepcopy(request_body))

                # Determine caller from the response entry (if available)
                caller = "unknown"
                if idx not in self._faults and self._response_pointer < len(self._responses):
                    caller = self._responses[self._response_pointer].get("caller", "unknown")
                elif idx in self._faults:
                    caller = self._faults[idx].get("caller", "fault")
                self._captured_metadata.append({
                    "call_index": idx,
                    "caller": caller,
                })

            # Check fault injection first
            if idx in self._faults:
                fault = self._faults[idx]
                fault_type = fault.get("fault_type", "http_error")

                if fault_type == "malformed_json":
                    # Return a special sentinel — the server will write raw text
                    return -1, {"_raw": fault.get("body_raw", "{bad json")}

                status = fault.get("status", 500)
                body = fault.get("body", {
                    "error": {"code": status, "message": "Injected fault", "status": "INTERNAL"}
                })
                logger.info(
                    "Fixture %s: call #%d -> fault %d (%s)",
                    self.scenario_id, idx, status, fault_type,
                )
                return status, body

            # Normal sequential response
            if self._response_pointer >= len(self._responses):
                # Ran out of scripted responses — return a safe fallback
                self._fixture_exhausted_calls.append(idx)
                logger.warning(
                    "Fixture %s: call #%d exhausted responses (pointer=%d, total=%d). "
                    "Returning empty-text fallback.",
                    self.scenario_id, idx, self._response_pointer, len(self._responses),
                )
                return 200, {
                    "candidates": [{
                        "content": {"role": "model", "parts": [{"text": "FINAL(fixture-exhausted)"}]},
                        "finishReason": "STOP",
                        "index": 0,
                    }],
                    "usageMetadata": {
                        "promptTokenCount": 1,
                        "candidatesTokenCount": 1,
                        "totalTokenCount": 2,
                    },
                    "modelVersion": "gemini-fake",
                }

            resp = self._responses[self._response_pointer]
            self._response_pointer += 1
            status = resp.get("status", 200)
            body = resp["body"]
            logger.info(
                "Fixture %s: call #%d -> response (pointer=%d, status=%d)",
                self.scenario_id, idx, self._response_pointer - 1, status,
            )
            return status, body

    def check_expectations(
        self,
        final_state: dict[str, Any],
        fixture_path: str | Path,
        elapsed_s: float,
        *,
        events: list[Any] | None = None,
        litellm_mode: bool = False,
    ) -> ContractResult:
        """Compare actual run results against fixture ``expected`` values.

        Checks ``final_answer``, ``total_iterations``, and ``total_model_calls``
        when present in the fixture's ``expected`` block.  Missing expected keys
        are skipped (not failures).  Missing actual values produce ``actual=None``.

        When *litellm_mode* is True and the fixture defines a
        ``litellm_overrides`` section, overrides are deep-merged on top of
        ``expected``, ``expected_state``, and ``expected_contract`` before
        checking.
        """
        from rlm_adk.state import FINAL_ANSWER, ITERATION_COUNT

        # Apply litellm overrides if present
        expected = self.expected
        expected_state = self.expected_state
        expected_contract = self.expected_contract
        if litellm_mode and self._litellm_overrides:
            expected = _deep_merge(copy.deepcopy(self.expected), self._litellm_overrides.get("expected", {}))
            expected_state = _deep_merge(copy.deepcopy(self.expected_state), self._litellm_overrides.get("expected_state", {}))
            expected_contract = _deep_merge(copy.deepcopy(self.expected_contract), self._litellm_overrides.get("expected_contract", {}))

        checks: list[dict[str, Any]] = []
        event_parts = _extract_event_parts(events or [])
        tool_results = _extract_tool_results(event_parts)

        # final_answer
        if "final_answer" in expected:
            actual = final_state.get(FINAL_ANSWER)
            expected_fa = expected["final_answer"]
            ok, detail = _match_value(actual, expected_fa)
            checks.append({
                "field": "final_answer",
                "expected": expected_fa,
                "actual": actual,
                "ok": ok,
                "detail": detail,
            })

        # total_iterations
        if "total_iterations" in expected:
            actual_iter = final_state.get(ITERATION_COUNT)
            expected_iter = expected["total_iterations"]
            ok, detail = _match_value(actual_iter, expected_iter)
            checks.append({
                "field": "total_iterations",
                "expected": expected_iter,
                "actual": actual_iter,
                "ok": ok,
                "detail": detail,
            })

        # total_model_calls
        if "total_model_calls" in expected:
            expected_calls = expected["total_model_calls"]
            actual_calls = self._call_index
            ok, detail = _match_value(actual_calls, expected_calls)
            checks.append({
                "field": "total_model_calls",
                "expected": expected_calls,
                "actual": actual_calls,
                "ok": ok,
                "detail": detail,
            })

        # Declarative expected_state assertions
        for key, spec in expected_state.items():
            # $absent: key should not exist in state
            if isinstance(spec, dict) and spec.get("$absent"):
                present = key in final_state
                checks.append({
                    "field": f"state:{key}",
                    "expected": "$absent",
                    "actual": final_state[key] if present else "<absent>",
                    "ok": not present,
                    "detail": f"key {key!r} should not exist" if present else "",
                })
                continue

            actual = final_state.get(key)
            ok, detail = _match_value(actual, spec)
            checks.append({
                "field": f"state:{key}",
                "expected": spec,
                "actual": actual,
                "ok": ok,
                "detail": detail,
            })

        checks.append({
            "field": "fixture_exhausted_fallback",
            "expected": False,
            "actual": bool(self._fixture_exhausted_calls),
            "ok": not self._fixture_exhausted_calls,
            "detail": (
                f"fallback used at call indices {self._fixture_exhausted_calls}"
                if self._fixture_exhausted_calls else ""
            ),
        })

        for check in _check_contract_invariants(
            expected_contract,
            final_state=final_state,
            callers=[meta.get("caller", "unknown") for meta in self._captured_metadata],
            captured_request_count=len(self._captured_requests),
            event_parts=event_parts,
            tool_results=tool_results,
        ):
            checks.append(check)

        passed = all(c["ok"] for c in checks)
        return ContractResult(
            fixture_path=str(fixture_path),
            scenario_id=self.scenario_id,
            passed=passed,
            checks=checks,
            call_summary=list(self._request_log),
            total_elapsed_s=elapsed_s,
            captured_requests=list(self._captured_requests),
            captured_metadata=list(self._captured_metadata),
        )

    def reset(self) -> None:
        """Reset state for reuse between tests."""
        with self._lock:
            self._call_index = 0
            self._response_pointer = 0
            self._request_log.clear()
            self._captured_requests.clear()
            self._captured_metadata.clear()
            self._fixture_exhausted_calls.clear()


def _extract_event_parts(events: list[Any]) -> list[dict[str, Any]]:
    """Normalize event content parts for declarative contract checks."""
    normalized: list[dict[str, Any]] = []
    for event_index, event in enumerate(events):
        content = getattr(event, "content", None)
        if content is None:
            continue
        role = getattr(content, "role", None)
        for part_index, part in enumerate(getattr(content, "parts", []) or []):
            function_call = getattr(part, "function_call", None)
            if function_call is not None:
                normalized.append({
                    "event_index": event_index,
                    "part_index": part_index,
                    "role": role,
                    "kind": "function_call",
                    "name": getattr(function_call, "name", None),
                    "args": getattr(function_call, "args", None),
                })
                continue

            function_response = getattr(part, "function_response", None)
            if function_response is not None:
                normalized.append({
                    "event_index": event_index,
                    "part_index": part_index,
                    "role": role,
                    "kind": "function_response",
                    "name": getattr(function_response, "name", None),
                    "response": getattr(function_response, "response", None),
                })
                continue

            text = getattr(part, "text", None)
            if text:
                normalized.append({
                    "event_index": event_index,
                    "part_index": part_index,
                    "role": role,
                    "kind": "text",
                    "text": text,
                })
    return normalized


def _extract_tool_results(event_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract dict-backed tool results from normalized event parts."""
    results: list[dict[str, Any]] = []
    for part in event_parts:
        if part.get("kind") != "function_response":
            continue
        response = part.get("response")
        if not isinstance(response, dict):
            continue
        results.append({
            "function_name": part.get("name"),
            **copy.deepcopy(response),
        })
    return results


def _find_matching_subsequence(
    actual_items: list[dict[str, Any]],
    expected_items: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Return whether *expected_items* appears contiguously in *actual_items*."""
    if not expected_items:
        return True, ""
    if len(expected_items) > len(actual_items):
        return False, (
            f"expected subsequence len {len(expected_items)}, got only {len(actual_items)} items"
        )
    for start in range(len(actual_items) - len(expected_items) + 1):
        all_ok = True
        for offset, expected_item in enumerate(expected_items):
            ok, _detail = _match_structure(
                actual_items[start + offset],
                expected_item,
                path=f"event_parts[{start + offset}]",
            )
            if not ok:
                all_ok = False
                break
        if all_ok:
            return True, ""
    return False, f"expected subsequence not found in {actual_items!r}"


def _check_contract_invariants(
    expected_contract: dict[str, Any] | None,
    *,
    final_state: dict[str, Any],
    callers: list[str],
    captured_request_count: int,
    event_parts: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate the fixture's richer declarative contract invariants."""
    if not expected_contract:
        return []

    checks: list[dict[str, Any]] = []

    callers_spec = expected_contract.get("callers")
    if callers_spec is not None:
        if isinstance(callers_spec, list):
            ok, detail = _match_structure(callers, callers_spec, "callers")
            checks.append({
                "field": "contract:callers.sequence",
                "expected": callers_spec,
                "actual": callers,
                "ok": ok,
                "detail": detail,
            })
        elif isinstance(callers_spec, dict):
            if "sequence" in callers_spec:
                expected_sequence = callers_spec["sequence"]
                ok, detail = _match_structure(callers, expected_sequence, "callers.sequence")
                checks.append({
                    "field": "contract:callers.sequence",
                    "expected": expected_sequence,
                    "actual": callers,
                    "ok": ok,
                    "detail": detail,
                })
            if "counts" in callers_spec:
                actual_counts = {caller: callers.count(caller) for caller in sorted(set(callers))}
                expected_counts = callers_spec["counts"]
                ok, detail = _match_structure(actual_counts, expected_counts, "callers.counts")
                checks.append({
                    "field": "contract:callers.counts",
                    "expected": expected_counts,
                    "actual": actual_counts,
                    "ok": ok,
                    "detail": detail,
                })
            if "count" in callers_spec:
                expected_count = callers_spec["count"]
                actual_count = len(callers)
                ok, detail = _match_value(actual_count, expected_count)
                checks.append({
                    "field": "contract:callers.count",
                    "expected": expected_count,
                    "actual": actual_count,
                    "ok": ok,
                    "detail": detail,
                })

    captured_requests_spec = expected_contract.get("captured_requests")
    if captured_requests_spec is not None:
        expected_count = (
            captured_requests_spec["count"]
            if isinstance(captured_requests_spec, dict) and "count" in captured_requests_spec
            else captured_requests_spec
        )
        ok, detail = _match_value(captured_request_count, expected_count)
        checks.append({
            "field": "contract:captured_requests.count",
            "expected": expected_count,
            "actual": captured_request_count,
            "ok": ok,
            "detail": detail,
        })

    events_spec = expected_contract.get("events") or {}
    if "part_counts" in events_spec:
        actual_counts: dict[str, int] = {}
        for part in event_parts:
            key = (
                f"{part['kind']}:{part['name']}"
                if part.get("name") else part["kind"]
            )
            actual_counts[key] = actual_counts.get(key, 0) + 1
        expected_counts = events_spec["part_counts"]
        ok, detail = _match_structure(actual_counts, expected_counts, "events.part_counts")
        checks.append({
            "field": "contract:events.part_counts",
            "expected": expected_counts,
            "actual": actual_counts,
            "ok": ok,
            "detail": detail,
        })
    if "part_sequence" in events_spec:
        expected_sequence = events_spec["part_sequence"]
        ok, detail = _find_matching_subsequence(event_parts, expected_sequence)
        checks.append({
            "field": "contract:events.part_sequence",
            "expected": expected_sequence,
            "actual": event_parts,
            "ok": ok,
            "detail": detail,
        })

    tool_spec = expected_contract.get("tool_results") or {}
    if "count" in tool_spec:
        expected_count = tool_spec["count"]
        actual_count = len(tool_results)
        ok, detail = _match_value(actual_count, expected_count)
        checks.append({
            "field": "contract:tool_results.count",
            "expected": expected_count,
            "actual": actual_count,
            "ok": ok,
            "detail": detail,
        })
    for idx, expected_tool in enumerate(tool_spec.get("any", [])):
        matched = False
        detail = ""
        for actual_tool in tool_results:
            ok, detail = _match_structure(actual_tool, expected_tool, f"tool_results.any[{idx}]")
            if ok:
                matched = True
                detail = ""
                break
        checks.append({
            "field": f"contract:tool_results.any[{idx}]",
            "expected": expected_tool,
            "actual": tool_results,
            "ok": matched,
            "detail": detail if not matched else "",
        })
    if "stdout_contains" in tool_spec:
        expected_needles = tool_spec["stdout_contains"]
        if not isinstance(expected_needles, list):
            expected_needles = [expected_needles]
        actual_stdout = "\n".join(str(item.get("stdout", "")) for item in tool_results)
        ok = all(needle in actual_stdout for needle in expected_needles)
        checks.append({
            "field": "contract:tool_results.stdout_contains",
            "expected": expected_needles,
            "actual": actual_stdout,
            "ok": ok,
            "detail": "" if ok else f"missing one of {expected_needles!r}",
        })
    if "stderr_contains" in tool_spec:
        expected_needles = tool_spec["stderr_contains"]
        if not isinstance(expected_needles, list):
            expected_needles = [expected_needles]
        actual_stderr = "\n".join(str(item.get("stderr", "")) for item in tool_results)
        ok = all(needle in actual_stderr for needle in expected_needles)
        checks.append({
            "field": "contract:tool_results.stderr_contains",
            "expected": expected_needles,
            "actual": actual_stderr,
            "ok": ok,
            "detail": "" if ok else f"missing one of {expected_needles!r}",
        })

    observability_spec = expected_contract.get("observability") or {}
    counters_spec = observability_spec.get("counters", observability_spec)
    for key, spec in counters_spec.items():
        actual = final_state.get(key)
        ok, detail = _match_structure(actual, spec, f"observability.{key}")
        checks.append({
            "field": f"contract:observability:{key}",
            "expected": spec,
            "actual": actual,
            "ok": ok,
            "detail": detail,
        })

    return checks


def _caller_to_model_name(caller: str) -> str:
    """Map fixture caller type to model name for output keys."""
    if caller == "reasoning":
        return "reasoning_agent"
    if caller == "worker":
        return "worker"
    return caller


def save_captured_requests(
    captured: list[dict[str, Any]],
    output_path: Path,
    metadata: list[dict[str, Any]] | None = None,
) -> Path:
    """Write captured request bodies to a JSON file.

    When *metadata* is provided (from ``ContractResult.captured_metadata``),
    the output is a dict keyed by ``request_to_<model>_iter_<N>`` with each
    value containing ``_meta`` (caller, call_index, iteration) and the full
    request body under ``body``.  Without metadata the output is a plain list
    for backward compatibility.

    Args:
        captured: List of request body dicts (from ContractResult.captured_requests).
        output_path: Destination file path.
        metadata: Optional parallel list of ``{call_index, caller}`` dicts.

    Returns:
        The output_path for downstream verification.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if metadata and len(metadata) == len(captured):
        # Build per-caller iteration counters
        caller_counters: dict[str, int] = {}
        keyed: dict[str, Any] = {}
        for req, meta in zip(captured, metadata):
            caller = meta.get("caller", "unknown")
            model_name = _caller_to_model_name(caller)
            caller_counters[caller] = caller_counters.get(caller, 0) + 1
            iteration = caller_counters[caller]
            key = f"request_to_{model_name}_iter_{iteration}"
            keyed[key] = {
                "_meta": {
                    "call_index": meta.get("call_index"),
                    "caller": caller,
                    "model": model_name,
                    "iteration": iteration,
                },
                "body": req,
            }
        with open(output_path, "w") as f:
            json.dump(keyed, f, indent=2)
    else:
        with open(output_path, "w") as f:
            json.dump(captured, f, indent=2)
    return output_path
