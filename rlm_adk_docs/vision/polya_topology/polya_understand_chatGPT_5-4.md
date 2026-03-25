Here’s a rigorous methodology for the **“Understand” phase** in George Pólya’s *How to Solve It*.

Pólya’s first phase is often summarized as **“Understand the problem.”** That sounds simple, but it is the most commonly skipped step, and that skip is why people solve the wrong problem, choose the wrong tool, or waste time on elegant work that does not satisfy the actual objective.

## What the “Understand” phase is really for

The goal is not merely to read the problem statement.

The goal is to build a **precise mental model** of:

* what is being asked
* what is already known
* what is unknown
* what constraints govern the solution
* what a valid answer must look like
* what hidden assumptions may be distorting the problem

A problem is “understood” only when you can restate it clearly, define the target, identify the moving parts, and detect what is missing or ambiguous.

---

# Detailed methodology for the Understand phase

## 1. Restate the problem in your own words

Take the original problem statement and rewrite it plainly.

Do not paraphrase lazily. Strip it down until the core demand is obvious.

Ask:

* What is the problem asking me to produce?
* Is it asking for a value, proof, explanation, design, diagnosis, comparison, or decision?
* What would count as a finished answer?

### Output of this step

A one- or two-sentence reformulation.

### Example

Original:
“Find the maximum stress in a beam under the given loading.”

Restated:
“I need to determine the greatest internal bending stress anywhere in the beam, based on the geometry, supports, and applied loads.”

That reformulation already exposes the likely pathway: geometry, loading, moments, section properties, stress relation.

---

## 2. Identify the objective with full precision

Many people think they understand a problem because they know the topic. That is not enough. You need to define the exact target.

Ask:

* What specifically is unknown?
* Is there one unknown or several?
* Is the problem asking for a numeric answer, symbolic form, ranked options, or a process?
* Is there an optimization target?
* Is there an implied criterion like “best,” “minimum,” “stable,” “safe,” or “sufficient”?

### Output of this step

A clearly named target variable, decision, or deliverable.

### Example

Not precise:
“I need the answer.”

Precise:
“I need the minimum material thickness that keeps peak deflection under the allowable limit.”

Now the problem is no longer vague. It is an optimization under a constraint.

---

## 3. Inventory the given information

Extract everything explicitly provided.

Do this mechanically at first. Don’t interpret too early.

Catalog:

* known quantities
* definitions
* conditions
* diagrams
* relationships
* units
* starting state
* boundary conditions
* examples
* exceptions
* assumptions stated by the source

For technical problems, separate these into categories:

* **data**
* **rules**
* **constraints**
* **context**

### Output of this step

A structured list of givens.

### Example

For a math problem:

* Triangle is right-angled
* Hypotenuse = 10
* One leg = 6
* Need area

For a software problem:

* Input format is JSON
* Max file size is 50 MB
* Must run locally
* No network access
* Output must be deterministic

This prevents the common mistake of “solving from memory” instead of solving from the actual problem.

---

## 4. Identify the unknowns and their relationships to the givens

Now connect the target to the known information.

Ask:

* Which givens are directly relevant to the unknown?
* Which are probably distractions?
* What intermediate quantities may need to be found first?
* Are there latent variables not explicitly named but obviously necessary?

### Output of this step

A map from knowns to unknowns.

### Example

If you need beam stress, you may need:

* load → reaction forces
* reactions → shear/moment diagram
* moment maximum → stress via section modulus

The key insight here is that many problems are not “one jump” problems. They are **chains**. Understanding means discovering the chain before calculation begins.

---

## 5. Clarify all terms and remove ambiguity

Pólya emphasizes making sure you actually know what the words mean.

Ask:

* Do I know the meaning of every technical term?
* Is any word overloaded or vague?
* Does “optimize” mean fastest, cheapest, lightest, simplest, or most accurate?
* Does “solution” mean proof, implementation, concept, or approximation?
* Are units, domains, or conventions implied but unstated?

### Output of this step

A list of clarified definitions and interpretations.

### Example

In software:
“Robust” could mean:

* handles malformed input
* fault-tolerant to system failures
* secure against adversarial input
* stable under scale

Until that is pinned down, the problem is not understood.

---

## 6. Draw, diagram, tabulate, or externalize the structure

Pólya repeatedly pushes the solver to make the problem visible.

Convert abstract wording into structure:

* draw the geometry
* sketch the forces
* make a table of inputs/outputs
* define entities and states
* map cause/effect
* write symbolic relations
* create a timeline
* build a dependency graph

This matters because working memory lies. External structure exposes missing pieces and contradictions.

### Output of this step

A visual or symbolic representation of the problem.

### Examples

* Geometry sketch for a mechanics problem
* State machine for a software workflow
* Input-output table for a data transformation task
* Sequence diagram for an API issue
* Constraint matrix for optimization

If you cannot diagram the problem, you probably do not understand it yet.

---

## 7. Separate facts from assumptions

This is one of the most important parts of real problem-solving and one of the least discussed.

Ask:

* What is explicitly stated?
* What am I merely assuming because it is typical?
* Which assumptions are safe, and which could derail the solution?
* Is the problem under-specified unless I add assumptions?

### Output of this step

Two lists:

* confirmed facts
* assumed conditions

### Example

Fact:
“The data comes from multiple hospitals.”

Assumption:
“The vendor names are normalized consistently.”

That assumption is dangerous. If false, the whole matching strategy changes.

This step is where sloppy solvers get exposed.

---

## 8. Check completeness: is the problem well-posed?

Not every problem is ready to solve.

Ask:

* Is there enough information to determine a unique solution?
* Could multiple answers satisfy the statement?
* Is there missing data?
* Are there contradictory conditions?
* Is the problem impossible as stated?
* Is the problem underspecified, overspecified, or ill-formed?

### Output of this step

A judgment:

* well-posed
* ambiguous
* underdetermined
* inconsistent
* impossible without added assumptions

### Example

A classic failure:
A word problem asks for a unique age, but the equations only constrain a family of possibilities. A careless solver plows ahead anyway.

Understanding includes the right to say:
“This problem is incomplete.”

That is not failure. That is competence.

---

## 9. Establish the constraints and success criteria

The target alone is not enough. A solution must satisfy conditions.

Ask:

* What limits apply?
* What resources are allowed?
* What methods are forbidden or preferred?
* What precision is required?
* What counts as acceptable error?
* What time, cost, or complexity bounds matter?
* What would make a solution invalid even if it looks clever?

### Output of this step

A concrete list of pass/fail conditions.

### Example

For an algorithm:

* must run in memory on a laptop
* cannot use external APIs
* must be reproducible
* must explainable to auditors
* should finish in under 10 minutes on dataset X

Now you are solving the real problem, not an imaginary cleaner version.

---

## 10. Identify the type or family of problem

Pólya often asked solvers to recognize whether they had seen a similar form before.

Ask:

* What kind of problem is this structurally?
* Is it a search problem, proof problem, optimization problem, classification problem, inversion problem, decomposition problem?
* Does it resemble a known template?

This is not yet solution-planning. It is classification for understanding.

### Output of this step

A tentative problem class.

### Examples

* “This is a constrained optimization problem.”
* “This is an inverse problem.”
* “This is really a diagnosis problem, not a design problem.”
* “This is a schema-matching problem disguised as a naming issue.”

This reframing can radically change the path forward.

---

## 11. Test your understanding by generating small examples

A brutal way to expose fake understanding is to instantiate the problem with simpler numbers or toy cases.

Ask:

* What happens in the smallest nontrivial case?
* Can I create a simple example by hand?
* Can I predict behavior in edge cases?
* What happens at zero, one, empty input, symmetry, or extremes?

### Output of this step

A few sanity-check examples.

### Why this matters

If your understanding is real, it should survive concrete examples.

### Example

If you are designing a matching algorithm, try:

* exact match
* abbreviation match
* typo match
* legal suffix noise
* merged vendor names
* null or blank values

A methodology that breaks immediately on toy cases was never understood.

---

## 12. Ask the canonical Pólya questions

These are the backbone of the phase. In modernized form:

* What is the unknown?
* What are the data?
* What is the condition?
* Is the condition sufficient?
* Is it insufficient?
* Is it redundant?
* Is it contradictory?
* Can I separate the condition into parts?
* Can I represent the problem another way?

These are not decorative questions. They are a diagnostic system.

---

## 13. Define the boundaries of the problem

A lot of wasted effort comes from solving beyond the scope.

Ask:

* What is in scope?
* What is out of scope?
* Am I being asked to solve the core problem only, or also validation, implementation, scaling, UX, deployment?
* Is this a local issue or a systemic one?

### Output of this step

A boundary statement.

### Example

“In scope: identify duplicate vendors from export data.
Out of scope: building the production monitoring dashboard.”

Without this, problem-solving turns into uncontrolled expansion.

---

## 14. Reformulate until the problem becomes operational

At the end of the Understand phase, the problem should be expressible in a form that can be attacked.

This usually means translating the original statement into one of the following:

* a formal model
* a mathematical relation
* an input/output spec
* a decision rule
* a system state description
* a set of constraints plus an objective

### Output of this step

An operational problem statement.

### Example

Weak:
“Make the system better at matching vendors.”

Operational:
“Given a source vendor record and candidate master vendors, produce a ranked match score and an explanation, with recall prioritized above precision during candidate generation and human-review thresholds applied downstream.”

Now the work can actually begin.

---

# What a completed “Understand” phase should produce

Before moving to planning, you should be able to produce the following artifact:

## Understand-phase deliverable

1. **Problem restatement**
2. **Exact objective**
3. **Knowns / givens**
4. **Unknowns**
5. **Definitions / clarified terms**
6. **Constraints**
7. **Facts vs assumptions**
8. **Representation**
   diagram, table, equations, state map, etc.
9. **Problem type**
10. **Edge cases / toy examples**
11. **Well-posedness judgment**
12. **Success criteria**

If those are missing, you are not done understanding.

---

# Common failure modes in the Understand phase

## 1. Premature solving

The solver starts applying techniques before defining the target.

## 2. Hidden assumption takeover

The solver silently inserts standard assumptions that the problem never granted.

## 3. Vocabulary illusion

The solver recognizes the words but not the structure.

## 4. Goal drift

The solver answers a nearby question because it is easier.

## 5. Constraint blindness

The solver finds a theoretically valid answer that violates practical limits.

## 6. No representation

The solver keeps the whole problem verbal and fuzzy rather than making it explicit.

## 7. Failure to challenge the prompt

The solver treats the statement as automatically complete and internally consistent.

---

# A compact procedural template

Here is a practical version you can reuse.

## Understand Phase Template

**A. Restate**

* What is being asked?

**B. Target**

* What exactly must be found, built, explained, or decided?

**C. Givens**

* What information is explicitly provided?

**D. Conditions**

* What constraints, rules, or boundaries apply?

**E. Unknowns**

* What is missing, and what intermediate values may connect givens to target?

**F. Definitions**

* What terms need clarification?

**G. Representation**

* What diagram, model, table, or formalism makes the problem visible?

**H. Assumptions**

* What am I assuming that is not stated?

**I. Well-posedness**

* Is the problem complete, consistent, and solvable as stated?

**J. Success criteria**

* What would a correct and acceptable answer look like?

---

# Example: applying the methodology to a software problem

Problem:
“Why does the agent fail intermittently when child tasks write to shared session state?”

## Understand phase result

**Restatement**
I need to determine the cause of nondeterministic agent failures that occur when child workflows mutate shared session state.

**Objective**
Identify the root cause and define the conditions under which it occurs.

**Givens**

* Parent and child tasks share session state
* Failures are intermittent
* Child tasks write to overlapping keys
* Failures do not occur in all runs

**Unknowns**

* Exact failure mechanism
* Whether issue is race condition, overwrite, stale read, or invalid state transition
* Whether session semantics are atomic

**Definitions**

* “Intermittent” = not reproducible every run
* “Shared session state” = same scoped key-value store visible across tasks

**Constraints**

* Must preserve current architecture if possible
* Diagnosis should be reproducible
* Need explanation, not just workaround

**Facts vs assumptions**
Fact: multiple children write to shared state
Assumption: writes are serialized safely

**Representation**
Draw parent-child execution timeline with state writes and reads

**Problem type**
Concurrency / state-coherence diagnosis

**Toy cases**

* one child, one key
* two children, same key
* two children, different keys
* delayed writes
* retry behavior

**Well-posedness**
Solvable if execution logs or instrumented traces are available; otherwise under-observed

**Success criteria**
A correct answer explains the mechanism, reproduces it, and identifies a fix or guardrail

That is a real Understand phase. Notice that no fixing has started yet.

---

# The deepest insight in Pólya’s “Understand” phase

The real power of this phase is that it converts a problem from a **word cloud** into a **structured object**.

Once that happens:

* irrelevant detail falls away
* missing information becomes obvious
* hidden assumptions get exposed
* the correct form of attack becomes visible

That is why strong problem solvers can look “intuitive.” They are not guessing better. They are understanding better.

If you want, I can also turn this into:

1. a **one-page checklist**,
2. a **software-engineering adapted version**, or
3. a **Pólya phase-by-phase methodology** covering Understand, Devise a Plan, Carry Out the Plan, and Look Back.
