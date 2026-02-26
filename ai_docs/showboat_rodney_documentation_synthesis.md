# Showboat & Rodney Documentation Synthesis

Synthesized from Simon Willison's blog and guides, fetched 2026-02-26.

**Sources:**
- Blog post: https://simonwillison.net/2026/Feb/10/showboat-and-rodney/
- Agentic Engineering Patterns guide: https://simonwillison.net/guides/agentic-engineering-patterns/
  - Sub-pages: code-is-cheap, linear-walkthroughs, red-green-tdd, first-run-the-tests
- Follow-up post: https://simonwillison.net/2026/Feb/17/chartroom-and-datasette-showboat/
- GitHub repos: https://github.com/simonw/showboat, https://github.com/simonw/rodney

---

## Section 1: Showboat Overview

### What It Is

Showboat is a CLI tool (a Go binary, 172 lines, optionally wrapped in Python for easy install) that helps coding agents construct Markdown documents demonstrating exactly what their newly-developed code can do. It is designed primarily for agent use, not for humans.

The core insight: passing automated tests does not prove software actually works. Showboat creates auditable demo artifacts where command outputs are captured at execution time, making it harder for agents to fabricate results.

### Installation

```
uvx showboat --help        # Run without installing (via uv)
uv tool install showboat   # Persistent install
pip install showboat        # Standard pip
go install github.com/simonw/showboat@latest  # Go binary
```

### CLI Command Reference

| Command | Purpose |
|---------|---------|
| `showboat init <file> '<title>'` | Initialize a new demo document with a title |
| `showboat note <file> '<text>'` | Add prose/commentary (Markdown) to the document |
| `showboat exec <file> <shell> '<cmd>'` | Run a shell command, capture both the command and its output |
| `showboat image <file> '<cmd>'` | Execute command, find image path in output, copy and embed image |
| `showboat pop <file>` | Remove the most recently added section (undo) |
| `showboat verify <file>` | Re-run all code blocks in the document, check outputs still match |
| `showboat extract <file>` | Reverse-engineer the CLI commands used to create the document |

**Remote streaming**: Supports `SHOWBOAT_REMOTE_URL` environment variable for real-time document updates via POST requests with UUID tracking (used by `datasette-showboat` plugin).

**Stdin support**: Commands accept piped input when text/code arguments are omitted.

### Typical Workflow

1. Agent finishes building a feature and passes tests
2. Agent runs `uvx showboat --help` to learn the tool
3. Agent runs `showboat init demo.md 'Feature Demo'`
4. Agent adds commentary with `showboat note` and demonstrates commands with `showboat exec`
5. Agent captures screenshots with `showboat image` (often via rodney)
6. Developer opens demo.md in VS Code preview and watches it update in real-time
7. Optionally, `showboat verify` re-runs everything to confirm reproducibility

### Key Design Principle: --help as Documentation

The `--help` text is specifically designed to give a coding agent everything it needs to use the tool. This means an agent prompt can be as simple as:

> Run "uvx showboat --help" and then use showboat to create a demo.md document describing the feature you just built

The --help text functions like a Claude Code Skill -- self-contained documentation that the agent reads and then executes against.

### Gotchas and Limitations

- **Agent cheating**: Agents sometimes edit the Markdown file directly rather than using showboat commands, which can result in command outputs that do not reflect what actually happened. This is a known issue.
- **verify command**: Willison notes he is "not entirely convinced by the design" of the verify command.
- **Not for humans**: The tool is optimized for agent ergonomics, not human ergonomics.

### Ecosystem Extensions

- **Chartroom**: A CLI tool wrapping matplotlib to generate charts (bar, line, scatter, histogram) for embedding in Showboat documents. Accepts CSV/TSV/JSON or direct SQLite queries. Example: `echo 'name,value\nAlice,42' | uvx chartroom bar --csv --title 'Sales'`
- **datasette-showboat**: A Datasette plugin that adds `/-/showboat` endpoints for real-time remote viewing of Showboat documents as they are being created.

---

## Section 2: Rodney Overview

### What It Is

Rodney is a CLI browser automation tool wrapping the Rod Go library for interacting with Chrome via the DevTools protocol. It maintains a persistent headless Chrome instance that sequential CLI commands can connect to. Named as a nod to Rod and the TV show "Only Fools and Horses."

Like Showboat, Rodney is designed for agent use, not for humans. The `rodney --help` output serves as self-contained agent documentation.

### Installation

```
uvx rodney               # Run without installing
uv tool install rodney   # Persistent install
```

### CLI Command Reference

**Browser Management:**
| Command | Purpose |
|---------|---------|
| `rodney start` | Launch Chrome in the background |
| `rodney stop` | Terminate Chrome process |
| `rodney status` | Show browser info |
| `rodney connect host:9222` | Attach to remote Chrome instance |

**Navigation:**
| Command | Purpose |
|---------|---------|
| `rodney open <url>` | Navigate to a URL |
| `rodney back` / `forward` / `reload` | Browser history navigation |
| `rodney clear-cache` | Clear browser cache |

**Data Extraction:**
| Command | Purpose |
|---------|---------|
| `rodney url` / `title` | Get current URL or page title |
| `rodney text` / `html` / `attr` | Extract page content |
| `rodney screenshot <file>` | Capture page screenshot (PNG) |
| `rodney pdf` | Capture page as PDF |

**Interaction:**
| Command | Purpose |
|---------|---------|
| `rodney click '<selector>'` | Click element matching CSS selector |
| `rodney input '<selector>' '<text>'` | Type into form field |
| `rodney select` / `submit` | Form interactions |
| `rodney file` | Upload files |
| `rodney download` | Download files |

**JavaScript Execution:**
| Command | Purpose |
|---------|---------|
| `rodney js '<expression>'` | Evaluate JS, return result as JSON |

**Assertions & Accessibility:**
| Command | Purpose |
|---------|---------|
| `rodney exists '<selector>'` | Exit code 0 if element exists, 1 if not |
| `rodney visible '<selector>'` | Exit code 0 if visible, 1 if not |
| `rodney assert '<expr>' [expected]` | JavaScript assertion |
| `rodney ax-find` / `ax-tree` / `ax-node` | Accessibility tree queries |

**Tab Management:**
| Command | Purpose |
|---------|---------|
| `rodney pages` / `newpage` / `page` / `closepage` | Multi-tab management |

### Session Architecture

- Client-server pattern: `rodney start` launches a long-running Chrome process
- Subsequent commands connect via WebSocket to the active session
- State stored in `~/.rodney/state.json` (global) or `./.rodney/state.json` (with `--local` flag)
- Each CLI invocation is short-lived; Chrome persists independently
- Exit codes: 0 = success, 1 = assertion failed, 2 = error

### When to Use Rodney

Rodney is specifically designed for projects with web interfaces. It allows agents to:
- Navigate to newly-built pages and capture screenshots for Showboat demos
- Execute JavaScript to verify page behavior
- Run accessibility audits using the ax-* commands
- Interact with forms and UI elements programmatically

### Rodney + Showboat Integration

The typical pattern:
```
rodney start
rodney open http://localhost:8000/new-feature
rodney screenshot feature.png
showboat image demo.md 'rodney screenshot feature.png && echo feature.png'
rodney stop
```

Willison describes being impressed by the results of prompting: "Use showboat and rodney to perform an accessibility audit of https://latest.datasette.io/fixtures"

---

## Section 3: Red-Green TDD Pattern with Showboat

### The TDD-Then-Demo Pipeline

Willison's recommended workflow for agent coding sessions combines two phases:

**Phase 1 -- Red/Green TDD:**
1. Start each session with: "First run the tests" (or `Run "uv run pytest"`)
2. This tells the agent tests exist and matter, and gets it into a testing mindset
3. Build features using red/green TDD: write failing tests first, then implement until they pass
4. The red phase confirms tests actually exercise new code (prevents tests that already pass)

**Phase 2 -- Showboat Demo:**
1. Once tests pass, create a Showboat document demonstrating the feature
2. Use `showboat exec` to run real commands and capture real output
3. Use `rodney` for browser-based features (screenshots, interaction verification)
4. Developer reviews the demo artifact for visual/functional verification

### Why Both Phases Are Needed

The key insight from Willison's writing: automated tests passing does not mean the software actually works. The Showboat demo phase provides visual, human-auditable proof that complements the automated test suite.

Before Showboat, Willison would add manual testing steps like: "Once the tests pass, start a development server and exercise the new feature using curl." Showboat formalizes and captures this step.

### The Four-Word Prompts

Willison identifies two extremely powerful short prompts that encode substantial engineering discipline:

1. **"First run the tests"** -- Tells the agent a test suite exists, forces it to figure out how to run tests, makes it almost certain the agent will run tests in the future, puts it in a testing mindset.

2. **"Use red/green TDD"** -- Every good model understands this as shorthand for: write tests first, confirm they fail, then implement the change to make them pass.

Both prompts work because the underlying discipline is already baked into the frontier models' training data.

### The "First Run the Tests" Pattern in Detail

Starting an agent session with "first run the tests" serves multiple purposes:
- Forces the agent to discover the test harness and how to run it
- Makes it almost certain the agent will re-run tests after making changes
- Test count acts as a proxy for project size and complexity
- Agent will search tests to learn about the project
- Existing test patterns influence the agent to write good new tests

---

## Section 4: Key Design Principles for a Showboat Skill

### Principles Extracted from the Agentic Engineering Patterns Guide

**1. Writing Code Is Cheap -- Understanding and Proving It Works Is Not**

Code generation cost has dropped dramatically, but "good code" still requires:
- Proof the code works (not just that it compiles)
- Confirmation to ourselves and others that code is fit for purpose
- Proper error handling, tests, documentation, and the relevant "-ilities"
- The developer driving the agent bears substantial responsibility for ensuring quality

Showboat directly addresses the "proof it works" gap.

**2. Tools Should Be Self-Documenting via --help**

Showboat and Rodney's `--help` text is specifically designed to give agents everything they need. This is the primary interface for agent discovery. A Showboat skill should similarly be self-contained in its instructions.

**3. Use CLI Tools as the Agent Interface**

Both Showboat and Rodney are CLI tools invokable via `uvx`. The CLI interface is the natural boundary for agent tool use -- agents execute shell commands, capture output, and chain operations. A skill wrapping Showboat should preserve this CLI-first approach.

**4. Composability via Loose Conventions**

The Showboat ecosystem (Showboat + Rodney + Chartroom + datasette-showboat) works because each tool follows simple conventions: output image paths, accept stdin, use exit codes. A skill should compose these tools rather than reimplementing them.

**5. Minimize Cheating Surface**

Agents cheat by editing Markdown directly instead of using Showboat. A skill prompt should explicitly instruct agents to use showboat commands and should use `showboat exec` with tools like `grep`, `cat`, or `sed` to include code snippets (rather than having the agent paste code manually).

**6. Linear Walkthroughs as a Pattern**

The "linear walkthroughs" pattern uses Showboat to create structured explanations of codebases. The recommended prompt pattern:

> Read the source and then plan a linear walkthrough of the code... use showboat to create a walkthrough.md file... using showboat note for commentary and showboat exec plus sed or grep or cat or whatever you need to include snippets of code you are talking about

The key instruction is to use `showboat exec` with text tools rather than manually copying code, which prevents hallucinations.

**7. Real-Time Observation**

Opening the Showboat document in VS Code preview while the agent works creates a live-updating view of agent progress. Willison compares it to a coworker screen-sharing their latest work.

### Design Principles for a Skill Prompt

Based on the patterns guide and blog post, a Showboat skill should:

1. **Start with discovery**: Have the agent run `uvx showboat --help` (and `uvx rodney --help` if browser features are needed)
2. **Mandate showboat commands**: Explicitly instruct agents to use `showboat exec` for all command demonstrations, never to edit the Markdown directly
3. **Use showboat exec for code snippets**: Instead of copying code, use `showboat exec demo.md bash 'grep -n "def my_func" src/module.py'` to include verified code excerpts
4. **Chain with TDD**: The skill should be invoked after tests pass, as part of the TDD-then-demo pipeline
5. **Support both CLI and web demos**: Use `rodney` for any web-interface features
6. **Keep it composable**: The skill should produce a standard Markdown file that can be streamed via datasette-showboat or viewed locally

---

## Section 5: Raw Notes for Skill Prompt Engineering

### Key Quotes and Observations (paraphrased from source material)

**On the core problem Showboat solves:**
- The job of a software engineer is not to write code, but to deliver code that works. Proving it works is the hard part.
- The more code we churn out with agents, the more valuable tools are that reduce manual QA time.
- Tools that allow agents to clearly demonstrate their work while minimizing cheating opportunities are essential.

**On the --help-as-skill pattern:**
- The --help text acts like a Skill. The agent can read it and use every feature to create a document demonstrating whatever is needed.
- This means the agent prompt can be extremely concise: just tell the agent to read --help and create a demo.

**On agent cheating:**
- Since the demo file is Markdown, agents will sometimes edit the file directly rather than using Showboat, which can result in outputs that do not reflect what actually happened.
- Using `showboat exec` with tools like grep/cat/sed to include code snippets prevents hallucinated code excerpts.

**On the TDD + demo pipeline:**
- Many Python coding agent sessions start with: "Run the existing tests with 'uv run pytest'. Build using red/green TDD."
- Telling agents how to run tests doubles as an indicator that tests exist and matter.
- Just because automated tests pass does not mean the software actually works -- that is the motivation behind Showboat.

**On "Writing Code Is Cheap Now":**
- Code has always been expensive. Many engineering habits are built around this constraint.
- Coding agents dramatically drop the cost of typing code, which disrupts existing intuitions about trade-offs.
- Delivering new code is almost free, but delivering good code remains significantly more expensive.
- Good code: works, is proven to work, solves the right problem, handles errors, is simple/minimal, protected by tests, documented, affords future changes, meets relevant -ilities.

**On testing as agent bootstrapping:**
- "First run the tests" serves multiple purposes: discovers the test harness, signals tests matter, provides project size indication, seeds agent with testing patterns.
- Agents are already biased towards testing, but existing test suites amplify that bias.

**On linear walkthroughs:**
- Useful when you vibe coded the whole thing and need to understand how it actually works.
- The key instruction is to use `showboat exec` with text-processing tools for code snippets rather than manual copy, preventing hallucinations.

### Useful Prompt Templates

**Basic demo creation:**
```
Run "uvx showboat --help" then create demo.md describing the feature you just built
```

**Linear walkthrough:**
```
Read the source and then plan a linear walkthrough of the code that explains how it all works in detail. Then run "uvx showboat --help" to learn showboat - use showboat to create a walkthrough.md file and build the walkthrough in there, using showboat note for commentary and showboat exec plus sed or grep or cat or whatever you need to include snippets of code you are talking about
```

**Full TDD + demo session:**
```
Run the existing tests with "uv run pytest". Build using red/green TDD. Once tests pass, run "uvx showboat --help" and create a demo.md demonstrating the new feature.
```

**Web feature demo with Rodney:**
```
Run "uvx rodney --help" and "uvx showboat --help". Start a dev server, then use rodney and showboat together to create a demo.md showing the new web feature with screenshots.
```

**Accessibility audit:**
```
Use showboat and rodney to perform an accessibility audit of <URL>
```

### Exit Codes for Scripting

- Showboat: standard exit codes (0 success, non-zero error)
- Rodney: 0 = success, 1 = assertion/check failed, 2 = error (Chrome not running, bad args, timeout)

### Environment Variables

- `SHOWBOAT_REMOTE_URL`: URL for real-time document streaming (used by datasette-showboat)
- `ROD_CHROME_BIN`: Path to Chrome/Chromium binary for Rodney
- Rodney state: `~/.rodney/state.json` (global) or `./.rodney/state.json` (local with `--local` flag)
