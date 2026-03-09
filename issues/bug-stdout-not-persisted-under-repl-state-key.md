# Bug: REPL `stdout` is not persisted under any state key

## Summary
REPL `stdout` is captured in tool telemetry, but there is no explicit state key that persists the REPL output itself. `last_repl_result` only stores booleans and summary metadata.

## Location
- [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L117)
- [state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L19)
- [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L968)

## Expected
REPL output should be persisted under an explicit state key, or at minimum a bounded preview key, so state-based introspection can answer:
- what code was run
- what it printed

## Actual
`stdout` is visible only through tool telemetry fields such as:
- `result_preview`
- `repl_stdout_len`

There is no dedicated REPL output state key in final session state or `session_state_events`.

## Evidence
From rerunning [fake_recursive_ping.json](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json):

Tool telemetry captured output lengths:
- root `execute_code`: `repl_stdout_len=58`
- layer 1 `execute_code`: `repl_stdout_len=58`
- layer 2 `execute_code`: `repl_stdout_len=67`

Example tool result preview at layer 2 included actual output:
```text
{'stdout': "recursion_layer=2\n{'my_response': 'pong', 'your_response': 'ping'}\n", ...}
```

But final state only included:
- `last_repl_result`
- `repl_submitted_code*`

And `last_repl_result` only contained:
- `has_output`
- `has_errors`
- `total_llm_calls`
- submitted-code metadata
- optional `trace_summary`

No raw `stdout` or preview field was persisted.

## Root Cause
`REPLTool._build_last_repl_result()` builds a summary object and omits `stdout` entirely. See [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L117).

## Impact
This creates an observability split:
- telemetry can say output existed and how large it was
- state cannot tell what the REPL actually printed

That makes state-based debugging weaker, especially for:
- replay validation
- session-state inspection
- artifact-free debugging paths
- checking recursive layer markers printed by code

## Reproduction
1. Run the fixture with SQLite tracing enabled.
2. Observe `repl_stdout_len > 0` in telemetry rows for `execute_code`.
3. Inspect final state and `session_state_events`.
4. Observe no explicit REPL output key.

## Proposed Fix
Add one or both of these state keys:
- `repl_stdout`
- `repl_stdout_preview`

A bounded preview is likely the safer default if full output volume is a concern.
