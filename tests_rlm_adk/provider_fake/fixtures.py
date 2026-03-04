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
        elif op == "$absent":
            # Handled by caller — should not reach here, but be safe
            pass
        else:
            return False, f"unknown operator {op!r}"

    return True, ""


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
    ) -> ContractResult:
        """Compare actual run results against fixture ``expected`` values.

        Checks ``final_answer``, ``total_iterations``, and ``total_model_calls``
        when present in the fixture's ``expected`` block.  Missing expected keys
        are skipped (not failures).  Missing actual values produce ``actual=None``.
        """
        from rlm_adk.state import FINAL_ANSWER, ITERATION_COUNT

        checks: list[dict[str, Any]] = []

        # final_answer
        if "final_answer" in self.expected:
            actual = final_state.get(FINAL_ANSWER)
            expected = self.expected["final_answer"]
            checks.append({
                "field": "final_answer",
                "expected": expected,
                "actual": actual,
                "ok": actual == expected,
            })

        # total_iterations
        if "total_iterations" in self.expected:
            actual_iter = final_state.get(ITERATION_COUNT)
            expected_iter = self.expected["total_iterations"]
            checks.append({
                "field": "total_iterations",
                "expected": expected_iter,
                "actual": actual_iter,
                "ok": actual_iter == expected_iter,
            })

        # total_model_calls
        if "total_model_calls" in self.expected:
            expected_calls = self.expected["total_model_calls"]
            actual_calls = self._call_index
            checks.append({
                "field": "total_model_calls",
                "expected": expected_calls,
                "actual": actual_calls,
                "ok": actual_calls == expected_calls,
            })

        # Declarative expected_state assertions
        for key, spec in self.expected_state.items():
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
