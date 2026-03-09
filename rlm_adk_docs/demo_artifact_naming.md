# Artifact Filename Disambiguation: depth + fanout_idx

*2026-03-09T18:20:40Z by Showboat 0.6.0*
<!-- showboat-id: f167ce27-2e3e-4c07-baf5-d9f1f50f47fc -->

## The Problem

When child orchestrators run at depth > 0, all artifact filenames collide with the parent and with each other:

- Parent at depth=0, iteration=1: `repl_code_iter_1_turn_0.py`
- Child at depth=1, iteration=1: `repl_code_iter_1_turn_0.py` (COLLISION)
- 3 batched children at depth=1: ALL produce `repl_code_iter_1_turn_0.py` (TOCTOU race, data loss)

## The Solution

Add `d{depth}_f{fanout_idx}` prefix to all artifact filenames:

| Old name | New name |
|----------|----------|
| `repl_code_iter_1_turn_0.py` | `repl_code_d0_f0_iter_1_turn_0.py` |
| `repl_output_iter_1.txt` | `repl_output_d0_f0_iter_1.txt` |
| `repl_trace_iter_1_turn_0.json` | `repl_trace_d0_f0_iter_1_turn_0.json` |
| `final_answer.md` | `final_answer_d0_f0.md` |

Root orchestrator uses `d0_f0`. Child at depth=1, fanout_idx=2 uses `d1_f2`.

## Data Flow: dispatch -> child orchestrator -> artifact

```
dispatch.py::_run_child(prompt, model, output_schema, fanout_idx=2)
  -> agent.py::create_child_orchestrator(depth=1, fanout_idx=2)
       -> RLMOrchestratorAgent(depth=1, fanout_idx=2)
            -> REPLTool(depth=1, fanout_idx=2)
                 -> save_repl_code(..., depth=1, fanout_idx=2)
                      -> filename = 'repl_code_d1_f2_iter_1_turn_0.py'
            -> save_final_answer(..., depth=1, fanout_idx=2)
                 -> filename = 'final_answer_d1_f2.md'
```

## Proof: artifact filename generation

```bash
.venv/bin/python3 -c "
import sys, os
sys.path.insert(0, os.getcwd())

from rlm_adk.artifacts import save_repl_code, save_repl_output, save_repl_trace, save_final_answer
import inspect

for fn_name, fn in [('save_repl_code', save_repl_code), ('save_repl_output', save_repl_output),
                     ('save_repl_trace', save_repl_trace), ('save_final_answer', save_final_answer)]:
    src = inspect.getsource(fn)
    for line in src.splitlines():
        if 'filename = f' in line:
            print(f'{fn_name}: {line.strip()}')
            break
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
save_repl_code: filename = f"repl_code_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.py"
save_repl_output: filename = f"repl_output_d{depth}_f{fanout_idx}_iter_{iteration}.txt"
save_repl_trace: filename = f"repl_trace_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.json"
save_final_answer: filename = f"final_answer_d{depth}_f{fanout_idx}.md"
```

## Proof: collision prevention between parent and 3 batched children

```bash
.venv/bin/python3 -c "
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Simulate artifact filename generation for parent + 3 batched children
def make_ctx():
    ctx = MagicMock()
    ctx.artifact_service = AsyncMock()
    ctx.artifact_service.save_artifact = AsyncMock(return_value=0)
    ctx.app_name = 'test'
    ctx.session.user_id = 'user'
    ctx.session.id = 'sess'
    ctx.session.state = {}
    return ctx

from rlm_adk.artifacts import save_repl_code

async def demo():
    filenames = []

    # Parent at depth=0
    ctx = make_ctx()
    await save_repl_code(ctx, iteration=1, turn=0, code='parent_code', depth=0, fanout_idx=0)
    fn = ctx.artifact_service.save_artifact.call_args.kwargs['filename']
    filenames.append(('parent  d=0 f=0', fn))

    # 3 batched children at depth=1
    for fi in range(3):
        ctx = make_ctx()
        await save_repl_code(ctx, iteration=1, turn=0, code='child_code', depth=1, fanout_idx=fi)
        fn = ctx.artifact_service.save_artifact.call_args.kwargs['filename']
        filenames.append((f'child   d=1 f={fi}', fn))

    print('Agent                  Artifact filename')
    print('-' * 60)
    for label, fn in filenames:
        print(f'{label}       {fn}')

    unique = set(fn for _, fn in filenames)
    print(f'\nTotal filenames: {len(filenames)}, Unique: {len(unique)}')
    print('All unique: ' + ('YES' if len(unique) == len(filenames) else 'NO -- COLLISION'))

asyncio.run(demo())
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
Agent                  Artifact filename
------------------------------------------------------------
parent  d=0 f=0       repl_code_d0_f0_iter_1_turn_0.py
child   d=1 f=0       repl_code_d1_f0_iter_1_turn_0.py
child   d=1 f=1       repl_code_d1_f1_iter_1_turn_0.py
child   d=1 f=2       repl_code_d1_f2_iter_1_turn_0.py

Total filenames: 4, Unique: 4
All unique: YES
```

## Proof: REPLTool threads fanout_idx to save_repl_code

```bash
.venv/bin/python3 -c "
import asyncio
from unittest.mock import AsyncMock, MagicMock

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.tools.repl_tool import REPLTool

def make_tool_context():
    # MagicMock without spec -- isinstance(ctx, CallbackContext) returns False
    # so get_invocation_context returns ctx directly as an InvocationContext
    ctx = MagicMock()
    ctx.state = {}
    ctx.artifact_service = AsyncMock()
    ctx.artifact_service.save_artifact = AsyncMock(return_value=0)
    ctx.app_name = 'test'
    ctx.session.user_id = 'user'
    ctx.session.id = 'sess'
    ctx.session.state = {}
    return ctx

async def demo():
    # REPLTool at depth=1, fanout_idx=2
    repl = LocalREPL()
    tool = REPLTool(repl=repl, depth=1, fanout_idx=2)
    tc = make_tool_context()
    try:
        await tool.run_async(args={'code': 'x = 42'}, tool_context=tc)
    finally:
        repl.cleanup()

    fn = tc.artifact_service.save_artifact.call_args.kwargs['filename']
    print(f'REPLTool(depth=1, fanout_idx=2) -> artifact: {fn}')

    # REPLTool at root (depth=0, fanout_idx=0)
    repl2 = LocalREPL()
    tool2 = REPLTool(repl=repl2, depth=0, fanout_idx=0)
    tc2 = make_tool_context()
    try:
        await tool2.run_async(args={'code': 'y = 99'}, tool_context=tc2)
    finally:
        repl2.cleanup()

    fn2 = tc2.artifact_service.save_artifact.call_args.kwargs['filename']
    print(f'REPLTool(depth=0, fanout_idx=0) -> artifact: {fn2}')

asyncio.run(demo())
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
REPLTool(depth=1, fanout_idx=2) -> artifact: repl_code_d1_f2_iter_1_turn_0.py
REPLTool(depth=0, fanout_idx=0) -> artifact: repl_code_d0_f0_iter_1_turn_0.py
```

## Key code changes

### artifacts.py -- all 4 helpers gain depth + fanout_idx params

Each filename format string now includes the `d{depth}_f{fanout_idx}` prefix:

```python
# save_repl_code (line 141)
filename = f"repl_code_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.py"

# save_repl_output (line 95)
filename = f"repl_output_d{depth}_f{fanout_idx}_iter_{iteration}.txt"

# save_repl_trace (line 185)
filename = f"repl_trace_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.json"

# save_final_answer (line 273)
filename = f"final_answer_d{depth}_f{fanout_idx}.md"
```

### repl_tool.py -- REPLTool.__init__ accepts fanout_idx

```python
def __init__(self, repl, *, ..., depth=0, fanout_idx=0, ...):
    self._fanout_idx = fanout_idx
```

Threaded to save_repl_code:

```python
await save_repl_code(tool_context, ..., depth=self._depth, fanout_idx=self._fanout_idx)
```

### orchestrator.py -- fanout_idx Pydantic field

```python
class RLMOrchestratorAgent(BaseAgent):
    fanout_idx: int = 0  # Proper Pydantic field
```

Threaded to REPLTool and save_final_answer.

### agent.py -- create_child_orchestrator accepts fanout_idx

```python
def create_child_orchestrator(..., fanout_idx=0):
    return RLMOrchestratorAgent(..., fanout_idx=fanout_idx, ...)
```

### dispatch.py -- _run_child threads fanout_idx

```python
child = create_child_orchestrator(..., fanout_idx=fanout_idx)
```

The `fanout_idx` parameter already existed in `_run_child`'s signature (used for obs summaries). Now it also flows to the child orchestrator for artifact disambiguation.

## Test coverage

14 tests in `tests_rlm_adk/test_artifact_naming.py` (all marked `@pytest.mark.unit_nondefault`):

| Test class | Tests | Verifies |
|------------|-------|----------|
| TestSaveReplCodeNaming | 3 | d0_f0 default, d1_f2 child, d2_f0 deep nesting |
| TestSaveReplOutputNaming | 2 | d0_f0 default, d1_f3 child |
| TestSaveReplTraceNaming | 2 | d0_f0 default, d2_f1 child |
| TestSaveFinalAnswerNaming | 2 | d0_f0 default, d1_f4 child |
| TestREPLToolArtifactNaming | 3 | REPLTool threads depth+fanout_idx to save_repl_code |
| TestCollisionPrevention | 2 | 3 siblings produce unique filenames; parent vs child distinct |
