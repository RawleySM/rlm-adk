# User-Provided Context: Directory Serialization and State Wiring

*2026-03-15 by Showboat*

## Summary

The user-provided context feature allows operators to load a directory of textual files into the RLM agent's working memory via the `RLM_USER_CTX_DIR` environment variable. The implementation uses a smallest-first packing strategy: files are sorted by size and packed into a context dict until a character budget (`RLM_USER_CTX_MAX_CHARS`, default 500k) is exhausted. Files that exceed the budget are recorded as "unserialized" so the agent can load them on demand via `open()`.

This gives the agent immediate access to small reference files (config, schemas, READMEs) while deferring large files (data dumps, logs) to on-demand reads -- maximizing context coverage without blowing the token budget.

## Architecture

```
RLM_USER_CTX_DIR=/path/to/ctx
RLM_USER_CTX_MAX_CHARS=2000
        |
        v
load_user_context(dir_path, max_chars)
        |
        v
  os.walk() -> filter textual extensions -> sort by size (smallest first)
        |
        v
  Pack into ctx dict until max_chars exceeded
        |
        v
  UserContextResult
    .ctx              -> {"file.py": "contents...", ...}
    .serialized       -> ["file.py", ...]
    .unserialized     -> ["big_data.csv", ...]
    .exceeded         -> True/False
    .build_manifest() -> instruction string for dynamic prompt
        |
        v
  Orchestrator wires into ADK state:
    user_provided_ctx          -> ctx dict
    user_provided_ctx_exceeded -> bool
    usr_provided_files_serialized   -> list[str]
    usr_provided_files_unserialized -> list[str]
    user_ctx_manifest          -> manifest string (dynamic instruction)
        |
        v
  REPL globals: user_ctx = ctx dict (agent code can do user_ctx["file.py"])
```

## Key Components

### UserContextResult (`rlm_adk/utils/user_context.py`)

- **`ctx`** -- dict mapping relative paths to file contents (only files that fit the budget)
- **`serialized`** -- list of filenames that were packed into `ctx`
- **`unserialized`** -- list of filenames that exceeded the budget (agent uses `open()`)
- **`exceeded`** -- True if any files were evicted
- **`build_manifest()`** -- generates a human-readable manifest string injected into the dynamic instruction via `{user_ctx_manifest?}` placeholder

### load_user_context() (`rlm_adk/utils/user_context.py`)

- Walks the directory recursively
- Filters to textual extensions (`.py`, `.md`, `.json`, `.yaml`, `.csv`, etc.)
- Sorts by size ascending (smallest first) to maximize file count within budget
- Packs greedily: once a file would exceed `max_chars`, it goes to `unserialized`

### State Keys (`rlm_adk/state.py`)

- `USER_PROVIDED_CTX` -- the ctx dict itself
- `USER_PROVIDED_CTX_EXCEEDED` -- whether any files were evicted
- `USR_PROVIDED_FILES_SERIALIZED` -- list of packed filenames
- `USR_PROVIDED_FILES_UNSERIALIZED` -- list of evicted filenames
- `DYN_USER_CTX_MANIFEST` -- manifest string for `{user_ctx_manifest?}` template resolution

## Demo 1: Basic Loading with Eviction

Create a temp directory with 3 files (2 small, 1 large) and load with a threshold that forces eviction.

```python
# demo_showboat/_demo_user_ctx_basic.py
import tempfile, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rlm_adk.utils.user_context import load_user_context

# Create temp directory with 3 files
with tempfile.TemporaryDirectory() as d:
    # Small file 1: 50 chars
    with open(os.path.join(d, "config.yaml"), "w") as f:
        f.write("db_host: localhost\ndb_port: 5432\ndb_name: myapp\n")

    # Small file 2: 30 chars
    with open(os.path.join(d, "notes.txt"), "w") as f:
        f.write("TODO: refactor auth module\n!!!")

    # Large file: 500 chars
    with open(os.path.join(d, "big_data.csv"), "w") as f:
        f.write("id,value\n" + "\n".join(f"{i},{i*10}" for i in range(60)))

    # Load with threshold=200 (fits small files, evicts big one)
    result = load_user_context(d, max_chars=200)

    print(f"serialized:   {result.serialized}")
    print(f"unserialized: {result.unserialized}")
    print(f"exceeded:     {result.exceeded}")
    print(f"total_chars:  {result.total_chars}")
    print(f"ctx keys:     {list(result.ctx.keys())}")
    print()

    # Verify small files are in ctx, large file is not
    assert "notes.txt" in result.ctx, "notes.txt should be serialized"
    assert "config.yaml" in result.ctx, "config.yaml should be serialized"
    assert "big_data.csv" not in result.ctx, "big_data.csv should be evicted"
    assert result.exceeded is True
    assert len(result.serialized) == 2
    assert len(result.unserialized) == 1
    print("PASS: small files packed, large file evicted")
```

**Expected output:**

```
serialized:   ['notes.txt', 'config.yaml']
unserialized: ['big_data.csv']
exceeded:     True
total_chars:  78
ctx keys:     ['notes.txt', 'config.yaml']

PASS: small files packed, large file evicted
```

## Demo 2: Manifest Output

Show that `build_manifest()` produces the correct instruction string for dynamic prompt injection.

```python
# demo_showboat/_demo_user_ctx_manifest.py
import tempfile, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rlm_adk.utils.user_context import load_user_context

with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, "schema.sql"), "w") as f:
        f.write("CREATE TABLE users (id INT, name TEXT);")

    with open(os.path.join(d, "readme.md"), "w") as f:
        f.write("# My Project\nA small project.")

    with open(os.path.join(d, "dump.csv"), "w") as f:
        f.write("x," * 5000)  # 10000 chars

    result = load_user_context(d, max_chars=500)
    manifest = result.build_manifest()
    print(manifest)
    print()

    # Verify structure
    assert "Pre-loaded context variable: user_ctx (dict)" in manifest
    assert 'Pre-loaded files (access via user_ctx["<filename>"])' in manifest
    assert "Files exceeding pre-load threshold (load via open())" in manifest
    assert "dump.csv" in manifest
    assert "requires open()" in manifest
    print("PASS: manifest contains all expected sections")
```

**Expected output:**

```
Pre-loaded context variable: user_ctx (dict)
Pre-loaded files (access via user_ctx["<filename>"]):
  - readme.md (30 chars)
  - schema.sql (39 chars)
Files exceeding pre-load threshold (load via open()):
  - dump.csv (10,000 chars) -> open("/tmp/.../dump.csv")
Total: 3 files, 2 pre-loaded, 1 requires open()

PASS: manifest contains all expected sections
```

## Demo 3: Threshold Eviction Ordering

Demonstrates that smallest-first packing maximizes file count. With a tight budget, the system packs as many small files as possible before evicting.

```python
# demo_showboat/_demo_user_ctx_eviction.py
import tempfile, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rlm_adk.utils.user_context import load_user_context

with tempfile.TemporaryDirectory() as d:
    # 5 files of increasing size
    sizes = {"tiny.txt": 10, "small.py": 50, "medium.md": 150, "large.json": 400, "huge.csv": 1000}
    for name, sz in sizes.items():
        with open(os.path.join(d, name), "w") as f:
            f.write("x" * sz)

    # Budget = 220 chars -> fits tiny(10) + small(50) + medium(150) = 210, evicts large + huge
    result = load_user_context(d, max_chars=220)

    print(f"Budget: 220 chars")
    print(f"Packed:   {result.serialized} (total {result.total_chars} chars)")
    print(f"Evicted:  {result.unserialized}")
    print()

    assert result.serialized == ["tiny.txt", "small.py", "medium.md"]
    assert result.unserialized == ["large.json", "huge.csv"]
    assert result.total_chars == 210
    print("PASS: smallest-first packing maximizes file count within budget")

    # Now with budget = 60 -> fits tiny(10) + small(50) = 60, evicts rest
    result2 = load_user_context(d, max_chars=60)
    print(f"\nBudget: 60 chars")
    print(f"Packed:   {result2.serialized} (total {result2.total_chars} chars)")
    print(f"Evicted:  {result2.unserialized}")

    assert result2.serialized == ["tiny.txt", "small.py"]
    assert len(result2.unserialized) == 3
    print("PASS: tighter budget evicts more files, still smallest-first")
```

## Demo 4: State Key Population

Verifies all 5 state keys are populated with correct types and values matching the `UserContextResult`.

```python
# demo_showboat/_demo_user_ctx_state_keys.py
import tempfile, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rlm_adk.utils.user_context import load_user_context
from rlm_adk.state import (
    USER_PROVIDED_CTX,
    USER_PROVIDED_CTX_EXCEEDED,
    USR_PROVIDED_FILES_SERIALIZED,
    USR_PROVIDED_FILES_UNSERIALIZED,
    DYN_USER_CTX_MANIFEST,
)

with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, "config.yaml"), "w") as f:
        f.write("key: value\n")
    with open(os.path.join(d, "big.log"), "w") as f:
        f.write("x" * 5000)

    result = load_user_context(d, max_chars=100)

    # Simulate what the orchestrator does: build the state_delta dict
    state_delta = {
        USER_PROVIDED_CTX: result.ctx,
        USER_PROVIDED_CTX_EXCEEDED: result.exceeded,
        USR_PROVIDED_FILES_SERIALIZED: result.serialized,
        USR_PROVIDED_FILES_UNSERIALIZED: result.unserialized,
        DYN_USER_CTX_MANIFEST: result.build_manifest(),
    }

    print("State delta keys and types:")
    for k, v in state_delta.items():
        print(f"  {k:40s} -> {type(v).__name__:6s} = {repr(v)[:80]}")
    print()

    # Assertions
    assert isinstance(state_delta[USER_PROVIDED_CTX], dict)
    assert isinstance(state_delta[USER_PROVIDED_CTX_EXCEEDED], bool)
    assert isinstance(state_delta[USR_PROVIDED_FILES_SERIALIZED], list)
    assert isinstance(state_delta[USR_PROVIDED_FILES_UNSERIALIZED], list)
    assert isinstance(state_delta[DYN_USER_CTX_MANIFEST], str)

    assert state_delta[USER_PROVIDED_CTX_EXCEEDED] is True
    assert "config.yaml" in state_delta[USER_PROVIDED_CTX]
    assert "big.log" not in state_delta[USER_PROVIDED_CTX]
    assert "config.yaml" in state_delta[USR_PROVIDED_FILES_SERIALIZED]
    assert "big.log" in state_delta[USR_PROVIDED_FILES_UNSERIALIZED]
    assert "user_ctx" in state_delta[DYN_USER_CTX_MANIFEST]

    print("PASS: all 5 state keys populated with correct types and values")
```

**Expected output:**

```
State delta keys and types:
  user_provided_ctx                        -> dict   = {'config.yaml': 'key: value\n'}
  user_provided_ctx_exceeded               -> bool   = True
  usr_provided_files_serialized            -> list   = ['config.yaml']
  usr_provided_files_unserialized          -> list   = ['big.log']
  user_ctx_manifest                        -> str    = 'Pre-loaded context variable: user_ctx (di

PASS: all 5 state keys populated with correct types and values
```

## Demo 5: No Eviction (All Files Fit)

Edge case: when the budget is large enough for all files, `exceeded` is False and `unserialized` is empty.

```python
# demo_showboat/_demo_user_ctx_no_eviction.py
import tempfile, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rlm_adk.utils.user_context import load_user_context

with tempfile.TemporaryDirectory() as d:
    with open(os.path.join(d, "a.txt"), "w") as f:
        f.write("hello")
    with open(os.path.join(d, "b.py"), "w") as f:
        f.write("x = 1")

    result = load_user_context(d, max_chars=500_000)
    manifest = result.build_manifest()

    print(f"serialized:   {result.serialized}")
    print(f"unserialized: {result.unserialized}")
    print(f"exceeded:     {result.exceeded}")
    print()
    print(manifest)
    print()

    assert result.exceeded is False
    assert len(result.unserialized) == 0
    assert len(result.serialized) == 2
    assert "requires open()" not in manifest
    print("PASS: no eviction when budget is sufficient")
```

**Expected output:**

```
serialized:   ['a.txt', 'b.py']
unserialized: []
exceeded:     False

Pre-loaded context variable: user_ctx (dict)
Pre-loaded files (access via user_ctx["<filename>"]):
  - a.txt (5 chars)
  - b.py (5 chars)
Total: 2 files, 2 pre-loaded

PASS: no eviction when budget is sufficient
```

## Verification

All demos can be run from the repo root:

```bash
.venv/bin/python demo_showboat/_demo_user_ctx_basic.py
.venv/bin/python demo_showboat/_demo_user_ctx_manifest.py
.venv/bin/python demo_showboat/_demo_user_ctx_eviction.py
.venv/bin/python demo_showboat/_demo_user_ctx_state_keys.py
.venv/bin/python demo_showboat/_demo_user_ctx_no_eviction.py
```

## Files

| File | Role |
|------|------|
| `rlm_adk/utils/user_context.py` | Directory serialization utility |
| `rlm_adk/state.py` (lines 42-49) | State key constants |
| `rlm_adk/utils/prompts.py` | Static/dynamic instruction templates |
| `rlm_adk/orchestrator.py` | Env var reading and state wiring |
