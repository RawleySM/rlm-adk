---
name: recursive-ping
display_name: Recursive Ping
description: A diagnostic skill that tests recursive LLM dispatch through the thread bridge.
---

## Instructions

Use `run_recursive_ping(prompt, starting_layer=0, max_layer=2)` to test recursive dispatch.
The function calls `llm_query()` at each layer until reaching `max_layer`.
Returns a `RecursivePingResult` with the response chain.
