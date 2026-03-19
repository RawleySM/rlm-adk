"""Reasoning Agent callbacks.

before_model_callback: Merges the ADK-resolved dynamic instruction into
    system_instruction (from static_instruction).  Records per-invocation
    token accounting.  ADK manages contents (tool call/response history)
    via include_contents='default'.

after_model_callback: Records per-invocation token accounting from
    usage_metadata.  The collapsed orchestrator reads the final answer
    from the output_key ("reasoning_output").

reasoning_test_state_hook: Test-only before_model_callback that writes a
    guillemet-marked dict to callback_context.state under the key
    ``cb_reasoning_context``.  Compose with reasoning_before_model in
    provider-fake fixtures to verify the state → systemInstruction path.
"""

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.state import (
    CB_REASONING_CONTEXT,
    CB_TOOL_CONTEXT,
    ITERATION_COUNT,
)
from rlm_adk.types import LineageEnvelope


def _extract_system_instruction_text(llm_request: LlmRequest) -> str:
    """Extract system_instruction text that ADK set from static_instruction."""
    if not llm_request.config or not llm_request.config.system_instruction:
        return ""
    si = llm_request.config.system_instruction
    if isinstance(si, str):
        return si
    # system_instruction may be a Content object with parts
    if isinstance(si, types.Content) and si.parts:
        return "".join(
            p.text for p in si.parts
            if isinstance(p, types.Part) and p.text
        )
    return str(si)


def _extract_adk_dynamic_instruction(llm_request: LlmRequest) -> str:
    """Extract the resolved instruction template that ADK placed in contents.

    When both static_instruction and instruction are set, ADK resolves the
    instruction template and appends it to contents as a user Content.
    We extract and remove it so it can be relocated to system_instruction.
    """
    dynamic_text = ""
    if llm_request.contents:
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text:
                        dynamic_text += part.text
    return dynamic_text.strip()


def _extract_response_text(llm_response: LlmResponse) -> tuple[str, str]:
    """Split visible output text from hidden thought text."""
    output_parts: list[str] = []
    thought_parts: list[str] = []
    if llm_response.content and llm_response.content.parts:
        for part in llm_response.content.parts:
            if not isinstance(part, types.Part) or not part.text:
                continue
            if getattr(part, "thought", False):
                thought_parts.append(part.text)
            else:
                output_parts.append(part.text)
    return "".join(output_parts), "".join(thought_parts)


def _usage_int(usage: Any, attr: str) -> int:
    """Return an integer usage field, guarding against MagicMock values in tests."""
    value = getattr(usage, attr, 0)
    return value if isinstance(value, int) else 0


def _agent_runtime(callback_context):
    """Extract invocation context and agent.

    Note: inv.branch and inv.invocation_id are private ADK attributes.
    """
    inv = callback_context._invocation_context
    agent = inv.agent
    return inv, agent


def _build_lineage(callback_context) -> LineageEnvelope:
    """Build a LineageEnvelope from agent runtime attrs."""
    inv, agent = _agent_runtime(callback_context)
    return LineageEnvelope(
        agent_name=getattr(agent, "name", "unknown"),
        depth=getattr(agent, "_rlm_depth", 0),
        fanout_idx=getattr(agent, "_rlm_fanout_idx", None),
        parent_depth=getattr(agent, "_rlm_parent_depth", None),
        parent_fanout_idx=getattr(agent, "_rlm_parent_fanout_idx", None),
        branch=getattr(inv, "branch", None),
        invocation_id=getattr(inv, "invocation_id", None),
        session_id=getattr(getattr(inv, "session", None), "id", None),
        output_schema_name=getattr(agent, "_rlm_output_schema_name", None),
    )


def reasoning_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Merge dynamic instruction into system_instruction.

    ADK has already set:
      - system_instruction from static_instruction (the stable system prompt)
      - resolved instruction template in contents (dynamic context metadata)

    This callback:
      1. Preserves system_instruction from static_instruction
      2. Extracts the resolved dynamic instruction from contents
      3. Appends the dynamic metadata to system_instruction
      4. Leaves contents as ADK manages them (include_contents='default')
      5. Records per-invocation token accounting
    """
    # --- Extract what ADK set ---
    static_si = _extract_system_instruction_text(llm_request)
    dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)

    # --- Build system_instruction: static prompt + dynamic metadata ---
    system_instruction_text = static_si
    if dynamic_instruction:
        if system_instruction_text:
            system_instruction_text += "\n\n" + dynamic_instruction
        else:
            system_instruction_text = dynamic_instruction

    # ADK manages contents via include_contents='default'
    contents = llm_request.contents or []

    if system_instruction_text:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.system_instruction = system_instruction_text

    # --- Per-invocation token accounting (agent-local) ---
    total_prompt_chars = sum(
        len(part.text or "")
        for content in contents
        if content.parts
        for part in content.parts
    )
    system_chars = len(system_instruction_text)
    content_count = len(contents)

    # Store request metadata on the agent instead of session state.
    # ObservabilityPlugin reads _rlm_pending_request_meta from the agent.
    inv, agent = _agent_runtime(callback_context)
    request_meta = {
        "prompt_chars": total_prompt_chars,
        "system_chars": system_chars,
        "content_count": content_count,
        "lineage": _build_lineage(callback_context).model_dump(),
    }
    object.__setattr__(agent, "_rlm_pending_request_meta", request_meta)

    return None


def reasoning_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Record per-invocation token accounting from usage_metadata.

    Stores response metadata on the agent as ``_rlm_last_response_meta``
    and injects lineage into ``llm_response.custom_metadata``.  The
    collapsed orchestrator reads the final answer from the output_key
    ("reasoning_output") and token data from the agent attr.
    """
    # --- Per-invocation token accounting from usage_metadata ---
    usage = llm_response.usage_metadata
    visible_text, thought_text = _extract_response_text(llm_response)
    finish_reason = getattr(getattr(llm_response, "finish_reason", None), "name", None)

    if usage:
        input_tokens = _usage_int(usage, "prompt_token_count")
        output_tokens = _usage_int(usage, "candidates_token_count")
        thought_tokens = _usage_int(usage, "thoughts_token_count")
    else:
        input_tokens = 0
        output_tokens = 0
        thought_tokens = 0

    # Parse reasoning_summary from JSON-shaped visible text
    reasoning_summary = ""
    if visible_text.lstrip().startswith("{"):
        try:
            import json

            parsed = json.loads(visible_text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            reasoning_summary = parsed.get("reasoning_summary", "") or ""

    # --- Store on agent-local metadata (not session state) ---
    inv, agent = _agent_runtime(callback_context)
    lineage = _build_lineage(callback_context)

    # Inject lineage into llm_response.custom_metadata
    meta = dict(llm_response.custom_metadata or {})
    meta["rlm"] = lineage.model_dump()
    llm_response.custom_metadata = meta

    response_meta = {
        "visible_text": visible_text,
        "thought_text": thought_text,
        "finish_reason": finish_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thought_tokens": thought_tokens,
        "reasoning_summary": reasoning_summary,
        "custom_metadata": meta,
    }
    object.__setattr__(agent, "_rlm_last_response_meta", response_meta)

    # Return None -- observe only, don't alter the response
    return None


# ---------------------------------------------------------------------------
# Test-only hook: state dict → systemInstruction verification
# ---------------------------------------------------------------------------


def reasoning_test_state_hook(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Write a guillemet-marked dict to state for provider-fake verification.

    Writes ``CB_REASONING_CONTEXT`` to ``callback_context.state`` containing
    a structured dict with markers.  When the fixture's dynamic instruction
    includes ``{cb_reasoning_context?}``, ADK resolves the template and the
    dict's ``str()`` repr flows into systemInstruction — verifiable in
    captured request bodies.

    Compose with the production callback by setting both as a chain::

        # In contract_runner or test setup:
        agent.before_model_callback = reasoning_test_state_hook
        # Then call reasoning_before_model manually, or chain them.

    Or use as a standalone before_model_callback for isolated testing.
    """
    iteration = callback_context.state.get(ITERATION_COUNT, 0)
    context_dict = {
        "«CB_REASONING_STATE_START»": True,
        "hook": "reasoning_test_state_hook",
        "iteration": iteration,
        "agent": "reasoning_agent",
        "«CB_REASONING_STATE_END»": True,
    }
    callback_context.state[CB_REASONING_CONTEXT] = context_dict

    # Patch the already-resolved template text in contents so the dict
    # appears on the FIRST iteration too (ADK resolves {cb_reasoning_context?}
    # before before_model_callback fires, so iter 0 would otherwise be empty).
    # reasoning_before_model runs next and extracts all content text into
    # systemInstruction, so this patch flows through automatically.
    dict_str = str(context_dict)
    placeholder = "Callback state: \n"
    if llm_request.contents:
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text and placeholder in part.text:
                        part.text = part.text.replace(
                            placeholder, f"Callback state: {dict_str}\n", 1,
                        )
    return None


# ---------------------------------------------------------------------------
# Test-only hook: tool state dict → systemInstruction verification
# ---------------------------------------------------------------------------


def tool_test_state_hook(
    tool: Any, args: dict, tool_context: Any,
) -> dict | None:
    """Write a guillemet-marked dict to state before each REPL tool execution.

    Writes ``CB_TOOL_CONTEXT`` to ``tool_context.state`` containing a
    structured dict with markers.  When the fixture's dynamic instruction
    includes ``{cb_tool_context?}``, ADK resolves the template on the *next*
    reasoning LLM call and the dict's ``str()`` repr flows into
    systemInstruction — verifiable in captured request bodies.

    The dict is available starting from the reasoning call *after* the first
    tool execution (call 2 in the comprehensive fixture, since call 0 has no
    prior tool execution).

    Wire on the reasoning agent as ``before_tool_callback``::

        object.__setattr__(reasoning_agent, "before_tool_callback", tool_test_state_hook)
    """
    tool_name = getattr(tool, "name", "unknown")
    tool_context.state[CB_TOOL_CONTEXT] = {
        "«CB_TOOL_STATE_START»": True,
        "hook": "tool_test_state_hook",
        "tool_name": tool_name,
        "args_keys": sorted(args.keys()) if args else [],
        "«CB_TOOL_STATE_END»": True,
    }
    return None  # Proceed with normal tool execution
