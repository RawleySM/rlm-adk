# RLM ADK Meta-Agent Specification: Recursive Neuro-Symbolic Evolution

## 1. Abstract
This specification details the architecture for transforming the `rlm_adk` agent from a static neuro-symbolic execution loop into an adaptive, self-tuning **Meta-Agent**. By synthesizing two multiagent learning algorithms—**VAD-CFR** (Volatility-Adaptive Discounting Counterfactual Regret Minimization) and **SHOR-PSRO** (Smoothed Hybrid Oracle-based Policy Space Response Oracles)—the agent will dynamically generate new symbolic tools (Python functions) and mathematically route between them based on historical reliability.

This architecture fundamentally leverages the **recursive nature** of the `rlm_adk` design: Depth 0 (the Orchestrator) manages the meta-game and routing, while Depth 1+ (sub-LMs) act as generative Oracles to expand the agent's capabilities.

---

## 2. Core Conceptual Model

The meta-agent operates by modeling task execution as a repeated game:
*   **Information Sets ($I$):** The categorization of the current task or prompt (e.g., `TaskType.SYNTAX_ERROR`, `TaskType.CODE_SEARCH`, `TaskType.API_MOCKING`). Information Sets can be hierarchical (from abstract objectives to programmatic primitives).
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
2.  **Volatility ($v$):** Calculate volatility ($v \in [0, 1]$) via an EWMA of instantaneous regret magnitude. Crucially, this must be measured via the $L_\infty$ norm globally across the information set (e.g., `inst_mag = max((abs(r) for r in inst_regrets.values()), default=0.0)`), and then normalized against a maximum expected utility (e.g., `volatility = min(1.0, ewma / max_expected)`).
3.  **Adaptive Discounting ($\alpha, \beta$):** Apply separate discount factors for positive and negative cumulative regrets. These parameters are calculated *once* per update cycle for the entire Information Set based on the global volatility:
    - $\alpha = \max(0.1, 1.5 - 0.5v)$ for $R \ge 0$.
    - $\beta = -0.1 - 0.5v$ for $R < 0$, then $\beta = \min(\alpha, \beta)$.
    - $R_{t+1} = (d \cdot R_t) + r_{boosted}$, where $d = \frac{t^\alpha}{t^\alpha+1}$ (or $t^\beta$).
4.  **Asymmetric Boosting:** Boost positive instantaneous regrets ($r > 0$) by a factor of **1.1x** to accelerate the exploitation of beneficial deviations.
5.  **Negative Regret Cap:** Cap cumulative negative regret at **-20.0** to prevent "regret lock-in" and allow the agent to adapt to changing tool performance.
6.  **Stabilized Meta-Policy:** Use a **Hard Warm-Start** (postpone policy averaging until $t=500$) and **Regret-Magnitude Weighting** to construct a stable "average strategy" for routing.

### 3.2 Architectural Integration
*   **`VADCFRRouter` Component:** A new module (backed by `SqliteSessionService` for cross-session meta-memory) that stores the `task_hash -> {action -> {regret, recent_utilities}}` tables.
*   **Orchestrator Injection:** During the `_run_async_impl` loop, before writing Python code, the Orchestrator queries the `VADCFRRouter` to select the optimal strategy template or tool to inject into the prompt.

---

## 4. SHOR-PSRO: Recursive Tool Generation (The Oracle)

When the VAD-CFR router detects that all available tools for an Information Set have negative regret or high volatility (meaning the agent is "stuck"), it triggers an **Oracle Expansion** using SHOR-PSRO principles.

### 4.1 Hybrid Blending Mechanism
The meta-strategy solver (MSS) for tool population management uses a **Hybrid Update Rule** that blends Optimistic Regret Matching (ORM+) with a Boltzmann distribution (Smoothed Best Pure Strategy):
$$\sigma_{hybrid} = (1 - \lambda) \cdot \sigma_{ORM} + \lambda \cdot \sigma_{softmax}$$
- **ORM+ Component:** Provides the stability of regret minimization.
- **Softmax Component:** Aggressively biases the solver toward high-reward (low-error) tools.
- **$\lambda$ Blending Factor:** Controls the trade-off between stable learning and greedy exploitation.

### 4.2 Training vs. Evaluation Asymmetry
The architecture distinguishes between two meta-solver configurations:
1.  **Training Solver (Population Growth):** Drives the generation of *new* tools. It uses a dynamic annealing schedule for $\lambda$ and diversity bonuses, returning the **average strategy** over internal iterations to ensure stable population expansion.
2.  **Evaluation Solver (Real-time Routing):** Used by the Orchestrator for task execution. It employs a fixed, low $\lambda$ (0.01) and returns the **last-iterate strategy** to ensure reactive and low-noise exploitability estimates.

### 4.3 Hybrid Recursive Dispatch
We utilize `rlm_adk`'s recursive dispatch (`llm_query_batched_async`) to spawn a *population* of distinct agents to solve the sub-task.

*   **Explorer Oracles:** Dispatched with high temperature (e.g., 0.7) and instructions to brainstorm divergent, creative approaches.
*   **Refiner Oracles:** Dispatched with low temperature (e.g., 0.0) to act as strict code-reviewers and synthesizers.

### 4.4 `HybridOraclePool` Expansion
The `WorkerPool` in `rlm_adk/dispatch.py` will be expanded to support Oracle profiles:
```python
class HybridOraclePool(WorkerPool):
    def register_oracles(self, model_name: str):
        # Deterministic, strict validation
        self._create_pool(f"{model_name}-refiner", temperature=0.0)
        # Divergent, creative exploration
        self._create_pool(f"{model_name}-explorer", temperature=0.7)
```

### 4.5 `llm_query_hybrid` Workflow
A new REPL primitive that executes the PSRO generation phase:
1.  **Parallel Generation:** Run $N$ Explorer agents concurrently via batched dispatch to write candidate scripts.
2.  **Smoothing / Synthesis:** Feed the $N$ candidate scripts into a Refiner agent to synthesize the single most robust Python function.
3.  **Persistence:** Save the synthesized function to `.adk/evolved_tools/` and register it as a new "Action" in the VAD-CFR router.

---

## 5. The Neuro-Symbolic Spectrum & Hierarchical Task Composition

The system does not mandate purely deterministic tools. It uses VAD-CFR and SHOR-PSRO to find the optimal point on the neuro-symbolic spectrum for any given task, seamlessly supporting workflows that contain embedded, stochastic LLM calls (`llm_query()`).

### 5.1 Evaluating Stochasticity (The "Prompt Evaluator")
If an evolved tool uses `llm_query()`, its utility is naturally stochastic, making it subject to VAD-CFR tracking:
*   **Robust Prompts:** High expected utility with low variance yields low volatility ($v$). VAD-CFR exploits this tool heavily.
*   **Hallucinations:** Erratic behavior causes the EWMA volatility tracker ($v$) to spike. VAD-CFR dynamically increases discounting ($\alpha, \beta$), violently penalizing the unpredictable tool and effectively quarantining it until SHOR-PSRO generates a more robust alternative.

### 5.2 Hierarchical Reinforcement Learning (HRL)
Tasks (Information Sets) can be hierarchical and varied in scope (e.g., Level 0: `INSPIRE_PUPILS`, Level 1: `GENERATE_VIDEO`, Level 2: `QUERY_PROFILES`). Because actions are Python functions executed in a REPL, high-level objectives are simply Python scripts that orchestrate calls to lower-level sub-tasks.
*   **Composability:** A high-level tool can execute its logic by directly importing and calling other tools.
*   **Credit Assignment:** If a primitive sub-task fails, its expected utility drops, causing the composite task to fail. Negative regret cascades upward, routing around the broken primitive or triggering SHOR-PSRO to fix the root cause.

---

## 6. Bootstrapping & Taxonomy Seeding

To effectively bootstrap the `rlm_adk` meta-agent and prevent excessive compute burn, a hybrid "Warm Start" strategy is employed.

### 6.1 Seeding the Task Taxonomy
The VAD-CFR router requires a mechanism to hash or classify inputs into Information Sets. This is seeded via:
*   **An Input Classifier:** A fast LLM or deterministic schema that runs before the Orchestrator loop, mapping the incoming prompt or system state (e.g., `IndentationError`) to a specific Information Set string (e.g., `TaskType.SYNTAX_RESOLUTION`).

### 6.2 Seeding the Base Game (Bottom-Up)
Instead of forcing the system to "Cold Start" on every task, we seed a `base_tools/` directory with foundational, human-authored Python functions.
*   **Seed Primitives Heavily:** Provide tools for programmatic tasks (`execute_standard_grep`, `parse_pdf`, `llm_diagnose_traceback`).
*   **Seed Composites Lightly:** Provide a few mid-level tasks to give the system a head start on orchestration.
*   **Cold Start Abstracts:** Let SHOR-PSRO discover abstract goals (e.g., `INSPIRE_PUPILS`). When the agent encounters an empty Information Set, it triggers a "Cold Start," spawning Oracles to write a script that glues existing primitives together.

---

## 7. Unified Orchestrator Loop

The `RLMOrchestratorAgent` loop (`_run_async_impl`) is updated to integrate both systems seamlessly:

1.  **Categorize:** Hash/categorize the current prompt to identify the Information Set ($I$).
2.  **Check Meta-Game State:** Query the **Evaluation Meta-Solver** (last-iterate VAD-CFR) for the current tool distribution.
    *   *If Actions are Empty or Max Utility is low (Stuck):* Trigger **SHOR-PSRO Expansion** using the **Training Meta-Solver** (average strategy) to generate and refine new symbolic tools via `llm_query_hybrid`.
3.  **Select & Execute:** Use the stable routing distribution to select a tool/action. Inject its usage into the LLM context or execute it directly.
4.  **Evaluate:** Calculate the iteration absolute utility ($u$).
5.  **Update Meta-Memory:** Feed $u$ back into the VAD-CFR state:
    - Update EWMA absolute volatility ($v$) using $L_\infty$ norm.
    - Boost instantaneous regret ($r_{boosted}$).
    - Apply adaptive discounting ($\alpha, \beta$).
    - Accumulate into the stabilized meta-policy using **Regret-Magnitude Weighting**.

---

## 8. Implementation Roadmap

*   **Phase 1: Meta-Memory Foundation:** Implement the `VADCFRRouter` tables backed by `SqliteSessionService` so data persists across invocations.
*   **Phase 2: Hybrid Oracle Dispatch:** Upgrade `WorkerPool` to `HybridOraclePool` and implement `llm_query_hybrid` to support temperature-varied, recursive synthesis.
*   **Phase 3: Taxonomy & Classifier:** Implement an initial Input Classifier and seed the `base_tools/` primitives.
*   **Phase 4: Tool Evolution API:** Implement `save_evolved_tool` and the dynamic loading of `.adk/evolved_tools/` into the `LocalREPL` `globals`.
*   **Phase 5: Orchestrator Integration:** Wire the VAD-CFR selection and utility updates into the core `_run_async_impl` iteration loop.