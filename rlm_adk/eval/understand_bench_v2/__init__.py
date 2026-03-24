"""Understand-Phase Benchmark v2 — file-based, multi-format tax return benchmark.

Unlike v1 (inline JSON context), v2 uses real files in diverse formats
(PDF, CSV, Excel, image, plain text, JSON) that require different
processing skills. The benchmark evaluates both:
  1. Missing-context detection (same as v1)
  2. Format-processing skill identification (new in v2)
"""

from rlm_adk.eval.understand_bench_v2.types import (
    BenchmarkCaseV2,
    FileRef,
    FormatSkill,
    MissingContextCategory,
    MissingContextItem,
    ProcessingChallenge,
)

__all__ = [
    "BenchmarkCaseV2",
    "FileRef",
    "FormatSkill",
    "MissingContextCategory",
    "MissingContextItem",
    "ProcessingChallenge",
]
