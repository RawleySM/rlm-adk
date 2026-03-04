import asyncio
from unittest.mock import MagicMock
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL

async def main():
    repl = LocalREPL()
    traces = []

    def fake_flush():
        return {"worker_dispatch_count": 5, "obs:worker_dispatch_latency_ms": [12.3]}

    tool = REPLTool(repl=repl, trace_holder=traces, flush_fn=fake_flush)
    tc = MagicMock()
    tc.state = {}

    await tool.run_async(args={"code": "x = 1 + 2"}, tool_context=tc)

    # Trace was recorded
    print("traces collected:", len(traces))
    assert len(traces) == 1
    print("trace type:", type(traces[0]).__name__)

    # flush_fn wrote accumulators into tool_context.state
    print("tc.state keys:", sorted(tc.state.keys()))
    assert tc.state["worker_dispatch_count"] == 5
    assert tc.state["obs:worker_dispatch_latency_ms"] == [12.3]
    print("worker_dispatch_count:", tc.state["worker_dispatch_count"])
    print("obs:worker_dispatch_latency_ms:", tc.state["obs:worker_dispatch_latency_ms"])

    repl.cleanup()
    print()
    print("PASS: trace recording and telemetry flush work")

asyncio.run(main())
