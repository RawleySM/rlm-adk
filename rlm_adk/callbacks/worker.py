"""Worker LlmAgent callbacks for sub-LM dispatch.

worker_before_model: AMEND - Injects the single prompt from the dispatch closure
    into LlmRequest. Stores prompt metrics on agent object for dispatch aggregation.

worker_after_model: OBSERVE - Extracts text response, writes to worker's output_key
    in state (for ADK persistence) and onto agent object (for dispatch closure reads).

worker_on_model_error: ERROR ISOLATION - Handles LLM errors gracefully without
    crashing ParallelAgent. Writes error result onto agent object and returns
    an LlmResponse so the agent completes normally.

worker_test_state_hook: Test-only before_model_callback that writes a
    guillemet-marked dict to callback_context.state under ``cb_worker_context``
    and appends its string repr to the pending prompt.  Compose with
    worker_before_model in provider-fake fixtures to verify the
    state-dict → worker request body path.
"""

import asyncio
import logging
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)


def _classify_error(error: Exception) -> str:
    """Classify an exception into an error category for observability."""
    import json as _json_mod

    code = getattr(error, "code", None)
    # LiteLLM exceptions use status_code (int) instead of code (str).
    # Fall back to status_code when code is missing or non-integer.
    status_code = getattr(error, "status_code", None)
    if (code is None or not isinstance(code, int)) and isinstance(status_code, int):
        code = status_code
    if isinstance(error, asyncio.TimeoutError):
        return "TIMEOUT"
    # Also detect litellm.Timeout which is not an asyncio.TimeoutError
    try:
        import litellm as _litellm_mod

        if isinstance(error, _litellm_mod.Timeout):
            return "TIMEOUT"
    except ImportError:
        pass
    if code == 429:
        return "RATE_LIMIT"
    if code in (401, 403):
        return "AUTH"
    if code and isinstance(code, int) and code >= 500:
        return "SERVER"
    if code and isinstance(code, int) and code >= 400:
        return "CLIENT"
    if isinstance(error, (ConnectionError, OSError)):
        return "NETWORK"
    # Detect JSON parse / malformed response errors
    if isinstance(error, (_json_mod.JSONDecodeError, ValueError)):
        err_msg = str(error).lower()
        if isinstance(error, _json_mod.JSONDecodeError) or "json" in err_msg:
            return "PARSE_ERROR"
    # Check error message for JSON-related patterns (e.g., wrapped exceptions)
    err_str = str(error).lower()
    if any(pat in err_str for pat in ("json", "malformed", "parse error", "decode")):
        return "PARSE_ERROR"
    return "UNKNOWN"


def worker_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Inject prompt from dispatch closure into LlmRequest.

    The dispatch closure sets worker._pending_prompt (a string) before
    running the agent.  This callback reads it and sets it as the
    LlmRequest contents.
    """
    agent = callback_context._invocation_context.agent
    pending_prompt = getattr(agent, "_pending_prompt", None)

    if pending_prompt:
        llm_request.contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=pending_prompt)],
            )
        ]

    return None  # Proceed with model call


def worker_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Extract response text, write to state output_key and agent object.

    Writes result onto the agent object (_result, _result_ready, _call_record)
    for the dispatch closure to read after ParallelAgent completes.
    Also writes to callback_context.state[output_key] for ADK persistence.

    Wrapped in try/except so a callback failure does not crash the entire
    K-worker batch via ParallelAgent (FM-20 blast radius fix).
    """
    agent = callback_context._invocation_context.agent
    try:
        response_text = ""
        if llm_response.content and llm_response.content.parts:
            response_text = "".join(
                part.text for part in llm_response.content.parts if part.text and not part.thought
            )

        # Detect safety-filtered responses (BUG-B fix)
        finish_reason = llm_response.finish_reason
        is_safety_filtered = (
            finish_reason is not None
            and hasattr(finish_reason, "name")
            and finish_reason.name == "SAFETY"
        )

        # Write result onto agent object for dispatch closure reads
        agent._result = response_text  # type: ignore[attr-defined]
        agent._result_ready = True  # type: ignore[attr-defined]
        if is_safety_filtered:
            agent._result_error = True  # type: ignore[attr-defined]

        # Extract usage from response metadata
        usage = llm_response.usage_metadata
        input_tokens = 0
        output_tokens = 0
        if usage:
            input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        # Write call record onto agent object for dispatch closure to accumulate
        record: dict[str, Any] = {
            "prompt": getattr(agent, "_pending_prompt", None),
            "response": response_text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": getattr(llm_response, "model_version", None),
            "finish_reason": finish_reason.name if finish_reason else None,
            "error": is_safety_filtered,
        }
        if is_safety_filtered:
            record["error_category"] = "SAFETY"
        agent._call_record = record  # type: ignore[attr-defined]

        # Write to the worker's output_key in state (for ADK persistence)
        output_key = getattr(agent, "output_key", None)
        if output_key:
            callback_context.state[output_key] = response_text

    except Exception as exc:
        # FM-20 fix: isolate callback failure so it doesn't crash siblings
        logger.error("worker_after_model failed for %s: %s", agent.name, exc)
        error_msg = f"[Worker {agent.name} callback error: {type(exc).__name__}: {exc}]"
        agent._result = error_msg  # type: ignore[attr-defined]
        agent._result_ready = True  # type: ignore[attr-defined]
        agent._result_error = True  # type: ignore[attr-defined]
        agent._call_record = {  # type: ignore[attr-defined]
            "prompt": getattr(agent, "_pending_prompt", None),
            "response": error_msg,
            "input_tokens": 0,
            "output_tokens": 0,
            "model": None,
            "finish_reason": None,
            "error": True,
            "error_category": "CALLBACK_ERROR",
        }

    return None


def worker_on_model_error(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
    error: Exception,
) -> LlmResponse | None:
    """Handle worker LLM errors gracefully without crashing ParallelAgent.

    Sets error result on the agent object so the dispatch closure can detect
    the failure and include the error message in the results list. Returns
    an LlmResponse so the agent completes normally within ParallelAgent.
    """
    agent = callback_context._invocation_context.agent
    error_msg = f"[Worker {agent.name} error: {type(error).__name__}: {error}]"

    agent._result = error_msg  # type: ignore[attr-defined]
    agent._result_ready = True  # type: ignore[attr-defined]
    agent._result_error = True  # type: ignore[attr-defined]

    # Write error call record onto agent object for dispatch closure
    agent._call_record = {  # type: ignore[attr-defined]
        "prompt": getattr(agent, "_pending_prompt", None),
        "response": error_msg,
        "input_tokens": 0,
        "output_tokens": 0,
        "model": None,
        "finish_reason": None,
        "error": True,
        "error_category": _classify_error(error),
        "http_status": getattr(error, "code", None),
    }

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=error_msg)],
        )
    )


# ---------------------------------------------------------------------------
# Test-only hook: state dict → worker request body verification
# ---------------------------------------------------------------------------


def worker_test_state_hook(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Write a guillemet-marked dict to state and append it to the worker prompt.

    Writes ``CB_WORKER_CONTEXT`` to ``callback_context.state`` containing a
    structured dict with markers.  Also appends the dict's ``str()`` repr to
    ``agent._pending_prompt`` so that when ``worker_before_model`` runs next
    (or this is used standalone), the dict content appears in the worker's
    ``llm_request.contents`` and thus in the captured request body.

    **Must run before** ``worker_before_model`` in the callback chain so the
    appended text is picked up when the prompt is injected into contents.

    Usage in provider-fake fixtures::

        # Chain: test hook appends to _pending_prompt, then production
        # callback injects it into llm_request.contents.
        def chained_worker_before_model(ctx, req):
            worker_test_state_hook(ctx, req)
            return worker_before_model(ctx, req)

        # Wire onto worker:
        worker.before_model_callback = chained_worker_before_model
    """
    from rlm_adk.state import CB_WORKER_CONTEXT

    agent = callback_context._invocation_context.agent
    worker_name = getattr(agent, "name", "unknown")

    context_dict = {
        "«CB_WORKER_STATE_START»": True,
        "hook": "worker_test_state_hook",
        "worker_name": worker_name,
        "«CB_WORKER_STATE_END»": True,
    }
    callback_context.state[CB_WORKER_CONTEXT] = context_dict

    # Append to pending prompt so it flows into llm_request.contents
    pending = getattr(agent, "_pending_prompt", None) or ""
    suffix = "\n\nCallback context: " + str(context_dict)
    agent._pending_prompt = pending + suffix  # type: ignore[attr-defined]

    return None
