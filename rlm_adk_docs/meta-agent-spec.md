# RLM ADK Meta-Agent Specification: Recursive Neuro-Symbolic Evolution

## 1. Abstract
This specification details the architecture for transforming the `rlm_adk` agent from a static neuro-symbolic execution loop into an adaptive, self-tuning **Meta-Agent**. By synthesizing two multiagent learning algorithms—**VAD-CFR** (Volatility-Adaptive Discounting Counterfactual Regret Minimization) and **SHOR-PSRO** (Smoothed Hybrid Oracle-based Policy Space Response Oracles)—the agent will dynamically generate new symbolic tools (Python functions) and mathematically route between them based on historical reliability.

This architecture fundamentally leverages the **recursive nature** of the `rlm_adk` design: Depth 0 (the Orchestrator) manages the meta-game and routing, while Depth 1+ (sub-LMs) act as generative Oracles to expand the agent's capabilities.

---

## 2. Core Conceptual Model

The meta-agent operates by modeling task execution as a repeated game:
*   **Information Sets ($I$):** The categorization of the current task or prompt (e.g., `TaskType.SYNTAX_ERROR`, `TaskType.CODE_SEARCH`, `TaskType.API_MOCKING`).
*   **Actions ($A$):** The available strategies or "policies." In `rlm_adk`, an action is the selection of a specific model configuration or an evolved REPL tool (e.g., `execute_standard_grep()`, `execute_evolved_ast_parser()`).
*   **Utility ($u$):** The measurable outcome of an action (e.g., +1 for resolving the task without syntax errors, -1 for a context window overflow or REPL exception).

### The Synergy
*   **SHOR-PSRO** drives **Vertical Expansion**: When current tools fail, it spawns recursive, hybrid sub-agents to invent new tools.
*   **VAD-CFR** drives **Horizontal Routing**: It tracks the volatility and regret of all tools, mathematically ensuring the Orchestrator selects the most stable and effective tool for a given Information Set.

---

## 3. VAD-CFR: Volatility-Adaptive Routing

VAD-CFR handles the selection of *existing* tools and sub-agent configurations. It modifies standard CFR by discounting historical regrets based on their recent volatility, preventing the agent from over-indexing on unstable, LLM-generated tools.

### 3.1 Mathematical Mechanism
1.  **Regret Tracking:** Maintain a Cumulative Regret ($R$) for each action within an Information Set.
2.  **Volatility ($v$):** Calculate the variance of recent utilities for each action using a sliding window.
3.  **VAD Discounting ($\gamma$):** Apply a discount factor inversely proportional to volatility. High volatility = high discount (forget the past faster).
    $$R_{t+1} = (\gamma \cdot R_t) + 	ext{counterfactual\_regret}$$
4.  **Strategy Selection:** Use Regret Matching to convert cumulative regrets into a probability distribution for selecting the next tool.

### 3.2 Architectural Integration
*   **`VADCFRRouter` Component:** A new module (backed by `SqliteSessionService` for cross-session meta-memory) that stores the `task_hash -> {action -> {regret, recent_utilities}}` tables.
*   **Orchestrator Injection:** During the `_run_async_impl` loop, before writing Python code, the Orchestrator queries the `VADCFRRouter` to select the optimal strategy template or tool to inject into the prompt.

---

## 4. SHOR-PSRO: Recursive Tool Generation (The Oracle)

When the VAD-CFR router detects that all available tools for an Information Set have negative regret or high volatility (meaning the agent is "stuck"), it triggers an **Oracle Expansion** using SHOR-PSRO principles.

### 4.1 Hybrid Recursive Dispatch
We utilize `rlm_adk`'s recursive dispatch (`llm_query_batched_async`) to spawn a *population* of distinct agents to solve the sub-task.

*   **Explorer Oracles:** Dispatched with high temperature (e.g., 0.7) and instructions to brainstorm divergent, creative approaches.
*   **Refiner Oracles:** Dispatched with low temperature (e.g., 0.0) to act as strict code-reviewers and synthesizers.

### 4.2 `HybridOraclePool` Expansion
The `WorkerPool` in `rlm_adk/dispatch.py` will be expanded to support Oracle profiles:
```python
class HybridOraclePool(WorkerPool):
    def register_oracles(self, model_name: str):
        # Deterministic, strict validation
        self._create_pool(f"{model_name}-refiner", temperature=0.0)
        # Divergent, creative exploration
        self._create_pool(f"{model_name}-explorer", temperature=0.7)
```

### 4.3 `llm_query_hybrid` Workflow
A new REPL primitive that executes the PSRO generation phase:
1.  **Parallel Generation:** Run $N$ Explorer agents concurrently via batched dispatch to write candidate scripts.
2.  **Smoothing / Synthesis:** Feed the $N$ candidate scripts into a Refiner agent to synthesize the single most robust Python function.
3.  **Persistence:** Save the synthesized function to `.adk/evolved_tools/` and register it as a new "Action" in the VAD-CFR router.

---

## 5. Unified Orchestrator Loop

The `RLMOrchestratorAgent` loop (`_run_async_impl`) is updated to integrate both systems seamlessly:

1.  **Categorize:** Hash/categorize the current prompt to identify the Information Set ($I$).
2.  **Check Meta-Game State:** Query VAD-CFR for maximum expected utility.
    *   *If Max Utility is low (Stuck):* Trigger **SHOR-PSRO Expansion** via `llm_query_hybrid` to generate a new tool. Register the new tool.
3.  **Select & Execute:** Use VAD-CFR Regret Matching to select a tool/action. Inject its usage into the LLM context or execute it directly.
4.  **Evaluate:** Calculate the utility ($u$) of the iteration (e.g., `REPLResult.stderr == ""`).
5.  **Update:** Feed the utility back into VAD-CFR. Update volatility ($v$), discount past regrets ($\gamma$), and update cumulative regret tables.

---

## 6. Implementation Roadmap

*   **Phase 1: Meta-Memory Foundation:** Implement the `VADCFRRouter` tables backed by `SqliteSessionService` so data persists across invocations.
*   **Phase 2: Hybrid Oracle Dispatch:** Upgrade `WorkerPool` to `HybridOraclePool` and implement `llm_query_hybrid` to support temperature-varied, recursive synthesis.
*   **Phase 3: Tool Evolution API:** Implement `save_evolved_tool` and the dynamic loading of `.adk/evolved_tools/` into the `LocalREPL` `globals`.
*   **Phase 4: Orchestrator Integration:** Wire the VAD-CFR selection and utility updates into the core `_run_async_impl` iteration loop.