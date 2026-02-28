import asyncio
from unittest.mock import MagicMock
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL

async def main():
    repl = LocalREPL()
    tool = REPLTool(repl=repl)
    tc = MagicMock()
    tc.state = {}

    # Test 1: stdout capture
    r1 = await tool.run_async(args={"code": "print('hello from REPLTool')"}, tool_context=tc)
    print("Test 1 - stdout:", repr(r1["stdout"].strip()))
    print("Test 1 - stderr:", repr(r1["stderr"]))
    assert r1["stdout"].strip() == "hello from REPLTool"
    assert r1["stderr"] == ""

    # Test 2: syntax error returns stderr
    r2 = await tool.run_async(args={"code": "def("}, tool_context=tc)
    print("Test 2 - syntax error stderr:", "SyntaxError" in r2["stderr"])
    assert "SyntaxError" in r2["stderr"]

    # Test 3: variable persistence across calls
    await tool.run_async(args={"code": "x = 42"}, tool_context=tc)
    r3 = await tool.run_async(args={"code": "print(x * 2)"}, tool_context=tc)
    print("Test 3 - variable persistence:", repr(r3["stdout"].strip()))
    assert "84" in r3["stdout"]

    # Test 4: variables dict in response
    r4 = await tool.run_async(args={"code": "greeting = 'world'"}, tool_context=tc)
    print("Test 4 - variables:", r4["variables"].get("greeting"))
    assert r4["variables"]["greeting"] == "world"

    repl.cleanup()
    print()
    print("PASS: sync execution, error handling, and variable persistence all work")

asyncio.run(main())
