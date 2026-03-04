# Phase 2: Child Orchestrator Factory

*2026-03-04T18:31:10Z by Showboat 0.6.0*
<!-- showboat-id: 5c1254bc-fe7d-4f53-9aa7-b9a4d92b1d19 -->

create_child_orchestrator() is the factory that produces fully-configured child orchestrators for recursive dispatch. It builds a condensed reasoning agent (no repomix context), wires depth-suffixed output keys to prevent state collisions, and returns a non-persistent RLMOrchestratorAgent ready to run as a nested sub-task.

```bash
sed -n "275,283p" rlm_adk/agent.py
```

```output
def create_child_orchestrator(
    model: str,
    depth: int,
    prompt: str,
    worker_pool: WorkerPool | None = None,
    max_iterations: int = 10,
    thinking_budget: int = 512,
    output_schema: type | None = None,
) -> RLMOrchestratorAgent:
```

```bash
sed -n "98,105p" rlm_adk/utils/prompts.py
```

```output
RLM_CHILD_STATIC_INSTRUCTION = textwrap.dedent("""\
You are tasked with answering a query. You have access to two tools:

1. execute_code(code="..."): Execute Python in a persistent REPL environment.
   Variables persist between calls. Returns stdout, stderr, and variables.
2. set_model_response(final_answer="...", reasoning_summary="..."):
   Provide your final answer. Call ONLY when analysis is complete.

```

Key design decisions: (1) depth-suffixed output_key ("reasoning_output@d{depth}") prevents state collisions between parent and child sessions, (2) include_repomix=False keeps the child prompt lean (~1/3 the size of the root instruction), and (3) persistent=False ensures child orchestrators are disposable — they run once and discard their state.

```bash
sed -n "298,306p" rlm_adk/agent.py
```

```output
    reasoning = create_reasoning_agent(
        model,
        static_instruction=RLM_CHILD_STATIC_INSTRUCTION,
        thinking_budget=thinking_budget,
        include_repomix=False,
        name=f"child_reasoning_d{depth}",
        output_key=f"reasoning_output@d{depth}",
        output_schema=output_schema,
    )
```

```bash
sed -n "311,321p" rlm_adk/agent.py
```

```output
    return RLMOrchestratorAgent(
        name=f"child_orchestrator_d{depth}",
        description=f"Child orchestrator at depth {depth}",
        reasoning_agent=reasoning,
        root_prompt=prompt,
        persistent=False,
        worker_pool=worker_pool,
        depth=depth,
        output_schema=output_schema,
        sub_agents=[reasoning],
    )
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_phase2_child_factory.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
7 passed
```

All 7 Phase 2 tests pass. The factory produces fully configured child orchestrators: condensed instruction, depth-suffixed output keys, shared worker pool, and non-persistent lifecycle. Ready for Phase 3 recursive dispatch integration.
