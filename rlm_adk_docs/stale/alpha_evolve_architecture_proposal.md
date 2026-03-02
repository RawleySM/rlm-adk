# AlphaEvolve Architecture Proposal for RLM ADK

Based on the paper "Discovering Multiagent Learning Algorithms with Large Language Models" (Li et al., 2026) and our internal document on neuro-symbolic improvements, this proposal outlines concrete architectural updates to `rlm_adk` to automate the tuning of the agent to specific workflows.

## 1. Automated Symbolic Discovery (The "Mutator" Loop)

**Concept:** Instead of manually writing REPL helper functions (like `probe_repo`), we allow the LLM to write, evaluate, and persist its own tools across sessions, acting as an evolutionary mutator of its own symbolic logic.

**Proposed Updates (`rlm_adk/repl/local_repl.py` & `rlm_adk/orchestrator.py`):**
*   **Tool Persistence:** Add a `save_evolved_tool(name: str, code: str)` method to `LocalREPL`. This method will write the AST-validated Python code to a `.adk/evolved_tools/` directory.
*   **Startup Injection:** Modify `LocalREPL.__init__` to load all functions from `.adk/evolved_tools/` into `self.globals`, granting future sessions access to previously discovered logic.
*   **Evaluation Phase:** Introduce a specific "Workflow Tuning" root prompt for the `RLMOrchestratorAgent`. The agent is instructed to:
    1. Write a candidate function for a specific sub-task (e.g., "Parse custom XML format").
    2. Run it against a validation dataset within the REPL.
    3. Use a sub-LM (`llm_query`) to grade the output.
    4. Mutate the code if it fails, or call `save_evolved_tool` if it passes.

## 2. Adaptive, Volatility-Sensitive Routing (VAD-CFR Inspired)

**Concept:** The paper introduces Volatility-Adaptive Discounting. In `rlm_adk`, we can apply this to how we dispatch sub-LM queries. If a specific chunk of context yields highly unstable answers, we should change the routing strategy for that chunk rather than blindly trusting it.

**Proposed Updates (`rlm_adk/dispatch.py`):**
*   **Confidence Sampling:** Modify `llm_query_batched_async` to optionally sample multiple times (with temperature > 0) for sub-queries flagged as "complex".
*   **Variance Tracking:** Calculate the semantic variance of the responses. If variance is high (high volatility), the dispatch layer can automatically retry the chunk with a stronger model (e.g., routing from a fast depth=1 model to the root model) or request the REPL to pull more context before proceeding.
*   **State Emittance:** Emit this volatility metric as an `Event` so the Orchestrator can adjust its strategy based on `OBS_WORKER_VOLATILITY`.

## 3. Explicit Meta-Memory (Cross-Task Generalization)

**Concept:** Following the ADA architecture referenced in the research, `rlm_adk` should separate episodic memory (current variables) from meta-memory (learned workflow patterns).

**Proposed Updates (`rlm_adk/agent.py` & `rlm_adk/repl/local_repl.py`):**
*   **Meta-Variables Dict:** Add a `self.meta_variables` dictionary to `LocalREPL`. Unlike `self.locals` which clears per session (unless persistent=True), `meta_variables` is backed by the `SqliteSessionService` but scoped globally to the user/workspace, not the specific invocation.
*   **Read/Write API:** Expose `read_meta(key)` and `write_meta(key, val)` to the REPL `globals`.
*   **Usage:** The agent can save generalized rules (e.g., `write_meta("test_command", "pytest -v")`) which are immediately available to zero-shot future tasks in the same workspace.

## 4. Hybrid Solvers via Agent Phase-Shifting

**Concept:** The SHOR-PSRO algorithm from the paper balances exploration and stability. The current `RLMOrchestratorAgent` uses a single `reasoning_agent`.

**Proposed Updates (`rlm_adk/agent.py` & `rlm_adk/orchestrator.py`):**
*   **Dual Sub-Agents:** Modify `create_rlm_orchestrator` to instantiate two reasoning agents:
    *   `exploration_agent` (e.g., temperature=0.7, higher thinking budget, instructed to try multiple hypotheses).
    *   `refinement_agent` (e.g., temperature=0.0, strict instruction to synthesize and finalize).
*   **Phase State:** Add a `CURRENT_PHASE` key to `session.state` (defaulting to "EXPLORE").
*   **Orchestrator Logic:** In `_run_async_impl`, the orchestrator routes to `exploration_agent` for the first $N$ iterations. If the agent emits a specific structural tag (e.g., `<READY_FOR_REFINEMENT>`), the orchestrator updates `CURRENT_PHASE` and routes all subsequent iterations to the `refinement_agent` to lock in the `FINAL_ANSWER`.

## Implementation Roadmap
1.  **Phase 1:** Implement Meta-Memory (`read_meta`/`write_meta`) as it requires minimal core changes and immediately enables cross-task tuning.
2.  **Phase 2:** Implement Dual Sub-Agents (Exploration/Refinement) in the Orchestrator to improve the convergence rate of complex tasks.
3.  **Phase 3:** Introduce the `save_evolved_tool` API and create the "Workflow Tuning" prompt template for automated algorithm discovery.
4.  **Phase 4:** Upgrade `dispatch.py` with Volatility-Sensitive Routing for robust sub-LM chunking.