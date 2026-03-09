# LSP and Staleness Prevention: Research Findings

> Research conducted 2026-03-09. Focused on keeping codebase documentation accurate
> and preventing staleness for a solo-dev Python project (RLM-ADK).

---

## Table of Contents

1. [LSP for Documentation Generation and Validation](#1-lsp-for-documentation-generation-and-validation)
2. [LSP-Based Dependency Graphs](#2-lsp-based-dependency-graphs)
3. [Staleness Detection Methods](#3-staleness-detection-methods)
4. [Python-Specific LSP Servers](#4-python-specific-lsp-servers-pyrightpylspjedi)
5. [Tree-Sitter for Structural Analysis](#5-tree-sitter-for-structural-analysis)
6. [Automated Documentation Validation Tools](#6-automated-documentation-validation-tools)
7. [Recommendations for RLM-ADK](#7-recommendations-for-rlm-adk)

---

## 1. LSP for Documentation Generation and Validation

### How It Works

The Language Server Protocol (LSP v3.17) defines a standard JSON-RPC interface between
development tools and language servers. Key LSP requests useful for documentation:

| LSP Request | What It Returns | Doc Use Case |
|---|---|---|
| `textDocument/documentSymbol` | Tree of all symbols (classes, functions, attrs) in a file | Generate module-level API inventories |
| `textDocument/hover` | Type info, docstrings, signatures at a position | Validate hover docs match written docs |
| `textDocument/definition` | Go-to-definition location | Trace symbol origins for cross-ref docs |
| `textDocument/references` | All call-sites / usages of a symbol | Identify which docs need updating when a symbol changes |
| `textDocument/signatureHelp` | Function parameter names, types, defaults | Compare documented signatures vs actual |
| `workspace/symbol` | Search all symbols across workspace | Discover undocumented public APIs |

### Programmatic Access: multilspy

Microsoft's **multilspy** library is the most practical way to use LSP programmatically
from Python scripts (without an IDE).

- **Repo**: https://github.com/microsoft/multilspy
- **Supported servers**: jedi-language-server (Python), Eclipse JDTLS (Java), Rust Analyzer, gopls, TypeScript, and 5 others
- **Python server**: Uses jedi-language-server under the hood
- **Key APIs**:
  - `lsp.request_definition(file, line, col)` -- go-to-definition
  - `lsp.request_references(file, line, col)` -- find all references
  - `lsp.request_document_symbols(file)` -- list all symbols in a file
  - `lsp.request_hover(file, line, col)` -- type info and docs
  - `lsp.request_completions(file, line, col)` -- completions at point
- **Usage pattern**:

```python
from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger

config = MultilspyConfig.from_dict({"code_language": "python"})
logger = MultilspyLogger()
lsp = SyncLanguageServer.create(config, logger, "/path/to/project/")

with lsp.start_server():
    symbols = lsp.request_document_symbols("rlm_adk/orchestrator.py")
    refs = lsp.request_references("rlm_adk/state.py", 10, 0)
```

### Caveats

- **Pyright LSP returns incomplete references** unless you send `textDocument/didOpen`
  for every file in the workspace (impractical for large projects). jedi-language-server
  is more reliable for `documentSymbol` requests.
- LSP servers are designed for interactive use; startup time and memory overhead can be
  non-trivial for CI scripts.
- multilspy handles server binary downloads and JSON-RPC communication automatically,
  but adds a dependency.

### Integration Effort: Medium
### Staleness Prevention: Medium-High (can detect symbol changes, but requires custom scripting)
### Solo Dev Feasibility: Medium (useful but heavyweight for what it provides)

---

## 2. LSP-Based Dependency Graphs

### How It Works

Dependency graphs can be extracted via two paths:

**Path A: LSP references** -- Use `textDocument/references` and `textDocument/definition`
to trace import chains and call graphs. multilspy supports this but it requires iterating
over all symbols in all files.

**Path B: Dedicated tools** (more practical):

#### pydeps
- **How**: Analyzes Python bytecode (`.pyc` files) to find import-opcodes
- **Output**: Module-level dependency graph as SVG/PNG via Graphviz
- **Key features**: Bacon number filtering (filter by hop distance), cycle detection,
  import-chain visualization
- **Install**: `pip install pydeps` + Graphviz
- **Usage**: `pydeps rlm_adk --max-bacon=2 --no-show -o deps.svg`
- **Repo**: https://github.com/thebjorn/pydeps

#### pydeptree
- **How**: Builds dependency tree with circular import detection
- **Output**: Rich terminal output
- **Install**: `pip install pydeptree`

#### Tree-sitter approach
- Parse all files, extract `import_statement` / `import_from_statement` AST nodes
- Build adjacency list manually
- More work, but no runtime dependency on bytecode compilation

### Integration Effort: Low (pydeps) to Medium (LSP/tree-sitter)
### Staleness Prevention: Medium (graphs show what depends on what; can flag docs for modules with changed dependencies)
### Solo Dev Feasibility: High (pydeps is trivial to run)

---

## 3. Staleness Detection Methods

### 3a. Git Diff-Based Approaches

**Concept**: Compare git timestamps/diffs between code files and their documentation
to detect when docs lag behind code changes.

**Implementation patterns**:

```bash
# Find code files changed more recently than their docs
git log --since="2 weeks ago" --name-only -- 'rlm_adk/*.py' | sort -u > changed_code.txt
git log --since="2 weeks ago" --name-only -- 'CLAUDE.md' 'ai_docs/*.md' | sort -u > changed_docs.txt
# Diff the two lists to find undocumented changes
```

**More sophisticated approach** -- per-module tracking:

1. Maintain a manifest mapping code modules to their documentation sections
2. On each commit, check if changed `.py` files have corresponding doc updates
3. Flag staleness when code changes but docs don't

**CI integration**: GitHub Actions / pre-commit hook that runs `git diff --name-only HEAD~1`
and checks if documentation files were updated alongside code changes.

**Tools**:
- **DocuWriter.ai**: Commercial tool that uses git diff monitoring + AI to auto-update docs
- **Custom script**: 50-100 lines of Python comparing `git log` timestamps

### Integration Effort: Low
### Staleness Prevention: Medium (catches broad staleness, not semantic accuracy)
### Solo Dev Feasibility: High

---

### 3b. AST Comparison Between Documented Interfaces and Actual Code

**Concept**: Parse both code and documentation to verify documented function signatures,
class hierarchies, and module structures match the actual code.

**Implementation using Python `ast` module**:

```python
import ast, inspect

tree = ast.parse(open("rlm_adk/orchestrator.py").read())
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        sig = f"{node.name}({', '.join(a.arg for a in node.args.args)})"
        # Compare against documented signatures
```

**Implementation using `inspect` module** (runtime):

```python
import inspect
from rlm_adk.orchestrator import RLMOrchestratorAgent
sig = inspect.signature(RLMOrchestratorAgent.__init__)
# Compare against docs
```

**Griffe** (recommended -- see Section 6) automates this with built-in API diffing.

### Integration Effort: Medium (ast) / Low (Griffe)
### Staleness Prevention: High (catches actual signature/structure mismatches)
### Solo Dev Feasibility: High

---

### 3c. CI/CD Hooks That Validate Docs

**Pre-commit hooks**:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-docs-freshness
        name: Check documentation freshness
        entry: python scripts/check_doc_staleness.py
        language: python
        pass_filenames: false
        always_run: true

      - id: interrogate
        name: Check docstring coverage
        entry: interrogate rlm_adk/ --fail-under=80
        language: python
        types: [python]
```

**GitHub Actions**:

```yaml
- name: Check API docs match code
  run: |
    griffe check rlm_adk --against=main
    interrogate rlm_adk/ --fail-under=80
```

**numpydoc validation**: Sphinx extension that raises warnings for undocumented
parameters in function signatures (validates docstring completeness at build time).

### Integration Effort: Low-Medium
### Staleness Prevention: High (automated, runs every commit/PR)
### Solo Dev Feasibility: High

---

## 4. Python-Specific LSP Servers (pyright/pylsp/jedi)

### Comparison

| Feature | pyright | pylsp (python-lsp-server) | jedi-language-server |
|---|---|---|---|
| Type checking | Full static type checker | Via mypy/pyflakes plugins | Inference only |
| Signature extraction | Yes (typed) | Yes | Yes |
| Find references | Yes (needs didOpen for all files) | Yes | Yes |
| Document symbols | Yes | Yes | Yes |
| Hover info | Rich (types + docstrings) | Good | Good |
| Programmatic use | Difficult (Node.js) | Python-native | Python-native |
| Speed | Fast | Medium | Medium |
| Standalone CLI | `pyright --outputjson` | No | No |

### pyright for Programmatic Use

Pyright has a useful **command-line mode** that outputs JSON:

```bash
pyright --outputjson rlm_adk/ > type_report.json
```

This gives you all type errors, inferred types, and diagnostics -- useful for
validating that documented types match actual types. However, pyright is a Node.js
tool (requires npm), not a Python library.

### Jedi as a Library (Most Practical for Scripts)

Jedi can be used directly as a Python library without LSP overhead:

```python
import jedi

script = jedi.Script(path="rlm_adk/orchestrator.py")

# Get all names (classes, functions, variables) in a module
names = script.get_names(all_scopes=True, definitions=True)
for name in names:
    print(f"{name.type}: {name.name} at line {name.line}")
    sigs = name.get_signatures()
    for sig in sigs:
        print(f"  Signature: {sig.to_string()}")

# Search across project
project = jedi.Project(path="/home/rawley-stanhope/dev/rlm-adk/")
script = jedi.Script(path="rlm_adk/state.py", project=project)
refs = script.get_references(line=10, column=0)
```

**Key Jedi API methods**:
- `Script.get_names()` -- all symbols in a file (filterable by type)
- `Script.get_signatures()` -- function signatures at a position
- `Script.get_references()` -- find all references to a symbol
- `Script.infer()` -- resolve definitions
- `Script.complete()` -- completions
- `Script.search()` -- search by name across project

### Integration Effort: Low (Jedi library) / Medium (LSP server)
### Staleness Prevention: High (can extract current state of all APIs for comparison)
### Solo Dev Feasibility: High (Jedi is already a dependency of most Python environments)

---

## 5. Tree-Sitter for Structural Analysis

### How It Works

Tree-sitter is an incremental parsing library that builds concrete syntax trees (CSTs)
for source code. Unlike Python's `ast` module, tree-sitter:

- Works on **any language** (not just Python)
- Handles **broken/partial code** gracefully
- Supports **incremental parsing** (only re-parses changed regions)
- Provides **query syntax** for pattern matching on the tree

### Python Bindings

```bash
pip install tree-sitter tree-sitter-python
```

```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

code = open("rlm_adk/orchestrator.py", "rb").read()
tree = parser.parse(code)

# Query for all function definitions
query = PY_LANGUAGE.query("""
(function_definition
  name: (identifier) @func_name
  parameters: (parameters) @params
  return_type: (type)? @return_type)
""")

matches = query.matches(tree.root_node)
for match in matches:
    for capture_name, nodes in match[1].items():
        for node in nodes:
            print(f"{capture_name}: {node.text.decode()}")
```

### Key Capabilities for Documentation

| Capability | How | Doc Use |
|---|---|---|
| Extract all function signatures | Query `function_definition` nodes | Compare against documented APIs |
| Extract class hierarchies | Query `class_definition` with `argument_list` | Validate inheritance docs |
| Extract imports | Query `import_statement`, `import_from_statement` | Build dependency graphs |
| Detect structural changes | `Tree.changed_ranges(old_tree, new_tree)` | Flag which docs need updating |
| Extract docstrings | Query `expression_statement > string` as first child of function/class | Validate docstring existence |
| Extract decorators | Query `decorator` nodes | Document middleware/plugin patterns |

### tree-sitter-analyzer

The `tree-sitter-analyzer` PyPI package provides higher-level analysis:
- Summary mode, detailed structure, complexity metrics
- JSON and text output formats
- Multi-language support
- Install: `pip install tree-sitter-analyzer`

### Change Detection

Tree-sitter's `changed_ranges()` is particularly powerful:

```python
old_tree = parser.parse(old_code)
new_tree = parser.parse(new_code)
changed = old_tree.changed_ranges(new_tree)
# Returns list of Range objects identifying structurally changed regions
```

This enables targeted staleness detection: only check documentation for functions/classes
that fall within changed ranges.

### Integration Effort: Medium (requires writing queries, but well-documented)
### Staleness Prevention: High (precise structural change detection)
### Solo Dev Feasibility: High (lightweight, fast, no server process)

---

## 6. Automated Documentation Validation Tools

### 6a. Griffe (Strongest Recommendation)

**What**: Extracts the complete API skeleton of a Python package and can diff between
versions to find breaking changes. Powers mkdocstrings.

**Repo**: https://github.com/mkdocstrings/griffe

**How it works**:
1. Parses Python source via AST (or inspects at runtime)
2. Builds a tree of Module > Class > Function > Attribute > Alias objects
3. Each object carries: name, signature, docstring, type annotations, decorators, line numbers
4. Can serialize the entire API to JSON
5. Can compare two versions and report breaking changes

**Key commands**:

```bash
# Dump API structure as JSON
griffe dump rlm_adk -d google

# Check for breaking changes since last release/commit
griffe check rlm_adk --against=git:HEAD~5

# Programmatic use
python -c "
import griffe
pkg = griffe.load('rlm_adk')
for name, obj in pkg.members.items():
    print(f'{obj.kind.value}: {name}')
    if hasattr(obj, 'members'):
        for mname, mobj in obj.members.items():
            print(f'  {mobj.kind.value}: {mname}')
"
```

**Programmatic API for staleness detection**:

```python
import griffe

# Load current API
current = griffe.load("rlm_adk")

# Load API from a previous git ref
previous = griffe.load_git("rlm_adk", ref="HEAD~10")

# Find breaking changes
for breakage in griffe.find_breaking_changes(previous, current):
    print(f"BREAKING: {breakage.kind.value} in {breakage.object.path}")
    print(f"  {breakage.explain()}")
```

**Breakage types detected**:
- Parameter added/removed/changed kind (positional vs keyword)
- Default value changes
- Return type changes
- Attribute type/value changes
- Base class removed
- Object kind changed (function became class, etc.)
- Object removed entirely

**Docstring parsing**: Supports Google, NumPy, and Sphinx docstring styles.

### Integration Effort: Low (pip install griffe, one-line CLI)
### Staleness Prevention: Very High (semantic API diffing, not just text comparison)
### Solo Dev Feasibility: Very High (minimal config, immediate value)

---

### 6b. interrogate (Docstring Coverage)

**What**: Checks Python codebase for missing docstrings, reports coverage percentage.

**Repo**: https://github.com/econchick/interrogate

```bash
pip install interrogate

# Check coverage
interrogate rlm_adk/ -v --fail-under=80

# Output resembles pytest-cov
# rlm_adk/orchestrator.py    85%
# rlm_adk/dispatch.py        72%
# TOTAL                       78%  FAILED (minimum: 80%)
```

**Configuration** (pyproject.toml):

```toml
[tool.interrogate]
ignore-init-method = true
ignore-init-module = true
fail-under = 80
exclude = ["tests_rlm_adk"]
verbose = 1
```

**Pre-commit integration**:

```yaml
- repo: https://github.com/econchick/interrogate
  rev: 1.7.0
  hooks:
    - id: interrogate
      args: [--fail-under=80, rlm_adk/]
```

### Integration Effort: Very Low
### Staleness Prevention: Medium (catches missing docstrings, not inaccurate ones)
### Solo Dev Feasibility: Very High

---

### 6c. docstr-coverage

**What**: Similar to interrogate but with pre-commit-native support and `.docstr.yaml` config.

```bash
pip install docstr-coverage
docstr-coverage rlm_adk/ --fail-under=80
```

### Integration Effort: Very Low
### Staleness Prevention: Medium
### Solo Dev Feasibility: Very High

---

### 6d. Sphinx Autodoc

**What**: Generates documentation directly from Python docstrings at build time.
Documentation is always in sync because it IS the docstrings.

**Key benefit**: If the function signature changes, the generated docs automatically
reflect the new signature (no separate doc file to update).

**Limitation**: Only covers docstring-based docs. External documentation (like CLAUDE.md
or architecture docs) is not covered.

**Integration**: Requires Sphinx setup, `conf.py`, RST/MD templates.

### Integration Effort: Medium-High (initial Sphinx setup)
### Staleness Prevention: High (for API docs), None (for prose docs)
### Solo Dev Feasibility: Medium (maintenance overhead for a solo dev)

---

### 6e. doctest

**What**: Python stdlib module that validates code examples in docstrings by executing them.

```python
def depth_key(key: str, depth: int) -> str:
    """Return a depth-scoped state key.

    >>> depth_key("iteration_count", 2)
    'iteration_count@d2'
    >>> depth_key("iteration_count", 0)
    'iteration_count@d0'
    """
    return f"{key}@d{depth}"
```

```bash
python -m doctest rlm_adk/state.py -v
```

**Integration with pytest**:

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "--doctest-modules"
```

### Integration Effort: Very Low
### Staleness Prevention: High (for documented examples -- they either pass or fail)
### Solo Dev Feasibility: Very High (zero infrastructure)

---

## 7. Recommendations for RLM-ADK

### Context

RLM-ADK is a solo-dev project with:
- ~20 Python modules in `rlm_adk/`
- Extensive `CLAUDE.md` (architecture docs for AI assistants)
- `ai_docs/` directory with supplementary documentation
- `issues/` directory with bug documentation
- Complex architecture (recursive agents, AST rewriting, worker pools)
- Already uses ruff for linting, pytest for testing

### Tiered Recommendation

#### Tier 1: Implement Now (< 1 hour each, high impact)

1. **Griffe API diffing in CI/pre-commit**
   - `griffe check rlm_adk --against=git:main` on every PR
   - Catches breaking API changes that documentation should reflect
   - Zero configuration needed beyond `pip install griffe`

2. **interrogate for docstring coverage**
   - Add to `pyproject.toml`, set `fail-under=60` initially (ramp up over time)
   - Ensures new code gets documented
   - Integrate as pre-commit hook

3. **Git diff staleness script**
   - Simple script: if files in `rlm_adk/` changed but `CLAUDE.md` hasn't been
     touched in N commits, emit a warning
   - 50 lines of Python, runs in pre-commit or CI

#### Tier 2: Implement When Needed (2-4 hours, medium impact)

4. **Jedi-based API inventory script**
   - Script that uses `jedi.Script.get_names()` to enumerate all public APIs
   - Compare against a documented inventory (could be a section in CLAUDE.md)
   - Run periodically or in CI to catch undocumented new modules/functions

5. **Tree-sitter structural change detector**
   - Parse changed files with tree-sitter, extract function/class signatures
   - Compare against a cached baseline (JSON file in repo)
   - More precise than git diff alone -- knows WHAT changed, not just THAT something changed

6. **doctest for critical utilities**
   - Add doctest examples to `state.py`, `repl/ast_rewriter.py`, and other
     pure-function modules
   - Run via `--doctest-modules` in pytest
   - Self-validating documentation

#### Tier 3: Consider Later (significant setup, specialized value)

7. **multilspy for cross-reference validation**
   - Use LSP references to validate that documented call flows match actual code
   - Heavyweight but powerful for complex architecture docs

8. **Sphinx autodoc for generated API reference**
   - Only if external documentation consumers emerge
   - Overkill for current AI-assistant-focused docs

9. **pydeps for dependency graph snapshots**
   - Generate SVG dependency graph, commit to repo
   - Compare in CI to detect architecture drift

### Recommended Stack Summary

| Tool | Purpose | When |
|---|---|---|
| **griffe** | API diffing, breaking change detection | Every PR |
| **interrogate** | Docstring coverage enforcement | Every commit (pre-commit) |
| **git diff script** | CLAUDE.md / prose doc staleness | Every PR |
| **jedi** | API inventory extraction | Monthly / on-demand |
| **tree-sitter** | Structural change detection | When architecture docs matter |
| **doctest** | Self-validating code examples | As docstrings are written |

### Key Insight

For a solo-dev project, the highest-leverage approach is **Griffe + interrogate + a
simple git-diff staleness check**. These three tools:

- Require under 30 minutes total to set up
- Run automatically (pre-commit or CI)
- Catch the three most common staleness modes:
  1. API changed but docs didn't (Griffe)
  2. New code has no docs at all (interrogate)
  3. Prose docs haven't been touched despite code churn (git diff script)

The LSP and tree-sitter approaches are more powerful but add complexity that isn't
justified until the project has multiple contributors or external documentation consumers.

---

## Sources

- [LSP Specification](https://microsoft.github.io/language-server-protocol/)
- [multilspy - Microsoft LSP client library](https://github.com/microsoft/multilspy)
- [python-lsp-server](https://github.com/python-lsp/python-lsp-server)
- [Jedi API Documentation](https://jedi.readthedocs.io/en/latest/docs/api.html)
- [pyright](https://github.com/microsoft/pyright)
- [Griffe - API structure extraction](https://mkdocstrings.github.io/griffe/)
- [Griffe - API checks](https://mkdocstrings.github.io/griffe/reference/api/checks/)
- [interrogate - docstring coverage](https://github.com/econchick/interrogate)
- [docstr-coverage](https://pypi.org/project/docstr-coverage/)
- [pydeps - dependency graphs](https://github.com/thebjorn/pydeps)
- [tree-sitter Python bindings](https://tree-sitter.github.io/py-tree-sitter/)
- [tree-sitter-analyzer](https://pypi.org/project/tree-sitter-analyzer/1.7.1/)
- [IBM tree-sitter-codeviews](https://github.com/IBM/tree-sitter-codeviews)
- [Sphinx autodoc](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html)
- [pre-commit framework](https://pre-commit.com/)
- [numpydoc validation](https://numpydoc.readthedocs.io/en/latest/validation.html)
- [Python ast module](https://docs.python.org/3/library/ast.html)
- [Continuous Documentation in CI/CD - The New Stack](https://thenewstack.io/continuous-documentation-in-a-ci-cd-world/)
