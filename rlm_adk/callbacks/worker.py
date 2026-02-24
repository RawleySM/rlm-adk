"""Worker LlmAgent callbacks for sub-LM dispatch.

worker_before_model: AMEND - Injects the single prompt from the dispatch closure
    into LlmRequest. Stores prompt metrics on agent object for dispatch aggregation.

worker_after_model: OBSERVE - Extracts text response, writes to worker's output_key
    in state (for ADK persistence) and onto agent object (for dispatch closure reads).

worker_on_model_error: ERROR ISOLATION - Handles LLM errors gracefully without
    crashing ParallelAgent. Writes error result onto agent object and returns
    an LlmResponse so the agent completes normally.
"""

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def worker_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Inject prompt from dispatch closure into LlmRequest.

    The dispatch closure sets worker._pending_prompt before running the agent.
    This callback reads it and sets it as the LlmRequest contents.

    Stores _prompt_chars and _content_count on the agent object for
    aggregation in the dispatch closure (no state writes for accounting).
    """
    agent = callback_context._invocation_context.agent
    pending_prompt = getattr(agent, "_pending_prompt", None)

    if pending_prompt:
        if isinstance(pending_prompt, str):
            llm_request.contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=pending_prompt)],
                )
            ]
        elif isinstance(pending_prompt, list):
            # Message list format [{role: ..., content: ...}, ...]
            contents = []
            for msg in pending_prompt:
                role = msg.get("role", "user")
                adk_role = "model" if role == "assistant" else "user"
                contents.append(
                    types.Content(
                        role=adk_role,
                        parts=[types.Part.from_text(text=msg.get("content", ""))],
                    )
                )
            llm_request.contents = contents

    # --- Store prompt metrics on agent object for dispatch aggregation ---
    total_prompt_chars = sum(
        len(part.text or "")
        for content in llm_request.contents
        if content.parts
        for part in content.parts
    )
    content_count = len(llm_request.contents)

    agent._prompt_chars = total_prompt_chars  # type: ignore[attr-defined]
    agent._content_count = content_count  # type: ignore[attr-defined]

    return None  # Proceed with model call


def worker_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Extract response text, write to state output_key and agent object.

    Writes result onto the agent object (_result, _result_ready, _result_usage)
    for the dispatch closure to read after ParallelAgent completes.
    Also writes to callback_context.state[output_key] for ADK persistence.
    """
    response_text = ""
    if llm_response.content and llm_response.content.parts:
        response_text = "".join(
            part.text for part in llm_response.content.parts if part.text and not part.thought
        )

    agent = callback_context._invocation_context.agent

    # Write result onto agent object for dispatch closure reads
    agent._result = response_text  # type: ignore[attr-defined]
    agent._result_ready = True  # type: ignore[attr-defined]

    # Extract usage from response metadata onto agent object
    usage = llm_response.usage_metadata
    if usage:
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        agent._result_usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}  # type: ignore[attr-defined]
    else:
        agent._result_usage = {"input_tokens": 0, "output_tokens": 0}  # type: ignore[attr-defined]

    # Write to the worker's output_key in state (for ADK persistence)
    output_key = getattr(agent, "output_key", None)
    if output_key:
        callback_context.state[output_key] = response_text

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
    agent._result_usage = {"input_tokens": 0, "output_tokens": 0}  # type: ignore[attr-defined]

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=error_msg)],
        )
    )
