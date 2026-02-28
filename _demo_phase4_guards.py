import asyncio
from unittest.mock import MagicMock
from rlm_adk.callbacks.worker_retry import (
    _SET_MODEL_RESPONSE_TOOL_NAME,
    WorkerRetryPlugin,
    make_worker_tool_callbacks,
)

# 1. Constant value
assert _SET_MODEL_RESPONSE_TOOL_NAME == "set_model_response"
print("_SET_MODEL_RESPONSE_TOOL_NAME:", repr(_SET_MODEL_RESPONSE_TOOL_NAME))

# Helper
def make_tool(name):
    t = MagicMock()
    t.name = name
    return t

def make_tc():
    tc = MagicMock()
    tc.state = {}
    return tc

async def main():
    plugin = WorkerRetryPlugin(max_retries=2)

    # 2. extract_error_from_result IGNORES execute_code (REPLTool)
    err = await plugin.extract_error_from_result(
        tool=make_tool("execute_code"),
        tool_args={"code": ""},  # empty -- would trigger for set_model_response
        tool_context=make_tc(),
        result={"output": ""},
    )
    assert err is None
    print("extract_error ignores execute_code:", err is None)

    # 3. extract_error_from_result CATCHES empty set_model_response
    err2 = await plugin.extract_error_from_result(
        tool=make_tool("set_model_response"),
        tool_args={"summary": "", "title": "ok"},
        tool_context=make_tc(),
        result={"summary": "", "title": "ok"},
    )
    assert err2 is not None
    assert "empty" in err2["details"].lower()
    print("extract_error catches empty set_model_response:", err2 is not None)

    # 4. on_tool_error_cb ignores execute_code errors
    _, error_cb = make_worker_tool_callbacks(max_retries=2)
    result = await error_cb(
        make_tool("execute_code"),
        {"code": "bad"},
        make_tc(),
        RuntimeError("exec failed"),
    )
    assert result is None
    print("error_cb ignores execute_code errors:", result is None)

    # 5. after_cb does NOT set _structured_result for execute_code
    after_cb, _ = make_worker_tool_callbacks(max_retries=2)
    agent = MagicMock()
    agent._structured_result = None
    tc = make_tc()
    tc._invocation_context.agent = agent
    await after_cb(
        make_tool("execute_code"),
        {"code": "print(1)"},
        tc,
        {"output": "1"},
    )
    assert agent._structured_result is None
    print("after_cb ignores execute_code: _structured_result still None:", True)

    print()
    print("PASS: tool-name guards protect REPLTool from retry/reflection interference")

asyncio.run(main())
