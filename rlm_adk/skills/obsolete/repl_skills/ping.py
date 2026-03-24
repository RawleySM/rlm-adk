"""Expandable REPL skill: recursive ping.

Registers source-expandable exports at import time so
``from rlm_repl_skills.ping import run_recursive_ping`` expands into
inline source before the AST rewriter runs.
"""

from __future__ import annotations

from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PING_TERMINAL_PAYLOAD_SRC = (
    'PING_TERMINAL_PAYLOAD = {"my_response": "pong", "your_response": "ping"}'
)

_PING_REASONING_LAYER_1_SRC = (
    "PING_REASONING_LAYER_1 = (\n"
    '    "You are recursion layer 1. "\n'
    '    "Dispatch a layer-2 child via llm_query and forward its response unchanged."\n'
    ")"
)

_PING_REASONING_LAYER_2_SRC = (
    "PING_REASONING_LAYER_2 = (\n"
    '    "You are recursion layer 2 (terminal). "\n'
    '    "Return the terminal JSON payload unchanged."\n'
    ")"
)

_RECURSIVE_PING_RESULT_SRC = """\
class RecursivePingResult:
    def __init__(self, layer: int, payload: dict, child_response: str, debug_log: list):
        self.layer = layer
        self.payload = payload
        self.child_response = child_response
        self.debug_log = debug_log

    def __repr__(self):
        return (
            f"RecursivePingResult(layer={self.layer}, "
            f"payload={self.payload}, "
            f"child_response={self.child_response!r:.80}, "
            f"debug_log_len={len(self.debug_log)})"
        )\
"""

_BUILD_RECURSIVE_PING_PROMPT_SRC = """\
def build_recursive_ping_prompt(
    current_layer,
    max_layer,
    terminal_payload,
    layer1_reasoning_summary,
    layer2_reasoning_summary,
):
    import json
    if current_layer >= max_layer:
        return (
            f"You are recursion layer {current_layer} (terminal). "
            f"{layer2_reasoning_summary} "
            f"Return ONLY this exact JSON: {json.dumps(terminal_payload)}"
        )
    return (
        f"You are recursion layer {current_layer}. "
        f"{layer1_reasoning_summary} "
        f"Dispatch a child at layer {current_layer + 1} via llm_query "
        f"and forward its response unchanged."
    )\
"""

_RUN_RECURSIVE_PING_SRC = """\
def run_recursive_ping(
    max_layer=2,
    starting_layer=0,
    terminal_layer=2,
    emit_debug=True,
    terminal_payload=None,
    layer1_reasoning_summary=None,
    layer2_reasoning_summary=None,
):
    import json

    if terminal_payload is None:
        terminal_payload = PING_TERMINAL_PAYLOAD
    if layer1_reasoning_summary is None:
        layer1_reasoning_summary = PING_REASONING_LAYER_1
    if layer2_reasoning_summary is None:
        layer2_reasoning_summary = PING_REASONING_LAYER_2

    debug_log = []

    def _log(msg):
        if emit_debug:
            print(msg)
        debug_log.append(msg)

    _log(f"[ping] starting recursive ping: layer={starting_layer}, max={max_layer}")

    if starting_layer >= terminal_layer:
        _log(f"[ping] layer {starting_layer} is terminal, returning payload directly")
        payload_json = json.dumps(terminal_payload)
        _log(f"[ping] terminal payload: {payload_json}")
        return RecursivePingResult(
            layer=starting_layer,
            payload=terminal_payload,
            child_response=payload_json,
            debug_log=debug_log,
        )

    prompt = build_recursive_ping_prompt(
        current_layer=starting_layer + 1,
        max_layer=max_layer,
        terminal_payload=terminal_payload,
        layer1_reasoning_summary=layer1_reasoning_summary,
        layer2_reasoning_summary=layer2_reasoning_summary,
    )
    _log(f"[ping] layer {starting_layer} dispatching child at layer {starting_layer + 1}")
    _log(f"[ping] prompt: {prompt[:120]}...")

    child_response = llm_query(prompt)

    _log(f"[ping] layer {starting_layer} received child response: {str(child_response)[:200]}")

    try:
        payload = json.loads(str(child_response))
    except (json.JSONDecodeError, ValueError):
        payload = {"raw_response": str(child_response)}
        _log(f"[ping] layer {starting_layer} could not parse child response as JSON")

    _log(f"[ping] layer {starting_layer} returning result")

    return RecursivePingResult(
        layer=starting_layer,
        payload=payload,
        child_response=str(child_response),
        debug_log=debug_log,
    )\
"""

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.ping",
        name="PING_TERMINAL_PAYLOAD",
        source=_PING_TERMINAL_PAYLOAD_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.ping",
        name="PING_REASONING_LAYER_1",
        source=_PING_REASONING_LAYER_1_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.ping",
        name="PING_REASONING_LAYER_2",
        source=_PING_REASONING_LAYER_2_SRC,
        requires=[],
        kind="const",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.ping",
        name="RecursivePingResult",
        source=_RECURSIVE_PING_RESULT_SRC,
        requires=[],
        kind="class",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.ping",
        name="build_recursive_ping_prompt",
        source=_BUILD_RECURSIVE_PING_PROMPT_SRC,
        requires=["PING_REASONING_LAYER_1", "PING_REASONING_LAYER_2", "PING_TERMINAL_PAYLOAD"],
        kind="function",
    )
)

register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.ping",
        name="run_recursive_ping",
        source=_RUN_RECURSIVE_PING_SRC,
        requires=[
            "RecursivePingResult",
            "build_recursive_ping_prompt",
            "PING_TERMINAL_PAYLOAD",
            "PING_REASONING_LAYER_1",
            "PING_REASONING_LAYER_2",
        ],
        kind="function",
    )
)
