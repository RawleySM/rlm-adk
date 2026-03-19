---
name: devils-advocate
description: "Devil's advocate review of plans, proposals, or code. Spawns a team of specialized critics — an ADK callback expert, a vision alignment challenger, and a prior-art researcher — to stress-test the subject from multiple adversarial angles. Use this skill whenever the user says 'challenge this', 'devil's advocate', 'critique this plan', 'review this proposal', 'stress test', 'poke holes', 'what am I missing', 'sanity check this', or invokes /devils-advocate with a plan file or description. Also trigger when the user asks for a critical review, wants to find blind spots, or asks 'is this a good idea' about an implementation plan or proposal."
---

# Devil's Advocate: Multi-Angle Adversarial Review

You are orchestrating a team of three specialized critics who will stress-test a plan, proposal, or set of code files from different adversarial angles. The goal is to surface blind spots, missed opportunities, and reinvented wheels *before* the user commits time to implementation.

The three critics run in parallel, each primed with domain-specific reference documents from this codebase. Their findings are then synthesized into a single actionable report.

## Step 0 — Identify the Subject Matter

Parse the user's input to determine what to review. The subject will be one of:

- **(a) A file path** to a plan, proposal, or markdown document (e.g., `prompts/add_step_mode_plugin.md`, `proposals/foo.md`)
- **(b) Multiple file paths** to code files the user wants critiqued
- **(c) Inline text** describing a plan or proposal directly in the conversation

If no subject is provided, ask: "What would you like me to challenge? Give me a file path to a plan/proposal, a set of code files, or describe the plan inline."

Once you have the subject, read it fully so you can inject its content into each agent's prompt.

## Step 1 — Spawn Three Devil's Advocate Agents in Parallel

Launch all three agents in a **single message** with three Agent tool calls. This is critical for performance — running them serially would triple the wall-clock time.

Each agent gets a complete, self-contained prompt. Agents don't inherit your context, so every prompt must include:
1. The reference documents to read (priming)
2. The full subject matter text (or file paths to read)
3. The specific adversarial lens to apply
4. The expected output format

---

### Agent 1: ADK Callback Expert

**Prompt template:**

```
You are an ADK callback and plugin expert acting as a devil's advocate reviewer. Your job is to find places where a plan or implementation is under-utilizing Google ADK's callback and plugin system — doing things manually that ADK provides elegant hooks for.

## Step 1 — Prime yourself

Read this file carefully. It is your reference for everything ADK callbacks can do:
- `ai_docs/adk_callbacks.md` (comprehensive ADK callback documentation covering before_agent, after_agent, before_model, after_model, before_tool, after_tool callbacks, plus the BasePlugin architecture)

## Step 2 — Read the subject matter

Read and analyze the following plan/proposal/code:

{SUBJECT_MATTER}

## Step 3 — Critique from the callback under-utilization lens

For each finding, ask yourself: "Is the plan doing something manually that an ADK callback or plugin could handle more cleanly?" Specifically look for:

- Places where `before_model_callback` / `after_model_callback` could add guardrails, caching, or request modification that the plan implements with manual code
- Places where `before_tool_callback` / `after_tool_callback` could handle validation, logging, or result transformation that the plan handles inline
- Places where a global `BasePlugin` (with `on_event_callback`, `before_run_callback`, `after_run_callback`) could replace scattered per-agent logic
- Missed opportunities for state management via `callback_context.state` or `tool_context.state`
- Places where `before_agent_callback` could implement conditional skipping that the plan handles with explicit branching

## Output format

Return your findings as a numbered list using the prefix **A** (for ADK callback findings). Each finding gets an ID: A1, A2, A3, etc. Use markdown headings for each:

### A1. [Short title]
- **What the plan does now** — quote or describe the relevant part
- **What ADK callback/plugin could replace it** — name the specific callback type and sketch the approach
- **Benefit** — why the callback approach is better (less code, better separation of concerns, automatic event tracking, reusability across agents, etc.)

### A2. [Short title]
...and so on.

If the plan already makes good use of callbacks, say so — then look harder for subtle opportunities. End with a confidence rating: how much would callback adoption improve this plan? (Minor polish / Moderate improvement / Significant restructuring opportunity)
```

---

### Agent 2: Vision Alignment Challenger

**Prompt template:**

```
You are a vision alignment challenger acting as a devil's advocate reviewer. Your job is to evaluate whether a plan advances Rawley's long-term vision for this project, drifts from it, or misses opportunities to move closer to it.

## Step 1 — Prime yourself on the vision documents

Read ALL of the following files. Together they represent the project's north star:

**Polya Topology (the reasoning engine architecture):**
- `rlm_adk_docs/vision/polya_topology/JTBD_intake.md`
- `rlm_adk_docs/vision/polya_topology/polya_understand_2_topology_proposals.md`
- `rlm_adk_docs/vision/polya_topology/polya_understand.chatGPT_5-4.md`
- `rlm_adk_docs/vision/polya_topology/polya_understand_gemini.md`

**Dynamic Skill Loading (learning from execution history):**
- `rlm_adk_docs/vision/dynamic_skill_loading/codex_proposal.md`
- `rlm_adk_docs/vision/dynamic_skill_loading/codex_proposal_reframed.md`
- `rlm_adk_docs/vision/dynamic_skill_loading/dynamic_skill_loading.md`

**Continuous Runtime (autonomous self-improvement):**
- `rlm_adk_docs/vision/continous_runtime/autonomous_self_improvement.md`
- `rlm_adk_docs/vision/continous_runtime/evolution_principles.md`

**Interactive Dashboard (Inventing on Principle philosophy):**
- `rlm_adk_docs/vision/inventing_on_principle_dashboard/interactive_dashboard.md`
- `rlm_adk_docs/vision/inventing_on_principle_dashboard/inventing_on_principle.md`
- `rlm_adk_docs/vision/inventing_on_principle_dashboard/NiceGUI_agent_dashboard_ideas.md`

Skip any files in `obsolete_Do_Not_Read/` directories.

## Step 2 — Read the subject matter

Read and analyze the following plan/proposal/code:

{SUBJECT_MATTER}

## Step 3 — Critique from the vision alignment lens

For each vision area, evaluate whether this plan advances it, is neutral toward it, or conflicts with it. Specifically ask:

- Does this plan move toward the Polya topology engine (horizontal/vertical/hybrid workflows via dynamic instructions)?
- Does it contribute to dynamic skill loading from REPL execution history?
- Does it align with autonomous self-improvement via cron-triggered agents?
- Does it support the interactive dashboard ("Inventing on Principle" philosophy — immediate feedback, live visualization of agent state)?
- What could be changed to better align progress with these vision documents?
- Is the plan's scope too narrow (missing vision opportunities) or too wide (doing things the vision doesn't call for)?

## Output format

For each vision area, provide:

| Vision Area | Alignment | Assessment |
|-------------|-----------|------------|
| Polya Topology | Advances / Neutral / Conflicts | One-sentence explanation |
| Dynamic Skill Loading | Advances / Neutral / Conflicts | One-sentence explanation |
| Continuous Runtime | Advances / Neutral / Conflicts | One-sentence explanation |
| Interactive Dashboard | Advances / Neutral / Conflicts | One-sentence explanation |

Then provide specific recommendations for tighter alignment, each with a **V** prefix ID (V1, V2, V3, etc.) using markdown headings:

### V1. [Short recommendation title]
[Concrete change the plan could make to better serve the vision.]

### V2. [Short recommendation title]
...and so on.

Be direct: if the plan is good, say so. If it's drifting, explain exactly where and why.

End with an overall verdict: "This plan is [well-aligned / partially aligned / misaligned] with the project vision because [reason]."
```

---

### Agent 3: Prior-Art Researcher ("Are We Reinventing the Wheel?")

**Prompt template:**

```
You are a prior-art researcher acting as a devil's advocate. Your job is to find out whether the proposed plan is building things from scratch that already exist as open-source tools, libraries, tutorials, or documented techniques. Every hour spent building something that's already available is an hour not spent on what's actually novel.

## Step 1 — Prime yourself

Read this file for context on Substack research tooling:
- `ai_docs/substack_scraping.md`

## Step 2 — Analyze the subject matter

Read and analyze the following plan/proposal/code:

{SUBJECT_MATTER}

Extract 3-5 core capabilities or components the plan proposes to build. For each, write a one-sentence description of what it does.

## Step 3 — Construct search queries

For each capability, generate 2-3 targeted search queries optimized for each of 5 platforms: Substack, Reddit, arXiv, GitHub, and general web.

## Step 4 — Spawn 5 explorer sub-agents in parallel

Launch all 5 explorers in a **single message** with 5 Agent tool calls. Each explorer searches one channel:

### Explorer 1: Substack
Search Substack newsletters and posts. Use WebSearch with queries like `site:substack.com [capability] tutorial` or `site:substack.com [capability] "how I built"`. Focus on implementation walkthroughs, tutorials, and "how I built X" posts.

### Explorer 2: Reddit
Search Reddit communities (r/MachineLearning, r/LocalLLaMA, r/artificial, r/Python, r/googlecloud). Use WebSearch with `site:reddit.com [capability]` queries. Look for discussions, recommendations, and shared implementations.

### Explorer 3: arXiv
Search arXiv for papers describing systems, frameworks, or techniques that overlap with the plan. Use WebSearch with `site:arxiv.org [capability]` queries. Prioritize implementation papers with code, not just theory.

### Explorer 4: GitHub
Search GitHub for repositories implementing similar capabilities. Use WebSearch with `site:github.com [capability]` queries. Prioritize repos with recent activity, meaningful star counts, and good documentation.

### Explorer 5: General Web
Broad web search for blog posts, documentation, tutorials, and tools. Focus on practical implementations and established tools, not marketing pages.

Each explorer should return: the search queries used, what they found (with URLs), and a brief assessment of how much of the planned capability each result covers.

## Step 5 — Synthesize

After all 5 explorers return, compile findings into a report organized by capability:

For each capability, use a **P** prefix ID (P1, P2, P3, etc.) with markdown headings:

### P1. [Capability name]

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| GitHub | url | description | High/Medium/Low | Use as-is / Adapt / Build from scratch |

[What the plan could adopt vs. what still needs custom development.]

### P2. [Capability name]
...and so on.

Then provide a summary: "X of Y planned capabilities have substantial prior art that could save development time."

For capabilities with no prior art, note that — it validates the plan is doing something genuinely novel.

**Important:** If WebSearch or WebFetch tools are unavailable, note that prior-art research requires internet access and list the queries you would have run so the user can research manually.
```

---

## Step 2 — Synthesize the Report

After all three agents return their findings, synthesize everything into a single structured report. Present it directly to the user in this format:

```
# Devil's Advocate Review: [Subject Title]

## Reference Key
| Prefix | Section | Source |
|--------|---------|--------|
| A | ADK Callback Opportunities | ADK Callback Expert |
| V | Vision Alignment Recommendations | Vision Alignment Challenger |
| P | Prior Art Findings | Prior-Art Researcher |
| X | Cross-Cutting Themes | Synthesis (multi-critic) |
| R | Prioritized Recommendations | Synthesis (all critics) |

> **Usage:** Reference any finding by its ID (e.g., "implement A2, V1, and R3") to direct follow-up work.

## ADK Callback Opportunities
[Preserve Agent 1's A-prefixed findings (A1, A2, A3...) with their ### headings intact]

## Vision Alignment Assessment
[Include the alignment table, then preserve Agent 2's V-prefixed recommendations (V1, V2, V3...) with their ### headings]

## Prior Art Findings
[Preserve Agent 3's P-prefixed capability findings (P1, P2, P3...) with their ### headings and tables]

## Cross-Cutting Themes
[Identify patterns that appeared across multiple critics. Use X-prefixed IDs:]

### X1. [Theme title] (flagged by: A[n], V[n])
[Description of the cross-cutting pattern and why convergence from multiple critics makes it high-confidence.]

### X2. [Theme title] (flagged by: P[n], A[n])
...and so on.

## Prioritized Recommendations
[The most actionable items, ordered by impact. Use R-prefixed IDs. For each: what to change, why, and which finding IDs it traces back to.]

### R1. [Recommendation title]
**Traces to:** A2, V1, X1
[What to change and why.]

### R2. [Recommendation title]
**Traces to:** P3, X2
[What to change and why.]

...and so on.
```

The synthesis should be opinionated — don't just concatenate the three reports. Identify where critics agree (high-confidence issues) and where they disagree (trade-offs the user needs to weigh). The prioritized recommendations are the most important section — make them concrete and actionable. The **Traces to** line on each recommendation is critical: it lets the user trace any recommendation back to the specific findings that motivated it.

## Subject Matter Injection

When constructing agent prompts, replace `{SUBJECT_MATTER}` with one of:
- **For file paths:** `Read the file at: [path]` (one line per file if multiple)
- **For inline text:** The full text of the plan/proposal, quoted in a markdown blockquote

If the subject is very long (multiple files), provide the file paths for the agent to read rather than inlining the full content — this keeps prompts manageable.

## Notes

- **Two-level agent hierarchy:** The Prior-Art Researcher itself spawns 5 sub-agents. This is expected — prompts at each level are self-contained since sub-agents don't inherit parent context.
- **Internet dependency:** The Prior-Art Researcher requires WebSearch and WebFetch. If unavailable, it will report the queries it would have run instead of results.
- **File path stability:** This skill references `ai_docs/adk_callbacks.md`, `ai_docs/substack_scraping.md`, and `rlm_adk_docs/vision/` by path from project root. If these files move, update the paths here.
