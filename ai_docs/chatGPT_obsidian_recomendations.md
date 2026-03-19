Obsidian is a **local-first Markdown note-taking and knowledge-base app**. The core idea is simple: your notes are just plain text `.md` files in a folder called a **vault**, and Obsidian layers tools on top of that—internal links, backlinks, graph view, search, properties, plugins, and publishing/sync options. ([Obsidian Help][1])

About the **graph software** part specifically: Obsidian’s **Graph view** visualizes notes as nodes and links between them as edges. There’s a **global graph** for your whole vault and a **local graph** for the currently active note and its nearby connections. The local graph can be filtered and its depth adjusted so you can inspect just the neighborhood around one idea instead of staring at a giant hairball. ([Obsidian Help][2])

What Obsidian is actually good at:

* building a **personal knowledge graph**
* journaling and linking ideas over time
* project notes and research notes
* creating a “personal wiki” with `[[internal links]]`
* keeping your data in files you own, instead of locking it into a web app ([Obsidian][3])

What it is **not** good at by default: a polished enterprise database app, a collaborative Google Docs replacement, or an auto-magical knowledge engine that thinks for you. The graph looks cool, but for a lot of people it becomes visual wallpaper unless they already have a disciplined linking habit.

A few current practical points:
Obsidian itself is free to use, including work use as of February 2025. Paid items are mostly optional services/support tiers, like **Sync** and **Publish**. Obsidian Sync starts at **$4/month**, and Catalyst is a **$25 one-time** support purchase. ([Obsidian][4])

Also worth knowing: Obsidian has been expanding beyond simple notes. Its newer **Bases** core plugin adds database-like views over notes and their properties, which moves it a bit closer to structured project management while still staying file-based. ([Obsidian Help][5])

My blunt take:
Obsidian is excellent if you want a **serious, durable thinking tool** built on your own files. It is overrated if what you really want is effortless collaboration, rigid task management, or a graph that automatically yields insight. The graph is useful, but the real value is the combo of:
**plain files + links + backlinks + search + plugins + ownership**.

For someone like you, it could be strong for:

* research notebooks
* engineering concept linking
* project specs and idea evolution
* AI workflow notes tied together by concepts, repos, and experiments

If you want, I’ll give you a **Rawley-specific breakdown** of whether Obsidian beats Notion, Logseq, and Capacities for your agentic engineering workflow.

[1]: https://help.obsidian.md/obsidian?utm_source=chatgpt.com "About Obsidian"
[2]: https://help.obsidian.md/plugins/graph?utm_source=chatgpt.com "Graph view - Obsidian Help"
[3]: https://obsidian.md/?utm_source=chatgpt.com "Obsidian - Sharpen your thinking"
[4]: https://obsidian.md/blog/free-for-work/?utm_source=chatgpt.com "Obsidian is now free for work"
[5]: https://help.obsidian.md/bases?utm_source=chatgpt.com "Introduction to Bases"


For **your** workflow, I’d rank them like this:

**1. Obsidian**
**2. Notion**
**3. Capacities**
**4. Logseq**

That is not “best for everyone.” That is **best fit for Rawley**: local files, engineering notes, agent workflows, repo-linked thinking, future automation, and not getting trapped in somebody else’s data model.

### The blunt breakdown

**Obsidian** wins for you because it is the strongest mix of:

* local-first Markdown files
* durable ownership of your notes
* graph/backlink thinking
* strong plugin ecosystem
* increasingly real automation hooks

Obsidian is still free for core use, with optional paid Sync and Publish. Its roadmap also now includes an **Obsidian CLI** and a **headless Sync client**, which matters a lot for someone like you who thinks in terms of scripts, agents, and external tooling. Canvas is also built in for visual ideation. ([Obsidian][1])

That last part is the real separator: Obsidian is no longer just a note app with a pretty graph. It is drifting toward being a **local knowledge operating system** that can actually participate in an agentic toolchain. That maps well to your Databricks / GitHub / local-dev / AI-agent setup. ([Obsidian][2])

**Notion** is better than Obsidian for structured planning, polished databases, dashboards, team sharing, and project tracking. Its core strength is that databases are first-class, and projects/tasks are a native happy path. It also has backlinks and AI features built into the workspace. ([Notion][3])

But here is the problem for you: Notion is great when you want a **workspace product**, not when you want a **hackable personal knowledge substrate**. It is more opinionated, more SaaS-centered, and less natural as a file-native engineering notebook. For heavy agentic experimentation, repo-adjacent notes, and long-lived personal R&D, I would not make it your center of gravity. I’d use it only if you want a clean ops dashboard layer on top of your messy real thinking. ([Notion][3])

**Capacities** is the most interesting wild card. Its model is object-based rather than file/folder-first, and that makes it feel more modern and “knowledge graph native” than many tools. It also now has offline support, and Pro includes AI, smart queries, calendar integration, and task features. But Capacities explicitly says collaboration/team plans are not a near-term focus, and even a whole-space graph is not clearly planned. It is also desktop-first and intentionally avoids some advanced automation/formula complexity. ([Capacities][4])

That means Capacities is attractive if you want a **beautiful thinking environment** and don’t mind betting on a smaller product vision. But for your style—where notes may eventually need to interoperate with scripts, repos, prompts, specs, and generated artifacts—I still think it is too closed and too early to be your main platform. ([Capacities][5])

**Logseq** is the purist’s choice: privacy-first, open-source, graph-oriented, and strongly aligned with local knowledge work. It is also comfortable with existing Markdown files. ([logseq][6])

But I’d still put it behind Obsidian for you because the ecosystem and product momentum feel less practical for your specific endgame. Logseq is philosophically attractive, but Obsidian currently looks stronger as a bridge between note-taking and automation-heavy workflows. Logseq does have Sync beta and whiteboards beta on its downloads page, but that still reads more like an evolving toolset than a finished platform for the kind of agentic integration you’re likely to push hard. ([logseq][6])

### What each one is really for

**Obsidian**
Best for: personal R&D vault, engineering notebooks, concept linking, local AI workflow docs, repo-adjacent specs, durable long-term idea system. ([Obsidian][1])

**Notion**
Best for: project management, family planning dashboards, shared docs, lightweight CRM/task systems, polished presentations of work. ([Notion][7])

**Capacities**
Best for: elegant personal knowledge work, object-centric notes, daily idea development, linked media and reading workflows. ([Capacities][4])

**Logseq**
Best for: journal-heavy knowledge work, outlines, local-first graph thinkers, open-source purists. ([Logseq Documentation][8])

### My actual recommendation for you

Do **not** pick one app to do everything.

Use this split:

**Obsidian = your thinking engine**
Put these there:

* engineering concepts
* agent architecture notes
* repo maps
* research notes
* invention threads
* theology / philosophy / science idea webs
* prompts, specs, and evolving design docs

**Notion = your execution dashboard**
Put these there:

* household systems
* project tracking
* business-facing status boards
* family planning
* clean shareable docs
* higher-level task databases

That combo is stronger than trying to force one tool into both roles. The mistake people make is wanting their deep thinking tool and their clean management tool to be the same thing. Usually that degrades both.

### Why Obsidian beats the others for your agentic engineering workflow

Because your future likely involves:

* Markdown notes tied to repos
* scripts touching your notes
* AI agents reading and generating files
* graph relationships between concepts, experiments, and architectures
* local ownership
* low fear of migration
* possible CLI/tooling integration later

Obsidian lines up with that trajectory better than the others right now. The newly surfaced CLI/headless direction just reinforces that. ([Obsidian][2])

### The one warning

If you adopt Obsidian, do **not** become a graph junkie who spends hours grooming links and no hours shipping. The graph is a support tool, not the product. Your real payoff would come from a vault structure that mirrors your real work:

* projects
* concepts
* experiments
* prompts
* decisions
* people
* repos
* artifacts

Then let links emerge from use.

### Bottom line

If you want the cleanest recommendation:

**Pick Obsidian as your main personal knowledge system.**
**Use Notion only as a secondary operational layer.**
Ignore the temptation to over-romanticize Logseq or over-aestheticize Capacities.

That’s the real answer.

I can next give you a **Rawley-specific Obsidian vault architecture** for engineering + AI agents + family systems + invention tracking.

[1]: https://obsidian.md/pricing "Pricing - Obsidian"
[2]: https://obsidian.md/roadmap/ "Obsidian Roadmap - Obsidian"
[3]: https://www.notion.com/help/intro-to-databases "Intro to databases – Notion Help Center"
[4]: https://capacities.io/?utm_source=chatgpt.com "Capacities - A studio for your mind | Capacities"
[5]: https://capacities.io/roadmap/whats-not-next "What's not next?"
[6]: https://logseq.com/?utm_source=chatgpt.com "Logseq: A privacy-first, open-source knowledge base"
[7]: https://www.notion.com/help/guides/getting-started-with-projects-and-tasks "Getting started with projects and tasks"
[8]: https://docs.logseq.com/?utm_source=chatgpt.com "contents - Logseq"


Here’s the vault I’d build for you.

## Core principle

Your Obsidian vault should **not** be a scrapbook.
It should be a **working knowledge system** that does four jobs:

1. capture raw ideas fast
2. evolve ideas into structured projects
3. connect concepts across engineering, AI, family, faith, and invention
4. make active work easy to find and resume

For you, the right design is **project-centered with concept cross-links**, not journal-centered and not folder-only.

---

# Recommended top-level vault structure

```text
00_Inbox/
01_Dashboard/
02_Projects/
03_Areas/
04_Concepts/
05_Resources/
06_Artifacts/
07_People/
08_Daily/
09_Templates/
10_Archive/
```

That structure is deliberate.

## What each folder does

### `00_Inbox`

Fast capture.
No friction. Dump first, organize later.

Use it for:

* raw ideas
* copied prompts
* voice-note transcriptions
* sudden invention thoughts
* half-baked architecture insights
* things captured from phone

Rule: nothing should live here long-term.

---

### `01_Dashboard`

Your control panel.

This should contain a small set of manually curated notes that help you restart fast:

* `Home.md`
* `Hot List.md`
* `Weekly Review.md`
* `Open Loops.md`
* `Current Builds.md`
* `Next Actions.md`

This is where your vault becomes operational instead of decorative.

---

### `02_Projects`

This is the heart.

Each active project gets its own folder or note cluster.

Examples for you:

* `AI Vendor Match`
* `RLM-ADK`
* `E-DAF Architecture`
* `FlogBoard`
* `Toroidal Braiding Project`
* `Cordless Drill Adapter`
* `Composite Robot Swarm`
* `Cryogenic Story / Eternal Wake`
* `Family Systems with AI`
* `Drink Beverage Formulator`

Each project should have one **project home note**.

Example:

```text
02_Projects/
  AI Vendor Match/
    AI Vendor Match - Home.md
    Decisions.md
    Open Questions.md
    Data Model.md
    Experiments.md
    Prompt Patterns.md
    Related Repos.md
```

Do not over-folderize. Most structure should live in notes, links, and properties.

---

### `03_Areas`

These are long-lived responsibilities, not projects.

For you:

* `Career and SpendMend`
* `Family Leadership`
* `Faith`
* `Health`
* `Home and Property`
* `Learning and Skill Building`
* `Entrepreneurial Ventures`

Difference:

* **Project** = has an outcome
* **Area** = never really ends

This distinction matters. Otherwise everything turns into a fake “project.”

---

### `04_Concepts`

This is where Obsidian crushes Notion.

This folder stores reusable ideas that cut across projects.

Examples:

* `Agentic Policy Bundle`
* `Progressive Disclosure`
* `Context Engineering`
* `EFSM`
* `Challenger Champion Loop`
* `Dirichlet Energy`
* `Toroidal Geometry`
* `Hopf Fibration`
* `Schema Matching`
* `Local-first Knowledge Systems`
* `Reward Harness`
* `Failure Mode Analysis`
* `Personal Knowledge Graph`
* `Engineering Moat`
* `Soft Actuator`
* `Topological Textile Reinforcement`

These notes become your intellectual lattice.

A concept note should link to:

* projects using the concept
* resources explaining it
* decisions influenced by it
* experiments testing it

This is where the graph becomes useful instead of stupid.

---

### `05_Resources`

Reference material.

Examples:

* book notes
* paper notes
* article summaries
* tool comparisons
* architecture references
* copied documentation insights
* benchmark summaries

Subfolders might be:

```text
05_Resources/
  Papers/
  Books/
  Tools/
  Docs/
  Benchmarks/
```

Do not treat resources as the center of the vault.
They support projects and concepts.

---

### `06_Artifacts`

Concrete outputs.

Examples:

* spec drafts
* pseudocode packages
* architecture summaries
* prompt libraries
* generated diagrams
* meeting summaries
* deliverables
* polished markdown for repos
* decision logs

This gives you a place for “things produced,” separate from “things thought about.”

That distinction helps a lot.

---

### `07_People`

For relationship-aware work.

Examples:

* Sarah
* Cambryn
* Creighton
* collaborators
* managers
* technical contacts
* researchers you may contact

Each person note can hold:

* relationship context
* open loops
* ideas for support
* relevant projects
* communication notes

Not creepy. Just useful.

---

### `08_Daily`

Daily notes, if you use them.

For you, I would use daily notes lightly:

* quick capture
* what you worked on
* blockers
* sparks of insight
* what to resume tomorrow

Do **not** bury important knowledge only in daily notes.
Daily notes should feed Projects, Concepts, and Artifacts.

---

### `09_Templates`

Critical.
This is what prevents chaos.

Templates I’d build for you:

* Project Home
* Concept Note
* Experiment Log
* Decision Record
* Daily Note
* Meeting Note
* Prompt Pattern
* Research Summary
* Person Note
* Weekly Review

---

### `10_Archive`

Dead or dormant stuff.

Archive aggressively.
A vault feels powerful when active notes are mostly alive.

---

# The metadata model that will make this work

Use **minimal but meaningful properties** at the top of notes.

Do not go insane with fields.

## Recommended core properties

For many notes:

```yaml
type:
status:
area:
project:
tags:
created:
updated:
```

For project notes:

```yaml
type: project
status: active
area: Career and SpendMend
horizon: active
review_frequency: weekly
```

For concept notes:

```yaml
type: concept
status: evergreen
related_projects:
  - AI Vendor Match
  - RLM-ADK
```

For experiment notes:

```yaml
type: experiment
status: running
project: RLM-ADK
hypothesis:
result:
next_step:
```

For decisions:

```yaml
type: decision
project: E-DAF Architecture
status: accepted
date:
supersedes:
```

That is enough.
Don’t try to turn Obsidian into a brittle enterprise schema monster.

---

# The note types you should standardize

## 1. Project Home note

Every real project gets one.

Structure:

```markdown
# Project Name

## Purpose
Why this project exists.

## Current Status
Where it stands right now.

## Desired Outcome
What done looks like.

## Active Workstreams
- 
- 
- 

## Open Questions
- 
- 
- 

## Key Decisions
- [[Decision - ...]]
- [[Decision - ...]]

## Related Concepts
- [[EFSM]]
- [[Progressive Disclosure]]

## Artifacts
- [[Spec v3]]
- [[Pseudocode Draft]]

## Next Actions
- 
- 
- 
```

This is the most important template in the vault.

---

## 2. Concept note

This is where you build your long-term brain.

Structure:

```markdown
# Concept Name

## Definition
Plain-language explanation.

## Why It Matters
Why you care.

## Used In
- [[RLM-ADK]]
- [[Toroidal Braiding Project]]

## Related Concepts
- [[Context Engineering]]
- [[Reward Harness]]

## Open Questions
- 
- 

## Examples
- 
- 

## Resources
- [[Paper - ...]]
- [[Article - ...]]
```

---

## 3. Experiment log

You run a lot of trials. Track them explicitly.

Structure:

```markdown
# Experiment - Name

## Project
[[RLM-ADK]]

## Hypothesis
What you think may happen.

## Setup
Tools, codebase, assumptions, constraints.

## Procedure
What was done.

## Result
What happened.

## Interpretation
What it means.

## Next Move
What to do now.
```

This alone will save you from rediscovering the same lessons repeatedly.

---

## 4. Decision record

Massively useful for architecture work.

Structure:

```markdown
# Decision - Embedded IPython over exec

## Context
Why this decision came up.

## Decision
What was chosen.

## Alternatives Considered
- Keep raw exec
- Use IPython + debugpy
- Use external sandbox service

## Why
Reasoning.

## Consequences
Tradeoffs, limitations, follow-up work.

## Related
- [[RLM-ADK]]
- [[REPL Architecture]]
```

---

## 5. Prompt pattern note

Because you repeatedly create prompts for coding agents, research agents, architecture proposals.

Structure:

```markdown
# Prompt Pattern - Repo Architecture Review

## Use Case
When to use this prompt.

## Prompt
...

## Inputs Required
- repo path
- design objective
- constraints

## Expected Output
- architecture options
- tradeoff table
- implementation plan

## Notes
What worked / failed.
```

This will become gold over time.

---

# Your actual dashboards

You need a few notes pinned in favorites.

## `Home.md`

This should link to:

* Hot List
* active projects
* current areas
* open loops
* weekly review
* inbox triage
* recent artifacts

## `Hot List.md`

This is your real active lane.

Keep it brutally small:

* 5–8 items max
* sorted by current force, not guilt

Sections:

* Career / AI
* Family
* Entrepreneurial
* Creative / story
* Immediate admin

## `Open Loops.md`

Use this for things that are mentally sticky:

* emails to send
* people to reply to
* blockers
* things waiting on other people
* unresolved design forks

## `Current Builds.md`

This should list:

* repo
* branch or environment
* what’s in motion
* next verification step

This is especially good for your agentic dev workflow.

---

# Tags: use fewer than you think

Do not tag everything like a maniac.

Use tags for only a few high-value dimensions, such as:

```text
#active
#stalled
#idea
#decision
#experiment
#research
#family
#faith
#engineering
#ai-agents
```

Let links and folders do more of the work.

---

# How I would map your real life into the vault

## Projects

Inside `02_Projects/` I’d start with:

```text
AI Vendor Match
RLM-ADK
E-DAF Architecture
FlogBoard
Toroidal Braiding Project
Cordless Drill Adapter
Drink Beverage Formulator
Family Systems with AI
The Eternal Wake
SpendMend Career Strategy
```

## Areas

Inside `03_Areas/`:

```text
Career and Craft
Family Leadership
Faith and Meaning
Health and Energy
Learning and Skill Building
Property and Environment
Entrepreneurial Direction
```

## Concepts

Inside `04_Concepts/`:

```text
Agentic Policy Bundle
Workflow Execution Agent
System Evolution Agent
Progressive Disclosure
Reward Harness
Verification Loop
Context Engineering
Failure Mode Analysis
Schema Matching
Vendor Canonicalization
Hopf Fibration
Toroidal Braiding
Soft Robotics
Knowledge Graph
Love Languages
```

That gives you cross-domain power without forcing everything into one bucket.

---

# Plugin stack I’d recommend

Keep this lean at first.

## Definitely install

* **Templates**
* **Properties** (core behavior, already built-in)
* **Backlinks**
* **Graph View**
* **Canvas**
* **Daily Notes**
* **Dataview** if you are willing to learn a little query syntax
* **Templater** if you want stronger automation than stock templates
* **QuickAdd** for fast capture flows

## Maybe later

* **Tasks**
* **Calendar**
* **Excalidraw**
* **Omnisearch**
* **Kanban**

Do not start with 30 plugins. That’s how people turn Obsidian into a fragile hobby.

---

# The automations that would actually help you

Given how you work, these are the first useful automations:

## 1. Quick capture to inbox

A fast note template that captures:

* title
* source
* rough type
* one-line idea

## 2. Project creation command

One action that creates:

* project home note
* decision log note
* experiment log note
* artifact note
* project folder

## 3. Decision record inserter

Fast template for architecture/design decisions.

## 4. Weekly review note

Auto-generate a note that pulls:

* active projects
* stalled items
* recent artifacts
* experiments without conclusions
* open loops

## 5. Prompt library capture

A shortcut to turn a good prompt into a reusable “Prompt Pattern” note.

That is the stuff that matters. Not cosmetic nonsense.

---

# How to keep the graph useful

The graph only becomes useful if your links reflect real relationships.

Use these link patterns consistently:

## Project to concept

“This project uses these ideas.”

## Concept to concept

“These ideas are adjacent or in tension.”

## Experiment to project

“This test belongs to this effort.”

## Decision to project

“This architecture choice shaped this build.”

## Artifact to project

“This output came from this effort.”

## Person to project

“This person matters to this initiative.”

Then your graph starts showing actual structure.

Without that, it’s just confetti.

---

# Naming conventions I’d use for you

Keep names boring and obvious.

Good:

* `Decision - Switch to provider-contract fake`
* `Experiment - IPython embedded REPL`
* `Prompt Pattern - Repo architecture review`
* `Concept - Progressive Disclosure`
* `Project - AI Vendor Match`

Bad:

* `Thoughts on maybe making the thing better`
* `cool architecture idea`
* `new note 47`

You are building a system, not a junk drawer.

---

# My recommended daily workflow for you

## Morning

Open `Home.md`
Review:

* Hot List
* Open Loops
* one key active project

## During the day

Capture everything fast into `00_Inbox`

When an idea matters:

* convert to project note
* concept note
* experiment note
* decision note
* artifact note

## End of day

Open daily note and write:

* what moved
* what blocked
* what to resume next

Then link those notes to the actual project.

---

# The biggest trap to avoid

Do **not** make the vault prettier than your work is real.

Your vault should primarily help you:

* restart work fast
* preserve good thinking
* reduce repeated confusion
* connect scattered insights
* create durable project memory

If it does not improve those five things, it is becoming procrastination furniture.

---

# My stripped-down starter version

If you want to start lean, use only this:

```text
00_Inbox/
01_Dashboard/
02_Projects/
04_Concepts/
06_Artifacts/
08_Daily/
09_Templates/
10_Archive/
```

That is enough to begin.

---

# Final recommendation

For you, Obsidian should become:

* **the place where ideas mature**
* **the memory layer around your repos and agent systems**
* **the cross-linking system between engineering, AI, invention, family, and philosophy**
* **the launchpad for structured output**

Not a diary.
Not a scrapbook.
Not a pretty graph toy.

A **working brain extension**.

I can next give you a **ready-to-paste starter pack** with:

1. folder tree
2. template files
3. a Home dashboard note
4. a Hot List note
5. a Dataview setup for active projects
