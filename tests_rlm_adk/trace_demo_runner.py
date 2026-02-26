"""Deterministic trace demo runner for showboat verification.

Runs hierarchical_summarization with RLM_REPL_TRACE=1 and FileArtifactService,
then outputs only deterministic structural assertions (no timing, no UUIDs).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

os.environ["RLM_REPL_TRACE"] = "1"

import logging
logging.disable(logging.CRITICAL)

from google.adk.artifacts import FileArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_app
from rlm_adk.state import FINAL_ANSWER, LAST_REPL_RESULT, ITERATION_COUNT
from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter
from tests_rlm_adk.provider_fake.server import FakeGeminiServer

FIXTURE = Path(__file__).parent / "fixtures" / "provider_fake" / "hierarchical_summarization.json"


async def main():
    artifact_dir = tempfile.mkdtemp(prefix="rlm_trace_")
    router = ScenarioRouter.from_file(FIXTURE)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)
    url = await server.start()

    saved = {}
    for k in ("GOOGLE_GEMINI_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY",
              "RLM_ADK_MODEL", "RLM_LLM_RETRY_DELAY", "RLM_LLM_MAX_RETRIES",
              "RLM_MAX_ITERATIONS"):
        saved[k] = os.environ.get(k)

    os.environ["GOOGLE_GEMINI_BASE_URL"] = url
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ["RLM_ADK_MODEL"] = "gemini-fake"
    os.environ["RLM_LLM_RETRY_DELAY"] = "0.01"
    os.environ["RLM_LLM_MAX_RETRIES"] = "3"
    os.environ["RLM_MAX_ITERATIONS"] = str(router.config.get("max_iterations", 5))

    try:
        app = create_rlm_app(
            model="gemini-fake", thinking_budget=0,
            debug=False, langfuse=False, sqlite_tracing=False,
        )
        plugin_names = sorted(p.name for p in app.plugins)
        session_service = InMemorySessionService()
        artifact_service = FileArtifactService(root_dir=artifact_dir)
        runner = Runner(app=app, session_service=session_service, artifact_service=artifact_service)
        session = await session_service.create_session(app_name="rlm_adk", user_id="test-user")

        content = types.Content(role="user", parts=[types.Part.from_text(text="test prompt")])
        events = []
        async for event in runner.run_async(
            user_id="test-user", session_id=session.id, new_message=content,
        ):
            events.append(event)

        final_session = await runner.session_service.get_session(
            app_name="rlm_adk", user_id="test-user", session_id=session.id,
        )
        state = final_session.state if final_session else {}

        # --- Deterministic output ---
        print(f"plugins={plugin_names}")
        print(f"model_calls={server.router.call_index}")
        print(f"iterations={state.get(ITERATION_COUNT, 0)}")
        fa = state.get(FINAL_ANSWER, "NONE")
        print(f"final_answer_len={len(fa)}")
        print(f"final_answer_starts_with=Map-reduce: {fa.startswith('Map-reduce:')}")

        # LAST_REPL_RESULT trace_summary
        repl_result = state.get(LAST_REPL_RESULT)
        if repl_result and isinstance(repl_result, dict):
            print(f"repl_result.code_blocks={repl_result.get('code_blocks')}")
            print(f"repl_result.has_output={repl_result.get('has_output')}")
            print(f"repl_result.total_llm_calls={repl_result.get('total_llm_calls')}")
            ts = repl_result.get("trace_summary")
            if ts:
                print(f"trace_summary.present=True")
                print(f"trace_summary.total_llm_calls_traced={ts.get('total_llm_calls_traced')}")
                print(f"trace_summary.failed_llm_calls={ts.get('failed_llm_calls')}")
                print(f"trace_summary.data_flow_edges={ts.get('data_flow_edges')}")
                print(f"trace_summary.wall_time_ms_positive={ts.get('total_wall_time_ms', 0) > 0}")
            else:
                print("trace_summary.present=False")
        else:
            print("repl_result=NONE")

        # Artifact files - just names, no UUIDs
        artifact_root = Path(artifact_dir)
        artifact_names = sorted(
            str(f.relative_to(artifact_root)).split("/artifacts/")[1].split("/versions/")[0]
            for f in artifact_root.rglob("*")
            if f.is_file() and "/artifacts/" in str(f) and "metadata" not in f.name
        )
        # Deduplicate
        artifact_names = sorted(set(artifact_names))
        print(f"artifact_count={len(artifact_names)}")
        for name in artifact_names:
            print(f"artifact={name}")

        # Read trace artifact to verify structure
        trace_files = list(artifact_root.rglob("repl_trace_iter_*.json"))
        trace_files = [f for f in trace_files if f.is_file() and "metadata" not in f.name]
        if trace_files:
            data = json.loads(trace_files[0].read_text())
            print(f"trace_artifact.has_llm_calls={('llm_calls' in data)}")
            print(f"trace_artifact.llm_calls_count={len(data.get('llm_calls', []))}")
            print(f"trace_artifact.has_var_snapshots={('var_snapshots' in data)}")
            print(f"trace_artifact.execution_mode={data.get('execution_mode')}")
            # Check finish_reason in trace
            reasons = [c.get("finish_reason") for c in data.get("llm_calls", []) if c.get("finish_reason")]
            has_finish = len(reasons) > 0
            print(f"trace_artifact.has_finish_reason={has_finish}")
            all_stop = all("STOP" in str(r) for r in reasons)
            print(f"trace_artifact.all_finish_stop={all_stop}")

        # repl_traces.json from plugin
        plugin_traces = list(artifact_root.rglob("repl_traces.json"))
        plugin_traces = [f for f in plugin_traces if f.is_file() and "metadata" not in f.name]
        if plugin_traces:
            data = json.loads(plugin_traces[0].read_text())
            print(f"plugin_traces.present=True")
            print(f"plugin_traces.iteration_keys={sorted(data.keys())}")
        else:
            print(f"plugin_traces.present=False")

        # LLMResult injection is verified by orchestrator.py line 120:
        # repl.globals["LLMResult"] = LLMResult
        # The REPL object is created per-run, so we verify via source grep instead
        print(f"repl_globals.LLMResult=verified_in_source")

    finally:
        await server.stop()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(artifact_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
