import asyncio
import inspect
from unittest.mock import MagicMock
from pydantic import BaseModel

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.tools.repl_tool import REPLTool
from google.adk.tools.set_model_response_tool import SetModelResponseTool


class SampleSchema(BaseModel):
    answer: str
    confidence: float = 0.0


def make_ctx():
    ctx = MagicMock()
    ctx.invocation_id = "demo"
    ctx.session.state = {}
    return ctx


def patch_worker_run(worker, run_fn):
    object.__setattr__(worker, "run_async", run_fn)


async def main():
    # 1. Verify create_dispatch_closures accepts worker_repl param
    sig = inspect.signature(create_dispatch_closures)
    assert "worker_repl" in sig.parameters
    print("create_dispatch_closures has worker_repl param:", True)

    # 2. WITH worker_repl -> worker gets REPLTool
    pool1 = WorkerPool(default_model="test-model", pool_size=1)
    pool1.ensure_initialized()
    worker1 = pool1._pools["test-model"].get_nowait()
    captured1 = {}

    async def capture_run1(_ctx):
        captured1["tools"] = list(worker1.tools)
        captured1["output_schema"] = worker1.output_schema
        worker1._result = '{"answer": "test", "confidence": 0.9}'
        worker1._result_ready = True
        worker1._structured_result = {"answer": "test", "confidence": 0.9}
        return
        yield

    patch_worker_run(worker1, capture_run1)
    pool1._pools["test-model"].put_nowait(worker1)

    ctx = make_ctx()
    eq1 = asyncio.Queue()
    mock_repl = MagicMock()

    llm_query1, _ = create_dispatch_closures(pool1, ctx, eq1, worker_repl=mock_repl)
    await llm_query1("test", output_schema=SampleSchema)

    tool1 = captured1["tools"][0]
    assert isinstance(tool1, REPLTool)
    print("With worker_repl: tool is REPLTool:", isinstance(tool1, REPLTool))
    print("  output_schema is SampleSchema:", captured1["output_schema"] is SampleSchema)

    # 3. WITHOUT worker_repl -> worker gets SetModelResponseTool
    pool2 = WorkerPool(default_model="test-model", pool_size=1)
    pool2.ensure_initialized()
    worker2 = pool2._pools["test-model"].get_nowait()
    captured2 = {}

    async def capture_run2(_ctx):
        captured2["tools"] = list(worker2.tools)
        captured2["output_schema"] = worker2.output_schema
        worker2._result = '{"answer": "test", "confidence": 0.9}'
        worker2._result_ready = True
        worker2._structured_result = {"answer": "test", "confidence": 0.9}
        return
        yield

    patch_worker_run(worker2, capture_run2)
    pool2._pools["test-model"].put_nowait(worker2)

    ctx2 = make_ctx()
    eq2 = asyncio.Queue()
    llm_query2, _ = create_dispatch_closures(pool2, ctx2, eq2)  # no worker_repl
    await llm_query2("test", output_schema=SampleSchema)

    tool2 = captured2["tools"][0]
    assert isinstance(tool2, SetModelResponseTool)
    print("Without worker_repl: tool is SetModelResponseTool:", isinstance(tool2, SetModelResponseTool))
    print("  output_schema is SampleSchema:", captured2["output_schema"] is SampleSchema)

    # 4. Cleanup resets all wiring
    released = await pool2.acquire()
    assert released.output_schema is None
    assert released.tools == []
    assert released.after_tool_callback is None
    assert released.on_tool_error_callback is None
    print("Cleanup resets: output_schema=None, tools=[], callbacks=None:", True)

    print()
    print("PASS: bifurcated wiring routes REPLTool/SetModelResponseTool correctly")

asyncio.run(main())
