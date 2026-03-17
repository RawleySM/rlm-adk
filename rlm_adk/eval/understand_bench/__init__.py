"""Understand-phase benchmark suite for RLM-ADK.

Evaluates whether an agent can detect insufficient context during the
Understand phase and emit a correct retrieval_order artifact identifying
missing external dependencies.
"""

__all__ = [
    "BenchmarkCase",
    "BenchmarkResult",
    "MissingContextCategory",
    "MissingContextItem",
    "load_case",
    "score_result",
]


def __getattr__(name: str):
    if name in ("MissingContextCategory", "MissingContextItem", "BenchmarkCase"):
        from rlm_adk.eval.understand_bench.types import (
            BenchmarkCase,
            MissingContextCategory,
            MissingContextItem,
        )

        _map = {
            "MissingContextCategory": MissingContextCategory,
            "MissingContextItem": MissingContextItem,
            "BenchmarkCase": BenchmarkCase,
        }
        return _map[name]
    if name == "BenchmarkResult":
        from rlm_adk.eval.understand_bench.scoring import BenchmarkResult

        return BenchmarkResult
    if name == "load_case":
        from rlm_adk.eval.understand_bench.loader import load_case

        return load_case
    if name == "score_result":
        from rlm_adk.eval.understand_bench.scoring import score_result

        return score_result
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
