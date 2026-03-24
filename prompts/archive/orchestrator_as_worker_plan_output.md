Here is the comprehensive, step-by-step TDD implementation plan to refactor the `rlm-adk` codebase to the **Orchestrator-as-Worker** model.

---

# TDD Implementation Plan: Orchestrator-as-Worker Refactor

## Overview: The "Orchestrator-as-Worker" Architecture
Currently, the `rlm-adk` system uses a central `RLMOrchestratorAgent` that can run a REPL (`execute_code` tool). This orchestrator delegates sub-tasks to a `WorkerPool`, which currently creates bare `LlmAgent` instances. These worker agents are designed as "leaf" nodes—they evaluate a prompt and return a string, but they **lack the ability to execute code** or perform their own iterative REPL reasoning.

**The Objective:** We need to refactor the system so that the `WorkerPool` creates and dispatches full `RLMOrchestratorAgent` instances instead of bare LLM agents. 

By treating the Orchestrator itself as a Worker, we enable **true recursive reasoning**:
1. **Symmetry:** Every level of a sub-call possesses its own REPL and can write/execute code to solve its assigned sub-problem.
2. **Isolation:** Each recursive level gets its own isolated sandbox (temp directory) and state space (message history, iteration counts) so nested agents don't corrupt the parent's thought process.
3. **Infinite Depth:** Sub-agents can spawn their own sub-agents, limited only by a configurable `max_depth` guardrail.

This plan details the Red/Green/Refactor lifecycle required to safely implement this architectural shift.

---

## Phase 1: RED (Failing Tests)
Before modifying the application code, we must define the expected behavior through failing tests. Create or update `tests_rlm_adk/test_recursive_orchestration.py`.

### 1. Test Sub-Agent REPL Capability
Verify that a dispatched worker can independently execute code and return a REPL-derived answer.
```python
# tests_rlm_adk/test_recursive_orchestration.py
import pytest
from rlm_adk.dispatch import WorkerPool
from rlm_adk.state import CURRENT_DEPTH

@pytest.mark.asyncio
async def test_worker_can_use_repl(mock_invocation_context):
    """Test that a worker spawned by the pool is an Orchestrator with REPL access."""
    pool = WorkerPool()
    
    # A prompt that strictly requires code execution to solve reliably
    prompt = "Calculate the 17th Fibonacci number using a Python script and return only the number."
    
    # Dispatch the query
    results = await pool.llm_query_batched_async([prompt], context=mock_invocation_context)
    
    assert len(results) == 1
    result = results[0]
    
    # The final answer should be the correct Fibonacci number
    assert "1597" in result.text
    
    # Verify the sub-agent actually used the REPL (check events or state)
    # Assuming mock_invocation_context captures tool calls
    tool_calls = mock_invocation_context.get_tool_calls()
    assert any(tc.name == "execute_code" for tc in tool_calls), "Sub-agent did not use the REPL"
```

### 2. Test Recursion Guard
Verify that the system prevents infinite recursive dispatching.
```python
@pytest.mark.asyncio
async def test_max_depth_recursion_guard(mock_invocation_context):
    """Test that exceeding APP_MAX_DEPTH raises a RecursionError."""
    pool = WorkerPool()
    
    # Artificially set the context to the max depth
    mock_invocation_context.session.state["CURRENT_DEPTH"] = 3 # Assuming APP_MAX_DEPTH = 3
    
    prompt = "Delegate this task to another worker."
    
    with pytest.raises(RecursionError, match="Maximum orchestration depth exceeded"):
        await pool.llm_query_batched_async([prompt], context=mock_invocation_context)
```

### 3. Test State Isolation (Concurrency & Depth)
Verify that parent and child orchestrators do not overwrite each other's `MESSAGE_HISTORY`.
```python
@pytest.mark.asyncio
async def test_state_isolation_across_depths(mock_invocation_context):
    """Test that parent and child use isolated state keys."""
    mock_invocation_context.session.state["CURRENT_DEPTH"] = 1
    mock_invocation_context.session.state["MESSAGE_HISTORY_1"] = ["Parent Message"]
    
    pool = WorkerPool()
    await pool.llm_query_batched_async(["Child task"], context=mock_invocation_context)
    
    # Parent state should remain untouched by the child's execution
    assert mock_invocation_context.session.state["MESSAGE_HISTORY_1"] == ["Parent Message"]
    # Child state should exist at depth 2
    assert "MESSAGE_HISTORY_2" in mock_invocation_context.session.state
```

---

## Phase 2: GREEN (Implementation Steps)

### Step 1: Update `rlm_adk/state.py`
Add the necessary constants and update the `depth_key` utility to support horizontal concurrency (worker IDs) alongside vertical depth.

```python
# rlm_adk/state.py

CURRENT_DEPTH = "CURRENT_DEPTH"
APP_MAX_DEPTH = 3  # Configurable limit
DEPTH_SCOPED_KEYS = ["MESSAGE_HISTORY", "ITERATION_COUNT", "FINAL_ANSWER"]

def depth_key(base_key: str, depth: int, worker_id: str = "") -> str:
    """Generates a state key isolated by depth and optionally worker_id."""
    if base_key not in DEPTH_SCOPED_KEYS:
        return base_key
    suffix = f"_{depth}_{worker_id}" if worker_id else f"_{depth}"
    return f"{base_key}{suffix}"
```

### Step 2: Update `rlm_adk/agent.py`
Modify the factory to inject the shared `WorkerPool` and ensure fresh `LocalREPL` instances are created with depth/worker awareness.

```python
# rlm_adk/agent.py
from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.repl.local_repl import LocalREPL

def create_rlm_orchestrator(worker_pool=None, depth: int = 1, worker_id: str = "") -> RLMOrchestratorAgent:
    # Instantiate a fresh, isolated REPL for this specific orchestrator
    repl = LocalREPL(depth=depth, worker_id=worker_id)
    
    # Create the orchestrator, passing the shared pool so it can also dispatch
    agent = RLMOrchestratorAgent(
        repl=repl,
        worker_pool=worker_pool,
        depth=depth,
        worker_id=worker_id
    )
    return agent
```

### Step 3: Update `rlm_adk/orchestrator.py`
Refactor `RLMOrchestratorAgent` to be dynamically depth-aware and enforce the recursion guard.

```python
# rlm_adk/orchestrator.py
from rlm_adk.state import CURRENT_DEPTH, APP_MAX_DEPTH, depth_key

class RLMOrchestratorAgent:
    def __init__(self, repl, worker_pool, depth: int = 1, worker_id: str = ""):
        self.repl = repl
        self.worker_pool = worker_pool
        self.depth = depth
        self.worker_id = worker_id

    async def run(self, prompt: str, context):
        # 1. Recursion Guard
        if self.depth > APP_MAX_DEPTH:
            raise RecursionError(f"Maximum orchestration depth exceeded: {self.depth} > {APP_MAX_DEPTH}")

        # 2. Set Context Depth (useful for tools/telemetry)
        context.session.state[CURRENT_DEPTH] = self.depth

        # 3. Initialize Scoped State
        msg_key = depth_key("MESSAGE_HISTORY", self.depth, self.worker_id)
        iter_key = depth_key("ITERATION_COUNT", self.depth, self.worker_id)
        ans_key = depth_key("FINAL_ANSWER", self.depth, self.worker_id)

        context.session.state[msg_key] = [{"role": "user", "content": prompt}]
        context.session.state[iter_key] = 0

        # 4. Main Agent Loop (Yielding events)
        while context.session.state[iter_key] < MAX_ITERATIONS:
            # ... existing LLM call and tool execution logic ...
            # Ensure all state reads/writes use msg_key, iter_key, ans_key
            
            if final_answer_found:
                context.session.state[ans_key] = extracted_answer
                yield {"type": "final_answer", "content": extracted_answer}
                break
            
            context.session.state[iter_key] += 1
```

### Step 4: Update `rlm_adk/dispatch.py`
Refactor `WorkerPool` to instantiate `RLMOrchestratorAgent` workers and capture their yielded `FINAL_ANSWER`.

```python
# rlm_adk/dispatch.py
import uuid
from rlm_adk.agent import create_rlm_orchestrator
from rlm_adk.state import CURRENT_DEPTH, depth_key

class WorkerPool:
    async def llm_query_batched_async(self, prompts: list[str], context) -> list:
        parent_depth = context.session.state.get(CURRENT_DEPTH, 1)
        child_depth = parent_depth + 1
        
        tasks = []
        for prompt in prompts:
            worker_id = str(uuid.uuid4())[:8]
            # Create an Orchestrator-as-Worker
            worker = create_rlm_orchestrator(
                worker_pool=self, 
                depth=child_depth, 
                worker_id=worker_id
            )
            tasks.append(self._consume_events(worker, prompt, context, child_depth, worker_id))
            
        return await asyncio.gather(*tasks)

    async def _consume_events(self, worker, prompt, context, depth, worker_id):
        final_answer = None
        
        # Iterate over the sub-orchestrator's event stream
        async for event in worker.run(prompt, context):
            # Bubble up events to the parent stream if necessary
            # e.g., yield event (if this method is a generator) or log them
            
            if event.get("type") == "final_answer":
                final_answer = event.get("content")
                
        # Fallback: check state if event stream missed it
        if not final_answer:
            ans_key = depth_key("FINAL_ANSWER", depth, worker_id)
            final_answer = context.session.state.get(ans_key, "No answer returned.")
            
        # Cleanup REPL resources
        await worker.repl.cleanup()
            
        return LLMResult(text=final_answer)
```

---

## Phase 3: REFACTOR (Cleanup & Hardening)

Once the tests are green, perform the following architectural hardening steps:

### 1. Concurrency and `_EXEC_LOCK` in `LocalREPL`
**Issue:** If `LocalREPL` uses a class-level `_EXEC_LOCK`, multiple sub-agents running concurrently will be bottlenecked, executing code sequentially.
**Refactor:** 
- Move `_EXEC_LOCK` from the class level to the instance level in `rlm_adk/repl/local_repl.py`.
- Because each `LocalREPL` instance now has a unique, depth-and-worker-isolated temporary directory, they do not share a filesystem state and can safely execute code concurrently.

### 2. Resource Cleanup (Temporary Directories)
**Issue:** Recursive REPLs will generate many temporary directories. If a sub-agent crashes, the directory might leak.
**Refactor:**
- Implement an `async def cleanup(self):` method in `LocalREPL` that uses `shutil.rmtree(self.temp_dir, ignore_errors=True)`.
- Wrap the `worker.run(...)` call in `dispatch.py::_consume_events` in a `try...finally` block to guarantee `await worker.repl.cleanup()` is called regardless of exceptions.

### 3. Telemetry and Token Aggregation
**Issue:** ADK tracks token usage per invocation. Sub-agent token usage might be orphaned or overwrite the parent's token counts if they share the exact same telemetry keys in `InvocationContext`.
**Refactor:**
- In `_consume_events`, intercept telemetry events yielded by the sub-agent.
- Append the `worker_id` and `depth` to the telemetry tags before bubbling them up to the parent context.
- Ensure the parent orchestrator aggregates the `total_tokens` from all `LLMResult` objects returned by `llm_query_batched_async` and adds them to its own running total.

### 4. Event Propagation (Bubbling)
**Issue:** The user needs visibility into what the sub-agents are doing (e.g., seeing their code execution in the UI).
**Refactor:**
- Modify `_consume_events` to yield events rather than just returning the final result, transforming it into an async generator.
- Wrap sub-agent events in a namespace: `{"type": "sub_agent_event", "worker_id": worker_id, "depth": depth, "payload": original_event}`.
- Update the parent `RLMOrchestratorAgent` to forward these `sub_agent_event` payloads to the main ADK event stream.