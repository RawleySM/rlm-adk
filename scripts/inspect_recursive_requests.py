#!/usr/bin/env python
"""Run fake_recursive_ping fixture and dump what the system sent to each LLM call.

Inspects captured_requests from the FakeGeminiServer to see what context
(contents, systemInstruction) each recursive layer received.
"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Force non-LiteLLM mode so requests hit the fake Gemini server directly
os.environ.pop("RLM_ADK_LITELLM", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("OPENAI_API_BASE", None)

FIXTURE = PROJECT_ROOT / "tests_rlm_adk" / "fixtures" / "provider_fake" / "fake_recursive_ping.json"


def _summarize_content(content: dict) -> str:
    """Summarize a single content entry (role + parts preview)."""
    role = content.get("role", "?")
    parts = content.get("parts", [])
    summaries = []
    for p in parts:
        if "text" in p:
            text = p["text"]
            if len(text) > 200:
                text = text[:200] + "..."
            summaries.append(f"TEXT({len(p['text'])} chars): {text}")
        elif "functionCall" in p:
            fc = p["functionCall"]
            summaries.append(f"FUNC_CALL: {fc['name']}(...)")
        elif "functionResponse" in p:
            fr = p["functionResponse"]
            summaries.append(f"FUNC_RESP: {fr['name']}(...)")
        else:
            summaries.append(f"OTHER: {list(p.keys())}")
    return f"  [{role}] " + " | ".join(summaries)


async def main() -> None:
    from tests_rlm_adk.provider_fake.contract_runner import (
        run_fixture_contract_with_plugins,
    )

    result = await run_fixture_contract_with_plugins(
        FIXTURE,
        prompt="test prompt",
        traces_db_path="/tmp/recursive_ping_traces.db",
        repl_trace_level=1,
    )

    router = result.router
    captured = router.captured_requests
    print(f"\n{'='*80}")
    print(f"CAPTURED {len(captured)} LLM REQUESTS")
    print(f"Contract passed: {result.contract.passed}")
    if not result.contract.passed:
        print(f"Diagnostics: {result.contract.diagnostics()}")
    print(f"{'='*80}\n")

    for i, req in enumerate(captured):
        fixture_entry = router._responses[i] if i < len(router._responses) else {}
        caller = fixture_entry.get("caller", "?")
        note = fixture_entry.get("note", "")

        print(f"\n{'─'*80}")
        print(f"REQUEST #{i} | caller={caller} | {note}")
        print(f"{'─'*80}")

        # System instruction
        sys_instr = req.get("systemInstruction")
        if sys_instr:
            parts = sys_instr.get("parts", [])
            for p in parts:
                text = p.get("text", "")
                if len(text) > 500:
                    print(f"  SYSTEM_INSTRUCTION ({len(text)} chars): {text[:500]}...")
                else:
                    print(f"  SYSTEM_INSTRUCTION ({len(text)} chars): {text}")
        else:
            print("  SYSTEM_INSTRUCTION: <none>")

        # Contents (conversation history) - full dump for worker calls
        contents = req.get("contents", [])
        print(f"  CONTENTS: {len(contents)} entries")
        if caller == "worker":
            for ci, c in enumerate(contents):
                role = c.get("role", "?")
                parts = c.get("parts", [])
                print(f"  CONTENT[{ci}] role={role}:")
                for pi, p in enumerate(parts):
                    if "text" in p:
                        print(f"    part[{pi}] TEXT ({len(p['text'])} chars):")
                        text = p["text"]
                        # Print full text up to 1500 chars
                        if len(text) > 1500:
                            print(f"      {text[:1500]}...")
                        else:
                            print(f"      {text}")
                    elif "functionCall" in p:
                        fc = p["functionCall"]
                        print(f"    part[{pi}] FUNC_CALL: {fc['name']}")
                    elif "functionResponse" in p:
                        fr = p["functionResponse"]
                        print(f"    part[{pi}] FUNC_RESP: {fr['name']}")
        else:
            for c in contents:
                print(_summarize_content(c))

        # Tools
        tools = req.get("tools", [])
        if tools:
            tool_names = []
            for t in tools:
                for fd in t.get("functionDeclarations", []):
                    tool_names.append(fd.get("name", "?"))
            print(f"  TOOLS: {tool_names}")

    print(f"\n{'='*80}")
    print("FINAL STATE (selected keys):")
    for key in sorted(result.final_state):
        if any(key.startswith(p) for p in ("obs:", "final_", "iteration", "reasoning_")):
            val = result.final_state[key]
            val_str = str(val)
            if len(val_str) > 100:
                val_str = val_str[:100] + "..."
            print(f"  {key} = {val_str}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
