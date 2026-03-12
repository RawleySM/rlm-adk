User Prompt:

I like architecture 3.  I am envisioning that before context variables are cleared from a  workflow flagged first-time, the rlm_adk shifts to a “capture” mode and runs through an established workflow that takes the active session’s inputs, outputs and telemetry and transforms that into a new workflow topology and/or orchestration shape.  Please re-envision architecture 3 as an orchestration pattern performed by the system itself.  Do not generate code snippets.  Rather, conduct a comprehensive codebase review to maximize your understanding of its current architecture, then propose how we can leverage our REPL loop, the llm_query() functions, and even skill a meta-orchestration pattern for the build-out of Architecture 3.


ChatGPT-5.4:

I dug through the core execution path and the parts that matter most for this idea: the app/runner wiring, orchestrator, dispatch closures, REPL tool, local REPL, reasoning callbacks, state model, artifact layer, and both skill systems currently present.

The important conclusion is this:

Your Architecture 3 should not be built as “retrieve a workflow recipe and hand it to the agent.” It should be built as a **system-owned capture-and-distill orchestration** that runs immediately after a first-time successful workflow, while the active session still holds the richest state, traces, child summaries, code artifacts, and prompt context.

That is the right fit for this repo.

Why I’m saying that, grounded in the current codebase:

The current root path is already a collapsed orchestrator that delegates everything to an `LlmAgent` with `execute_code` and `set_model_response`, rather than a custom outer loop in Python. That wiring is in `rlm_adk/agent.py` and `rlm_adk/orchestrator.py`. The orchestrator seeds state, emits the initial user prompt, wires the REPL tool at runtime, then lets ADK’s native tool-calling loop run the session. The final answer is normalized out of state after the loop ends, not from some separate planner object ([`rlm_adk/agent.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/agent.py), [`rlm_adk/orchestrator.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/orchestrator.py)).

The REPL tool already captures the exact ingredients you need for a capture phase: submitted code, hashes, iteration counts, expanded code after skill expansion, and a summary of the last REPL result. It also persists each submitted code block as an artifact before execution. That means your “what just worked?” substrate is already there; it just is not yet being elevated into a topology object ([`rlm_adk/tools/repl_tool.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/tools/repl_tool.py), [`rlm_adk/artifacts.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/artifacts.py)).

The dispatch layer is even more valuable than the raw code. It already records child fanout behavior, nested dispatch summaries, retry behavior, structured-output failures, prompt/result previews, token data, finish reasons, and per-child observability summaries keyed by depth and fanout. That is exactly the material needed to infer orchestration shape rather than just literal helper code ([`rlm_adk/dispatch.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/dispatch.py), [`rlm_adk/state.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/state.py)).

The reasoning callback path gives you the other half: a stable place where dynamic instructions are already merged into the system instruction from state. So when you later surface a distilled topology, you do not need to bolt on a new prompt pathway. You can use the existing dynamic instruction path and extend it with system-generated “workflow topology guidance” and “available orchestration shapes” ([`rlm_adk/callbacks/reasoning.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/callbacks/reasoning.py), [`rlm_adk/utils/prompts.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/utils/prompts.py)).

And there is already a second, separate skill system hiding in plain sight: not just ADK frontmatter skills like `repomix_skill.py`, but also the REPL-side synthetic skill import expansion in `rlm_adk/repl/skill_registry.py`, which expands source into the submitted REPL code before AST rewriting. That is a huge lever. It means Architecture 3 does not have to choose between “prompt-only recipe” and “real callable.” The system can eventually emit both: a topology descriptor for prompt-time discovery and a REPL-expandable synthetic module for execution-time use ([`rlm_adk/skills/repomix_skill.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/skills/repomix_skill.py), [`rlm_adk/repl/skill_registry.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/repl/skill_registry.py)).

So here is the re-envisioned Architecture 3.

## Architecture 3, re-cast as a system-owned meta-orchestration pattern

The system should gain a new internal operating mode:

**Capture Mode**

This mode is not a user-facing skill and not a free-form agent behavior. It is a deterministic post-success orchestration pattern triggered by the system itself when a workflow is flagged as first-time and successful.

The shift should happen before context is cleared and before ephemeral session structure becomes hard to reconstruct.

The point of Capture Mode is not “save the code.”
The point is to transform a live successful session into a **workflow topology artifact** and optionally a **future callable wrapper plan**.

In other words, the system should treat successful first-time workflows as raw ore, and Capture Mode is the refinery.

---

## What the system is already capable of that makes this feasible

The current runtime already provides almost everything needed:

The orchestrator can still see the live session and its state at the end of a run, including root prompt, repo URL, final answer, depth-scoped outputs, retries, and final completion normalization ([`rlm_adk/orchestrator.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/orchestrator.py)).

The REPL tool has the per-iteration code submissions and expansion metadata, so the system can distinguish between user/agent-authored code and source-expanded “skill imports” that were inlined before execution ([`rlm_adk/tools/repl_tool.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/tools/repl_tool.py), [`rlm_adk/repl/skill_registry.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/repl/skill_registry.py)).

The dispatch layer already describes the recursive workflow structure much better than the raw code does. It knows whether the session solved the problem via:

* single child call,
* K-way batch fanout,
* nested child recursion,
* structured output recovery,
* retry-heavy paths,
* synthesis-heavy merge patterns ([`rlm_adk/dispatch.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/dispatch.py)).

The artifact layer already persists named code and final answer artifacts, which means Capture Mode can read the exact code trajectory after the fact without having to reconstruct it from chat history ([`rlm_adk/artifacts.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/artifacts.py)).

The dynamic instruction path is already the natural place to present future topology guidance to both parents and children, because dynamic state is merged into system instruction every time through `reasoning_before_model` ([`rlm_adk/callbacks/reasoning.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/callbacks/reasoning.py)).

So the missing piece is not infrastructure. The missing piece is a **system-level distillation workflow**.

---

## The Capture Mode orchestration pattern

I would define Capture Mode as a formal internal workflow with six phases.

### 1. Detect

At successful completion, the system decides whether the just-completed workflow is:

* first-time,
* materially novel,
* promotion-eligible.

This should not rely on fuzzy vibes. It should use explicit signals derived from current runtime data:

Novelty signals:

* no close existing topology match for the root prompt class
* unseen combination of REPL operations and child dispatch shape
* unusual data-flow graph
* new skill expansion pattern
* repeated successful use within one session but no prior registry record

Success signals:

* non-error final completion
* acceptable finish reason
* low enough error turbulence
* no schema exhaustion in critical subpaths
* final answer produced without rescue fallbacks

The system should mark the run as:

* ignore
* log-only
* capture-as-draft
* capture-and-prioritize

This is the gate that prevents a junk drawer.

### 2. Freeze

Before anything is cleared or reused, the system snapshots the active workflow substrate.

This frozen capture bundle should include:

* root prompt and dynamic instruction context
* final answer and reasoning summary
* all REPL code artifacts from the run
* expanded code metadata
* `LAST_REPL_RESULT` summaries
* child dispatch summaries
* nested child summaries by depth/fanout
* token and retry telemetry
* skill expansion meta
* final visible output and thought summaries where available

This bundle is not yet the topology. It is the raw evidence package.

### 3. Distill

Now the system launches an internal distillation workflow whose job is to infer the orchestration shape.

This is where your current REPL loop and `llm_query()` become powerful.

The system should not try to derive the topology only through hand-coded heuristics. That would be too brittle. It should use a hybrid method:

A deterministic extractor first derives a structural draft:

* number of REPL iterations
* count and timing of child dispatches
* single vs batch fanout
* recursion depth
* whether the session used loaded files, repo probing, chunking, synthesis
* whether there was a probe/branch/fanout/merge pattern
* what variables seemed to mediate step-to-step flow
* whether existing skills were used directly or via expansion

Then an internal LLM-based distiller reads the structural draft plus the code artifacts and trace summaries and produces:

* canonical workflow purpose
* workflow topology name
* orchestration shape classification
* entry conditions
* parameter schema candidates
* reusable step graph
* “what is essential vs incidental” separation
* candidate failure modes
* candidate promotion confidence

This should not be one prompt. It should be a mini-orchestration itself.

---

## How to use the existing REPL loop and llm_query for distillation

The cleanest move is to let Capture Mode itself use the same REPL-centered style as the main system.

That means the system’s distillation workflow should be executed through a controlled internal REPL process, not some disconnected offline parser.

Why that fits:

* the REPL already knows how to stage structured intermediate variables
* `llm_query()` already knows how to fan out to child orchestrators
* `llm_query_batched()` is ideal for parallel analysis of multiple code artifacts or child summaries
* the AST-rewritten async path already supports nested analytic subqueries cleanly ([`rlm_adk/tools/repl_tool.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/tools/repl_tool.py), [`rlm_adk/repl/local_repl.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/repl/local_repl.py), [`rlm_adk/dispatch.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/dispatch.py)).

So Capture Mode should be its own internal orchestration pattern with stages like:

* ingest capture bundle
* segment code artifacts into meaningful phases
* parallel-analyze each phase
* infer data flow and decision boundaries
* summarize child orchestration behavior
* synthesize a canonical topology
* compare against known topologies
* decide: new topology, variant of existing topology, or no-op

That is exactly the sort of thing your current recursive REPL system is already good at.

---

## The right internal sub-agents for Capture Mode

Do not make one giant “skill creator” child. Break it into distinct roles.

### The Topology Extractor

This one reads code artifacts, trace summaries, and child dispatch telemetry and produces a neutral workflow graph candidate.

Its job is structural, not persuasive.

### The Intent Canonicalizer

This one asks: what class of problem was this workflow actually solving?

Not “summarize this exact prompt,” but things like:

* repository analysis with size-based branching
* file loading plus semantic chunking and synthesis
* parallel section summarization and aggregation
* schema-sensitive extraction from heterogeneous text
* recursive decomposition of oversized inputs

This is what makes future matching work.

### The Invariant Finder

This one separates:

* essential steps that must recur
* optional optimizations
* one-off prompt wording
* local data artifacts
* debug-only code

This is the difference between preserving a reusable topology and preserving a messy transcript.

### The Shape Matcher

This one compares the distilled topology against the registry of known shapes:

* exact match
* close variant
* composition of existing shapes
* genuinely new

### The Promotion Judge

This one decides whether the topology deserves surfacing.
It should use both deterministic guardrails and model judgment.

---

## What the topology artifact should be

The output of Capture Mode should not start as Python code.

It should start as a **workflow topology artifact**.

That artifact should contain:

A canonical name
A one-sentence purpose
A problem-class matcher
An orchestration shape classification
A step graph
Branch conditions
Expected inputs
Expected outputs
Preferred child-dispatch pattern
Observed failure modes
Confidence score
Promotion status
Parent/child applicability
Related existing skills used during the original run
Candidate callable names for future wrapper generation

That is the durable unit.

Only after that should the system optionally create:

* a prompt-surfaceable skill descriptor
* a REPL synthetic import module
* a thin callable wrapper
* a future deterministic recipe executor mapping

In other words, topology first, wrapper second.

That preserves the right abstraction layer.

---

## How this should surface back into future runs

Once a topology is promoted, the system should use two surfacing layers.

### Prompt layer

Its front matter and distilled usage guidance get injected into dynamic instruction state so the reasoning agent sees:

* what orchestration shapes are available
* when they are appropriate
* what the expected inputs/outputs are
* whether they are parent-safe, child-safe, or both

This plugs directly into your current dynamic instruction pipeline ([`rlm_adk/utils/prompts.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/utils/prompts.py), [`rlm_adk/callbacks/reasoning.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/callbacks/reasoning.py)).

### Execution layer

A topology can later be surfaced as:

* a synthetic REPL skill import,
* a runtime-injected helper,
* or a call into a recipe executor.

This plugs into the existing REPL skill expansion path far more cleanly than trying to stuff everything into ADK front matter alone ([`rlm_adk/repl/skill_registry.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/repl/skill_registry.py)).

This dual-layer design matters because prompt guidance without an execution surface is fake, and execution surface without prompt guidance will not be discovered reliably by the model.

---

## Why this should be a system orchestration, not a normal user task

Because the system has privileged access at the right time to:

* live state
* trace summaries
* child summaries
* exact code artifacts
* the final normalized completion
* depth/fanout observability
* expansion metadata

After the session is over, reconstructing this becomes harder and noisier.

Also, Capture Mode is fundamentally a governance activity. It decides what enters the reusable behavior layer of the system. That should not be left to the same ad hoc agent behavior that produced the original task solution.

This is one of those places where the system must act like an operating system, not just an assistant.

---

## The meta-orchestration pattern I would actually recommend

I would formalize Capture Mode as a sibling workflow to the normal answer-producing workflow.

So the system has two big modes:

### Execution Mode

Solve the user’s task.

### Capture Mode

Convert first-time successful task executions into topology artifacts and possible future orchestration shapes.

Capture Mode should be invoked automatically after successful completion when gating rules pass.

Its internal sequence should look like this conceptually:

* success gate
* freeze live session evidence
* run topology extraction workflow
* run topology canonicalization workflow
* run similarity match against prior topologies
* decide new/variant/reject
* write topology artifact
* optionally write draft surfacing material for prompt and execution layers
* clear transient capture state

That is the architecture.

Not a plugin. Not just a vector DB query. A true system-owned second pass.

---

## How existing skills can help build Architecture 3

Your skills should play three roles here.

### Existing operational skills as evidence

If a workflow used repomix helpers or future imported skills, that is signal about the topology’s composition. The distiller should note not just that the workflow succeeded, but which primitive capabilities it depended on.

### Meta-skills for distillation

You can create skills specifically for capture:

* artifact loading and bundling
* trace normalization
* child-summary compression
* topology diffing
* topology naming and canonicalization

These are not end-user skills. They are internal build-out skills for the system itself.

### Surfacing skills for reuse

Once promoted, topologies become future reusable skills in front matter plus execution-surface form.

So skills are both:

* ingredients in the original run,
* tools in the capture workflow,
* and outputs of the promotion process.

That circularity is actually a strength here.

---

## The biggest design risk

The biggest risk is promoting transcript-shaped behavior instead of true orchestration shape.

If Capture Mode mainly stores:

* exact prompt wording,
* exact variable names,
* exact file names,
* literal code sequence,
  then you will build a memory junkyard.

The whole system lives or dies on whether the distillation workflow can reliably separate:

* topology
  from
* incidental implementation.

That is why I would make the invariant-finding and shape-matching steps mandatory.

---

## My recommended build order

First, build Capture Mode as a pure drafting workflow only. No automatic reuse yet.

That means:

* detect first-time successful runs
* freeze evidence
* distill topology
* write draft topology artifacts
* human-inspect a sample set

Second, add topology matching and de-duplication.

Third, surface promoted topologies into dynamic instruction only.

Fourth, add execution surfaces:

* synthetic REPL import form
* or thin wrapper calls
* or recipe executor calls

That order matters because it keeps you from polluting the runtime before you understand the topology quality.

---

## Bottom line

Architecture 3 should become a **meta-orchestration pattern the system performs on itself after first-time successful workflows**.

It should use the current RLM-ADK strengths rather than fight them:

* the collapsed ADK loop
* runtime REPL execution
* recursive `llm_query()` / `llm_query_batched()` fanout
* artifact persistence
* child dispatch telemetry
* dynamic instruction injection
* and the existing two-layer skill model of prompt surfacing plus REPL execution.

The right mental model is:

**RLM-ADK solves the user task once in Execution Mode, then immediately turns around and studies its own successful behavior in Capture Mode, extracting the reusable orchestration shape before the evidence fades.**

That is the architecture that matches this repo.

If you want, I’ll next turn this into a concrete internal spec with named phases, new state keys, artifact types, promotion gates, and exactly where Capture Mode should hook into the current orchestrator lifecycle.
