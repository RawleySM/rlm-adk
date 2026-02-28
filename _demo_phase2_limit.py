import asyncio
from unittest.mock import MagicMock
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL

async def main():
    repl = LocalREPL()
    tool = REPLTool(repl=repl, max_calls=2)
    tc = MagicMock()
    tc.state = {}

    r1 = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
    print("Call 1 - call_number:", r1["call_number"], "stderr:", repr(r1["stderr"]))
    assert r1["call_number"] == 1
    assert r1["stderr"] == ""

    r2 = await tool.run_async(args={"code": "x = 2"}, tool_context=tc)
    print("Call 2 - call_number:", r2["call_number"], "stderr:", repr(r2["stderr"]))
    assert r2["call_number"] == 2
    assert r2["stderr"] == ""

    r3 = await tool.run_async(args={"code": "x = 3"}, tool_context=tc)
    print("Call 3 - call_number:", r3["call_number"], "stderr:", repr(r3["stderr"][:50]))
    assert r3["call_number"] == 3
    assert "call limit reached" in r3["stderr"].lower()
    assert r3["stdout"] == ""

    repl.cleanup()
    print()
    print("PASS: call limit enforced after max_calls=2")

asyncio.run(main())
