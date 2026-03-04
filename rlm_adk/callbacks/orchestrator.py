"""Orchestrator-level test callbacks.

orchestrator_test_state_hook: Test-only before_agent_callback that writes a
    guillemet-marked dict to callback_context.state under ``cb_orchestrator_context``.
    Since before_agent_callback fires before the reasoning agent's first LLM
    call, the dict is available for ADK template resolution on ALL reasoning
    iterations (including call 0).
"""

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from rlm_adk.state import CB_ORCHESTRATOR_CONTEXT


def orchestrator_test_state_hook(
    callback_context: CallbackContext,
) -> types.Content | None:
    """Write a guillemet-marked dict to state for provider-fake verification.

    Writes ``CB_ORCHESTRATOR_CONTEXT`` to ``callback_context.state`` containing
    a structured dict with markers.  When the fixture's dynamic instruction
    includes ``{cb_orchestrator_context?}``, ADK resolves the template and the
    dict's ``str()`` repr flows into systemInstruction — verifiable in
    captured request bodies.

    Because ``before_agent_callback`` fires before the reasoning agent's
    first ``before_model_callback``, the value is in state before the first
    template resolution, so it appears in ALL reasoning calls (including call 0).
    """
    callback_context.state[CB_ORCHESTRATOR_CONTEXT] = {
        "«CB_ORCHESTRATOR_STATE_START»": True,
        "hook": "orchestrator_test_state_hook",
        "agent": "rlm_orchestrator",
        "«CB_ORCHESTRATOR_STATE_END»": True,
    }
    return None  # Proceed with agent execution
