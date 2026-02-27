"""RLM ADK Evaluation utilities - DuckDB analytics and session forking."""

__all__ = ["TraceReader"]


def __getattr__(name: str):
    if name == "TraceReader":
        from rlm_adk.eval.trace_reader import TraceReader

        return TraceReader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
