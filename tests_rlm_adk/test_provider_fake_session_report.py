"""Provider-fake coverage for evaluator-facing session report child outcomes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from rlm_adk.eval.session_report import build_session_report
from rlm_adk.state import FINAL_ANSWER
from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    PluginContractResult,
    run_fixture_contract_with_plugins,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]


async def _run_fixture_report(
    fixture_name: str,
    tmp_path: Path,
) -> tuple[PluginContractResult, dict[str, Any]]:
    """Run a provider-fake fixture with plugins and return its session report."""
    traces_db_path = tmp_path / f"{fixture_name}.db"
    result = await run_fixture_contract_with_plugins(
        FIXTURE_DIR / f"{fixture_name}.json",
        traces_db_path=str(traces_db_path),
        repl_trace_level=1,
    )
    trace_id = _latest_trace_id(traces_db_path)
    return result, build_session_report(trace_id, str(traces_db_path))


def _latest_trace_id(traces_db_path: Path) -> str:
    """Read the single trace_id produced by a focused provider-fake run."""
    conn = sqlite3.connect(str(traces_db_path))
    try:
        row = conn.execute(
            "SELECT trace_id FROM traces ORDER BY start_time DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"No trace row found in {traces_db_path}"
    return str(row[0])


async def test_session_report_child_outcomes_recursive_success(tmp_path: Path):
    """Recursive child success should be visible via child_outcomes only."""
    result, report = await _run_fixture_report("fake_recursive_ping", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {}
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 2}
    assert child["children_with_errors"] == 0

    summaries = child["summaries"]
    assert [(item["depth"], item["fanout"]) for item in summaries] == [(1, 0), (2, 0)]
    assert summaries[0]["final_answer"] == '{"my_response":"pong","your_response":"ping"}'
    assert summaries[0]["nested_dispatch"]["count"] == 1
    assert summaries[1]["final_answer"] == '{"my_response":"pong","your_response":"ping"}'
    assert summaries[1]["nested_dispatch"]["count"] == 0


async def test_session_report_child_outcomes_structured_exhaustion(tmp_path: Path):
    """Mixed structured-output exhaustion should survive into child_outcomes."""
    _result, report = await _run_fixture_report("structured_output_batched_k3_mixed_exhaust", tmp_path)

    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 3
    assert child["child_total_batch_dispatches"] == 1
    assert child["child_error_counts"] == {"SCHEMA_VALIDATION_EXHAUSTED": 1}
    assert child["structured_output_failures"] == 1
    assert child["structured_output_outcomes"] == {
        "validated": 2,
        "retry_exhausted": 1,
    }
    assert child["child_error_categories"] == {"SCHEMA_VALIDATION_EXHAUSTED": 1}
    assert child["total_summaries"] == 3
    assert child["children_with_errors"] == 1

    exhausted = next(
        item
        for item in child["summaries"]
        if item["structured_output"]["outcome"] == "retry_exhausted"
    )
    validated = [
        item for item in child["summaries"] if item["structured_output"]["outcome"] == "validated"
    ]

    assert len(validated) == 2
    assert {item["prompt_preview"] for item in validated} == {
        "Review: Great product!",
        "Review: Love it!",
    }
    assert exhausted["structured_output"]["schema_name"] == "SentimentResult"
    assert exhausted["structured_output"]["attempts"] == 3
    assert exhausted["structured_output"]["retry_count"] == 2
    assert exhausted["structured_output"]["outcome"] == "retry_exhausted"
    assert exhausted["structured_output"]["validated_result"] is None
    assert exhausted["error_category"] == "SCHEMA_VALIDATION_EXHAUSTED"
    assert exhausted["prompt_preview"] == "Review: Terrible quality"


async def test_session_report_child_outcomes_worker_auth_fault(tmp_path: Path):
    """Worker auth failures should be evaluator-queryable via child_outcomes."""
    result, report = await _run_fixture_report("worker_auth_error_401", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {"AUTH": 1}
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["child_error_categories"] == {"AUTH": 1}
    assert child["children_with_errors"] == 1

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is True
    assert summary["error_category"] == "AUTH"
    assert "401" in summary["error_message"]
    assert summary["structured_output"]["expected"] is False
    assert summary["structured_output"]["outcome"] == "not_applicable"


async def test_session_report_child_outcomes_worker_500_recovery(tmp_path: Path):
    """Recovered 500 retries should remain visible as successful child outcomes."""
    result, report = await _run_fixture_report("worker_500_then_success", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {}
    assert child["child_error_categories"] == {}
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["total_summaries"] == 1
    assert child["children_with_errors"] == 0

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is False
    assert summary["error_category"] is None
    assert summary["prompt_preview"] == "What is the status?"
    assert summary["result_preview"] == "Server recovered answer"
    assert summary["final_answer"] == "Server recovered answer"


async def test_session_report_child_outcomes_worker_500_retry_exhausted(tmp_path: Path):
    """Handled retry exhaustion should remain queryable via evaluator-facing child outcomes."""
    result, report = await _run_fixture_report("worker_500_retry_exhausted", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {"SERVER": 1}
    assert child["child_error_categories"] == {"SERVER": 1}
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["total_summaries"] == 1
    assert child["children_with_errors"] == 1

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is True
    assert summary["error_category"] == "SERVER"
    assert "500 INTERNAL" in summary["error_message"]
    assert "500 INTERNAL" in summary["result_preview"]
    assert "500 INTERNAL" in summary["final_answer"]


async def test_session_report_child_outcomes_worker_500_naive_consumption(tmp_path: Path):
    """Evaluator-facing child outcomes should preserve the hidden server error."""
    result, report = await _run_fixture_report("worker_500_retry_exhausted_naive", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert "500 INTERNAL" in result.final_state.get(FINAL_ANSWER, ""), (
        f"Expected root final_answer to be the consumed worker error string, got {result.final_state.get(FINAL_ANSWER)!r}"
    )
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {"SERVER": 1}
    assert child["child_error_categories"] == {"SERVER": 1}
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["total_summaries"] == 1
    assert child["children_with_errors"] == 1

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is True
    assert summary["error_category"] == "SERVER"
    assert "500 INTERNAL" in summary["error_message"]
    assert "500 INTERNAL" in summary["result_preview"]
    assert "500 INTERNAL" in summary["final_answer"]


async def test_session_report_child_outcomes_worker_empty_response(tmp_path: Path):
    """Mixed batch success and safety-blocked empty output should be queryable."""
    result, report = await _run_fixture_report("worker_empty_response", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 2
    assert child["child_total_batch_dispatches"] == 1
    assert child["child_error_counts"] == {"SAFETY": 1}
    assert child["structured_output_outcomes"] == {"not_applicable": 2}
    assert child["children_with_errors"] == 1

    summaries = {(item["depth"], item["fanout"]): item for item in child["summaries"]}
    assert summaries[(1, 0)]["final_answer"] == "Analysis: positive trend"
    assert summaries[(1, 1)]["error"] is True
    assert summaries[(1, 1)]["error_category"] == "SAFETY"
    assert "SAFETY" in summaries[(1, 1)]["error_message"]


async def test_session_report_child_outcomes_worker_max_tokens_naive(tmp_path: Path):
    """Naively consumed truncated worker output should preserve MAX_TOKENS metadata."""
    result, report = await _run_fixture_report("worker_max_tokens_naive", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {}
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["children_with_errors"] == 0

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is False
    assert summary["error_category"] is None
    assert summary["prompt_preview"] == "Provide a detailed market analysis"
    assert summary["final_answer"].endswith("and")


async def test_session_report_child_outcomes_worker_safety_finish(tmp_path: Path):
    """A SAFETY-blocked child should survive into evaluator-facing child_outcomes."""
    result, report = await _run_fixture_report("worker_safety_finish", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {"SAFETY": 1}
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["child_error_categories"] == {"SAFETY": 1}
    assert child["children_with_errors"] == 1

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is True
    assert summary["error_category"] == "SAFETY"
    assert summary["final_answer"].startswith("[RLM ERROR]")
    assert summary["prompt_preview"] == "Generate content"
    assert summary["structured_output"]["outcome"] == "not_applicable"


async def test_session_report_child_outcomes_worker_empty_response_batch(tmp_path: Path):
    """A mixed batch should retain both the valid child and the blocked-empty child."""
    result, report = await _run_fixture_report("worker_empty_response", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 2
    assert child["child_total_batch_dispatches"] == 1
    assert child["child_error_counts"] == {"SAFETY": 1}
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 2}
    assert child["child_error_categories"] == {"SAFETY": 1}
    assert child["children_with_errors"] == 1

    summaries = {(item["depth"], item["fanout"]): item for item in child["summaries"]}
    valid = summaries[(1, 0)]
    blocked = summaries[(1, 1)]
    assert valid["error"] is False
    assert valid["final_answer"] == "Analysis: positive trend"
    assert blocked["error"] is True
    assert blocked["error_category"] == "SAFETY"
    assert blocked["final_answer"].startswith("[RLM ERROR]")
    assert blocked["prompt_preview"] == "Analyze market B"


async def test_session_report_child_outcomes_worker_max_tokens_naive(tmp_path: Path):
    """A truncated child should still be evaluator-visible as a non-error MAX_TOKENS outcome."""
    result, report = await _run_fixture_report("worker_max_tokens_naive", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_error_counts"] == {}
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["child_error_categories"] == {}
    assert child["children_with_errors"] == 0

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is False
    assert summary["error_category"] is None
    assert summary["prompt_preview"] == "Provide a detailed market analysis"
    assert summary["final_answer"].endswith("and")
    assert "revenue increasing by 15%" in summary["final_answer"]
    assert summary["structured_output"]["outcome"] == "not_applicable"


@pytest.mark.parametrize(
    ("fixture_name", "expected_error_counts", "expected_children_with_errors", "expected_summary"),
    [
        (
            "worker_500_retry_exhausted",
            {"SERVER": 1},
            1,
            {
                "error": True,
                "error_category": "SERVER",
                "prompt_preview": "Summarize the data",
                "result_preview_contains": "retry exhausted",
                "error_message_contains": "500 INTERNAL",
            },
        ),
        (
            "worker_500_then_success",
            {},
            0,
            {
                "error": False,
                "error_category": None,
                "prompt_preview": "What is the status?",
                "final_answer": "Server recovered answer",
            },
        ),
    ],
)
async def test_session_report_child_outcomes_worker_server_retry_families(
    tmp_path: Path,
    fixture_name: str,
    expected_error_counts: dict[str, int],
    expected_children_with_errors: int,
    expected_summary: dict[str, Any],
):
    """Worker server retry exhaustion and recovery should stay queryable in child summaries."""
    _result, report = await _run_fixture_report(fixture_name, tmp_path)

    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_total_batch_dispatches"] == 0
    assert child["child_error_counts"] == expected_error_counts
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["child_error_categories"] == expected_error_counts
    assert child["total_summaries"] == 1
    assert child["children_with_errors"] == expected_children_with_errors

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is expected_summary["error"]
    assert summary["error_category"] == expected_summary["error_category"]
    assert summary["prompt_preview"] == expected_summary["prompt_preview"]
    assert summary["structured_output"]["expected"] is False
    assert summary["structured_output"]["outcome"] == "not_applicable"

    if "final_answer" in expected_summary:
        assert summary["final_answer"] == expected_summary["final_answer"]
        assert summary["result_preview"] == expected_summary["final_answer"]
        assert summary["error_message"] is None
    else:
        assert expected_summary["result_preview_contains"] in summary["result_preview"]
        assert expected_summary["error_message_contains"] in summary["error_message"]
        assert summary["final_answer"] == summary["result_preview"]


async def test_session_report_child_outcomes_finish_reason_empty_output(tmp_path: Path):
    """SAFETY-finished empty outputs should remain queryable via child summaries."""
    result, report = await _run_fixture_report("worker_empty_response_finish_reason", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 2
    assert child["child_total_batch_dispatches"] == 1
    assert child["child_error_counts"] == {"SAFETY": 1}
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 2}
    assert child["child_error_categories"] == {"SAFETY": 1}
    assert child["total_summaries"] == 2
    assert child["children_with_errors"] == 1

    summaries = {item["fanout"]: item for item in child["summaries"]}

    ok = summaries[0]
    assert ok["depth"] == 1
    assert ok["error"] is False
    assert ok["error_category"] is None
    assert ok["prompt_preview"] == "Analyze market A"
    assert ok["final_answer"] == "Analysis: positive trend"
    assert ok["result_preview"] == "Analysis: positive trend"
    assert ok["error_message"] is None
    assert ok["structured_output"]["outcome"] == "not_applicable"

    blocked = summaries[1]
    assert blocked["depth"] == 1
    assert blocked["error"] is True
    assert blocked["error_category"] == "SAFETY"
    assert blocked["prompt_preview"] == "Analyze market B"
    assert "[RLM ERROR]" in blocked["final_answer"]
    assert "SAFETY before producing a final answer" in blocked["error_message"]
    assert blocked["final_answer"] == blocked["result_preview"]
    assert blocked["structured_output"]["expected"] is False
    assert blocked["structured_output"]["outcome"] == "not_applicable"


async def test_session_report_child_outcomes_finish_reason_truncated_output(tmp_path: Path):
    """MAX_TOKENS-truncated worker outputs should remain queryable without error flags."""
    result, report = await _run_fixture_report("worker_max_tokens_truncated", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    child = report["child_outcomes"]
    assert report["overview"]["status"] == "completed"
    assert child["child_dispatch_count"] == 1
    assert child["child_total_batch_dispatches"] == 0
    assert child["child_error_counts"] == {}
    assert child["structured_output_failures"] == 0
    assert child["structured_output_outcomes"] == {"not_applicable": 1}
    assert child["child_error_categories"] == {}
    assert child["total_summaries"] == 1
    assert child["children_with_errors"] == 0

    summary = child["summaries"][0]
    assert (summary["depth"], summary["fanout"]) == (1, 0)
    assert summary["error"] is False
    assert summary["error_category"] is None
    assert summary["error_message"] is None
    assert summary["prompt_preview"] == "Provide a detailed market analysis"
    assert (
        summary["final_answer"]
        == "The analysis shows that the market is trending upward with several key indicators suggest"
    )
    assert summary["final_answer"] == summary["result_preview"]
    assert summary["structured_output"]["expected"] is False
    assert summary["structured_output"]["outcome"] == "not_applicable"
