"""Fixture loader and scenario router for the fake Gemini provider."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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

        self._responses: list[dict[str, Any]] = fixture.get("responses", [])
        self._faults: dict[int, dict[str, Any]] = {
            f["call_index"]: f for f in fixture.get("fault_injections", [])
        }

        self._call_index: int = 0
        self._response_pointer: int = 0
        self._lock = threading.Lock()
        self._request_log: list[dict[str, Any]] = []

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

    def next_response(self, request_body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        """Return ``(status_code, response_body)`` for the next call.

        Thread-safe: multiple worker calls may arrive concurrently.
        """
        with self._lock:
            idx = self._call_index
            self._call_index += 1

            # Log the request (sanitised — drop large content arrays)
            self._request_log.append({
                "call_index": idx,
                "has_system_instruction": bool(
                    request_body.get("systemInstruction") if request_body else False
                ),
                "contents_count": len(request_body.get("contents", [])) if request_body else 0,
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

    def reset(self) -> None:
        """Reset state for reuse between tests."""
        with self._lock:
            self._call_index = 0
            self._response_pointer = 0
            self._request_log.clear()
