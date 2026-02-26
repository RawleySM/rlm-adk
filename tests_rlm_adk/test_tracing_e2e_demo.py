"""E2E tracing demo: runs hierarchical_summarization with full observability.

Exercises the end-to-end trace pipeline:
  RLM_REPL_TRACE=1 -> REPLTrace per code block -> trace_summary in LAST_REPL_RESULT
  -> REPLTracingPlugin saves repl_traces.json artifact
  -> save_repl_trace() saves per-block JSON artifacts
  -> ObservabilityPlugin records finish_reason counters
  -> LLMResult metadata flows through dispatch closures

Designed to be run standalone or via pytest, capturing all outputs for
showboat demo verification.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

# --- Set trace env BEFORE any rlm_adk imports ---
os.environ["RLM_REPL_TRACE"] = "1"

from google.adk.artifacts import FileArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_app
from rlm_adk.state import (
    FINAL_ANSWER,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    OBS_FINISH_SAFETY_COUNT,
    OBS_WORKER_TIMEOUT_COUNT,
    OBS_ZERO_PROGRESS_ITERATIONS,
    OBS_CONSECUTIVE_ZERO_PROGRESS,
)
from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter
from tests_rlm_adk.provider_fake.server import FakeGeminiServer


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "provider_fake" / "hierarchical_summarization.json"


async def run_demo():
    """Run hierarchical_summarization with full tracing + artifacts."""

    # --- Setup artifact dir ---
    artifact_dir = tempfile.mkdtemp(prefix="rlm_trace_demo_")
    print(f"ARTIFACT_DIR={artifact_dir}")

    # --- Start fake server ---
    router = ScenarioRouter.from_file(FIXTURE_PATH)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)
    url = await server.start()

    saved_env = {}
    env_keys = (
        "GOOGLE_GEMINI_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY",
        "RLM_ADK_MODEL", "RLM_LLM_RETRY_DELAY", "RLM_LLM_MAX_RETRIES",
        "RLM_MAX_ITERATIONS",
    )
    for key in env_keys:
        saved_env[key] = os.environ.get(key)

    os.environ["GOOGLE_GEMINI_BASE_URL"] = url
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ["RLM_ADK_MODEL"] = "gemini-fake"
    os.environ["RLM_LLM_RETRY_DELAY"] = "0.01"
    os.environ["RLM_LLM_MAX_RETRIES"] = "3"
    os.environ["RLM_MAX_ITERATIONS"] = str(router.config.get("max_iterations", 5))

    try:
        # --- Create app with ALL plugins enabled ---
        app = create_rlm_app(
            model="gemini-fake",
            thinking_budget=0,
            debug=True,           # DebugLoggingPlugin
            langfuse=False,
            sqlite_tracing=False,  # skip sqlite for demo
        )

        # List registered plugins
        plugin_names = [p.name for p in app.plugins]
        print(f"PLUGINS={plugin_names}")

        # --- Create runner with FileArtifactService ---
        session_service = InMemorySessionService()
        artifact_service = FileArtifactService(root_dir=artifact_dir)
        runner = Runner(
            app=app,
            session_service=session_service,
            artifact_service=artifact_service,
        )

        session = await session_service.create_session(
            app_name="rlm_adk",
            user_id="test-user",
        )

        # --- Run to completion ---
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text="test prompt")],
        )

        events = []
        async for event in runner.run_async(
            user_id="test-user",
            session_id=session.id,
            new_message=content,
        ):
            events.append(event)

        # --- Fetch final state ---
        final_session = await runner.session_service.get_session(
            app_name="rlm_adk",
            user_id="test-user",
            session_id=session.id,
        )
        state = final_session.state if final_session else {}

        # ===== REPORT =====
        print(f"\n{'='*60}")
        print("TRACE DEMO REPORT")
        print(f"{'='*60}")

        # 1. Final answer
        fa = state.get(FINAL_ANSWER, "NONE")
        print(f"FINAL_ANSWER={fa[:120]}")

        # 2. Iteration count
        print(f"ITERATION_COUNT={state.get(ITERATION_COUNT, 0)}")

        # 3. Total model calls
        print(f"MODEL_CALLS={server.router.call_index}")

        # 4. LAST_REPL_RESULT (should have trace_summary)
        repl_result = state.get(LAST_REPL_RESULT)
        print(f"LAST_REPL_RESULT={json.dumps(repl_result, indent=2) if repl_result else 'NONE'}")

        # 5. Extract all REPL snapshots from events
        repl_snapshots = []
        for event in events:
            sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
            if LAST_REPL_RESULT in sd:
                repl_snapshots.append(sd[LAST_REPL_RESULT])
        print(f"\nREPL_SNAPSHOTS_COUNT={len(repl_snapshots)}")
        for i, snap in enumerate(repl_snapshots):
            has_trace = "trace_summary" in snap if isinstance(snap, dict) else False
            print(f"  snapshot[{i}]: code_blocks={snap.get('code_blocks', '?')} "
                  f"has_output={snap.get('has_output', '?')} "
                  f"total_llm_calls={snap.get('total_llm_calls', '?')} "
                  f"has_trace_summary={has_trace}")
            if has_trace:
                ts = snap["trace_summary"]
                print(f"    trace_summary: wall_time_ms={ts.get('total_wall_time_ms', '?'):.1f} "
                      f"llm_calls_traced={ts.get('total_llm_calls_traced', '?')} "
                      f"failed={ts.get('failed_llm_calls', '?')} "
                      f"data_flow_edges={ts.get('data_flow_edges', '?')}")

        # 6. Observability state keys
        print(f"\nOBS_FINISH_SAFETY_COUNT={state.get(OBS_FINISH_SAFETY_COUNT, 0)}")
        print(f"OBS_WORKER_TIMEOUT_COUNT={state.get(OBS_WORKER_TIMEOUT_COUNT, 0)}")
        print(f"OBS_ZERO_PROGRESS_ITERATIONS={state.get(OBS_ZERO_PROGRESS_ITERATIONS, 0)}")
        print(f"OBS_CONSECUTIVE_ZERO_PROGRESS={state.get(OBS_CONSECUTIVE_ZERO_PROGRESS, 0)}")

        # 7. Check for finish_reason in obs breakdown
        obs_keys = [k for k in state if k.startswith("obs:")]
        print(f"\nALL_OBS_KEYS={sorted(obs_keys)}")

        # 8. Artifact files on disk
        print(f"\nARTIFACT_FILES:")
        artifact_root = Path(artifact_dir)
        for f in sorted(artifact_root.rglob("*")):
            if f.is_file():
                rel = f.relative_to(artifact_root)
                size = f.stat().st_size
                print(f"  {rel} ({size} bytes)")
                # Show trace JSON content if it's a trace file
                if "trace" in str(rel) and str(rel).endswith(".json"):
                    try:
                        data = json.loads(f.read_text())
                        # Print compact summary
                        if isinstance(data, dict):
                            top_keys = list(data.keys())[:5]
                            print(f"    keys={top_keys}")
                            if "llm_calls" in data:
                                print(f"    llm_calls_count={len(data['llm_calls'])}")
                                for call in data["llm_calls"][:3]:
                                    print(f"      call[{call.get('index', '?')}]: "
                                          f"elapsed={call.get('elapsed_ms', '?')}ms "
                                          f"error={call.get('error', '?')} "
                                          f"finish_reason={call.get('finish_reason', '?')}")
                    except Exception:
                        pass

        # 9. LLMResult in worker events
        print(f"\nWORKER_EVENTS:")
        for event in events:
            author = getattr(event, "author", "")
            if author.startswith("worker_"):
                sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
                print(f"  author={author} state_keys={list(sd.keys())[:5]}")

        # 10. Event count
        print(f"\nTOTAL_EVENTS={len(events)}")
        print(f"{'='*60}")

    finally:
        await server.stop()
        for key, val in saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        # Clean up artifact dir
        shutil.rmtree(artifact_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_demo())
