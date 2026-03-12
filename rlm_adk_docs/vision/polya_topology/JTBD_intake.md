Here’s a **single reusable interrogation template** for turning a vague **“build me a `<complex_thing>`”** request into a **user-needs extraction** workflow.

It is built to do three things in sequence:

1. **Discover** the real need behind the requested thing
2. **Define** the smallest valid problem worth solving
3. **Validate** whether the need is real, important, and worth building now

---

## Reusable interrogation template

```text
You are not yet designing the solution.

Your job is to transform a vague request of the form “build me a <complex thing>” into a validated user-needs definition.

Do not accept the requested artifact at face value.
Treat the requested thing as a hypothesis about the solution, not the problem itself.

Your process:

PHASE 1 — DISCOVER THE REAL NEED
Goal: uncover the user’s underlying job, pain, context, and desired outcome.

Start by extracting:
1. Who is the primary user?
2. What are they trying to get done?
3. In what situation or trigger do they need this?
4. What do they do today instead?
5. What is frustrating, slow, risky, expensive, or broken about the current way?
6. What consequence happens if this problem is not solved?
7. What outcome do they actually care about?
8. What evidence suggests this is a real need and not just a nice-to-have?

Do not ask “what features do you want?” first.
Instead ask:
- What job are you trying to accomplish?
- What is hard about it today?
- What have you already tried?
- What does success look like in the real world?
- What would improve if this worked?

PHASE 2 — REFRAME THE REQUEST
Goal: convert the solution-shaped request into a problem statement.

Translate “build me a <complex thing>” into:
- user
- job to be done
- current struggle
- desired outcome
- constraints
- risks of failure

Produce a draft reframe in this form:
“The user needs a way to [accomplish job] in [context], because current approaches [failure/pain]. Success means [desired outcome], under constraints of [constraints].”

Then test whether the original requested thing is:
- clearly the right solution
- one possible solution among many
- probably the wrong solution shape
- premature before discovery is complete

PHASE 3 — MAP THE WORKFLOW
Goal: understand the user journey and system boundaries.

Identify:
1. Trigger: what starts the need?
2. Inputs: what information, materials, or context are available?
3. Actions: what steps does the user take today?
4. Breakdowns: where do they get stuck?
5. Outputs: what result do they need?
6. Decision point: what do they do with that result?
7. Frequency: how often does this happen?
8. Variants: what edge cases or different user types exist?

Represent the workflow as:
- trigger
- current steps
- failure points
- desired future steps
- required output

PHASE 4 — EXTRACT CONSTRAINTS
Goal: surface the hidden realities that shape the build.

Identify and separate:
- technical constraints
- business constraints
- operational constraints
- data constraints
- legal/compliance constraints
- trust/safety constraints
- cost constraints
- time constraints
- maintainability constraints
- human skill constraints

Also identify assumptions that are currently unproven.

PHASE 5 — VALIDATE THE NEED
Goal: distinguish a real painful problem from an imagined or weak demand.

Ask:
1. How often does this problem occur?
2. How painful is it when it occurs?
3. Who feels the pain most?
4. What is the cost of doing nothing?
5. What have they already done to solve it?
6. Are they asking for a tool, or for an outcome?
7. Is this urgent, or just interesting?
8. What observable signal would prove this is worth solving now?

Then classify the need as one of:
- urgent and validated
- real but under-evidenced
- plausible but weak
- solution in search of a problem

PHASE 6 — DEFINE THE MINIMUM USEFUL SLICE
Goal: identify the smallest version that solves the core need.

Define:
1. The smallest end-to-end workflow that creates real value
2. What must be included now
3. What should explicitly be excluded
4. What would make phase 1 successful
5. What would make phase 1 fail even if something gets built

Avoid feature creep.
Do not define a full platform if a narrow workflow solves the real pain.

PHASE 7 — PRODUCE THE OUTPUT
Return the results in exactly this structure:

A. Original request
B. Reframed user need
C. Primary user and stakeholders
D. Job to be done
E. Current workflow
F. Pain points / failure modes
G. Desired outcomes
H. Evidence of need
I. Constraints
J. Assumptions needing validation
K. Risks / ambiguities
L. Minimum useful slice
M. Out of scope
N. Validation verdict
O. Recommended next move

Rules:
- Prefer problem clarity over solution enthusiasm.
- Challenge hidden assumptions.
- Separate facts from guesses.
- Treat feature requests as clues, not truth.
- Do not overbuild the first version.
- If the need is weak, say so directly.
```

---

## Best way to use it

Use that template as the **front-end intake prompt** for an agent, analyst, or product-discovery pass.

The flow underneath it is:

* **JTBD** for the real job and desired outcome
* **Double Diamond** for discover first, define second
* **Lean validation** for “is this actually painful and worth solving?”

---

## Fast operator version

If you want the shorter field-ready version, use this:

```text
A user says: “Build me a <complex thing>.”

Your task is to determine:
1. Who is the user?
2. What job are they trying to get done?
3. What do they do today?
4. Where does that fail?
5. What outcome do they actually want?
6. What constraints shape the problem?
7. What evidence says this problem is important?
8. Is the requested thing really the right solution shape?
9. What is the smallest useful version worth building?
10. What should not be built yet?

Return:
- reframed problem statement
- workflow and pain points
- validated need level
- minimum useful slice
- out-of-scope list
- next recommended step
```

---

## Example transformation

Input:

**“Build me a multi-agent research platform.”**

Bad response:

* planner agent
* retriever agent
* synthesis agent
* memory layer
* dashboard
* eval harness

Good interrogation result:

* Primary user: technical researcher evaluating tools and architectures
* Job: answer broad technical questions with source-backed comparison
* Current pain: manual searching is slow, scattered, and hard to reproduce
* Desired outcome: decision-ready briefs with citations
* Evidence: repeated research tasks, duplicated effort, inconsistent conclusions
* Minimum useful slice: question decomposition + grounded retrieval + structured synthesis + citations
* Out of scope: autonomous memory, self-improvement loops, UI platform, multi-user auth

That is the difference between **taking the noun literally** and **extracting the need**.

---

## Recommended next move after this template runs

Once this intake is complete, the next artifact should be a **phase-1 problem statement**, not code.

Format:

```text
Build a system for [user] to accomplish [job] in [context], using [inputs], producing [outputs], under [constraints]. Phase 1 will solve [minimum useful slice]. It will not include [out of scope]. Success will be measured by [acceptance criteria].
```

That becomes the handoff into planning, architecture, and implementation.

If you want, I can turn this into a **strict JSON schema** for agent use, or into a **Markdown worksheet** you can reuse manually with every “build me X” request.
