"""diagnostic_dump.py -- Write a comprehensive JSON diagnostic dump from an InstrumentedContractResult.

Usage::

    from tests_rlm_adk.provider_fake.diagnostic_dump import write_diagnostic_dump

    write_diagnostic_dump(run_result, output_path="./issues/dashboard/fixture_runtime_output.json")
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .instrumented_runner import InstrumentedContractResult


def _serialize_contract(contract: Any) -> dict[str, Any]:
    """Extract all fields from a ContractResult into a plain dict."""
    return {
        "fixture_path": getattr(contract, "fixture_path", None),
        "scenario_id": getattr(contract, "scenario_id", None),
        "passed": getattr(contract, "passed", None),
        "checks": getattr(contract, "checks", []),
        "call_summary": getattr(contract, "call_summary", []),
        "total_elapsed_s": getattr(contract, "total_elapsed_s", None),
        "captured_requests": getattr(contract, "captured_requests", []),
        "captured_metadata": getattr(contract, "captured_metadata", []),
    }


def write_diagnostic_dump(
    run_result: InstrumentedContractResult,
    output_path: str | Path = "./issues/dashboard/fixture_runtime_output.json",
) -> Path:
    """Write a comprehensive JSON diagnostic dump of a fixture run.

    Args:
        run_result: The InstrumentedContractResult from run_fixture_contract_instrumented().
        output_path: File path for the output JSON. Parent directories are created if needed.

    Returns:
        The resolved Path where the file was written.
    """
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    contract = run_result.contract
    contract_passed = bool(contract.passed) if contract else False
    contract_diagnostics = contract.diagnostics() if contract and not contract_passed else ""

    dump: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "fixture_path": str(getattr(contract, "fixture_path", None)) if contract else None,
        "traces_db_path": run_result.traces_db_path,
        "contract_passed": contract_passed,
        "contract_diagnostics": contract_diagnostics,
        "contract_detail": _serialize_contract(contract) if contract else None,
        "repl_stdout": run_result.repl_stdout,
        "repl_stderr": run_result.repl_stderr,
        "instrumentation_log": run_result.instrumentation_log,
        "local_callback_log": run_result.local_callback_log,
        "final_state": run_result.final_state,
        "state_key_timeline": run_result.state_key_timeline,
        "plugin_result": {
            "traces_db_path": getattr(run_result.plugin_result, "traces_db_path", None),
            "session_db_path": getattr(run_result.plugin_result, "session_db_path", None),
            "artifact_root": getattr(run_result.plugin_result, "artifact_root", None),
            "event_count": len(run_result.plugin_result.events)
            if run_result.plugin_result.events
            else 0,
        },
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2, default=str, ensure_ascii=False)

    return output
