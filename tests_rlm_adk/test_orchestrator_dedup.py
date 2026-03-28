"""Tests for orchestrator duplicate final-text suppression (Layer 1 loop guard).

The orchestrator can emit the same final answer text twice:
1. ADK's native tool loop emits Content(role="model") after set_model_response.
2. The orchestrator's post-loop logic yields its own Content(role="model").

The dedup guard tracks SHA-256 digests of model text during the reasoning
loop and suppresses the orchestrator's post-loop Content if the same text
was already emitted.
"""

from __future__ import annotations

import hashlib

from google.adk.events import Event, EventActions
from google.genai import types


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _model_content_events(events: list) -> list:
    """Extract events that carry Content(role='model') with text."""
    results = []
    for ev in events:
        c = getattr(ev, "content", None)
        if c and c.role == "model" and c.parts:
            texts = [p.text for p in c.parts if p.text]
            if texts:
                results.append(ev)
    return results


def _state_delta_events(events: list) -> list:
    """Extract events that carry EventActions with state_delta."""
    results = []
    for ev in events:
        actions = getattr(ev, "actions", None)
        if actions and getattr(actions, "state_delta", None):
            results.append(ev)
    return results


def _content_texts(events: list) -> list[str]:
    """Extract all text strings from model Content events."""
    texts = []
    for ev in _model_content_events(events):
        for p in ev.content.parts:
            if p.text:
                texts.append(p.text)
    return texts


# ---------------------------------------------------------------------------
# Digest-set unit tests (no orchestrator needed)
# ---------------------------------------------------------------------------


class TestEmittedTextDigests:
    """Verify the dedup logic at the digest-set level."""

    def test_same_text_detected_as_duplicate(self) -> None:
        digests: set[str] = set()
        text = "This is the final answer."
        digests.add(_sha256(text))
        assert _sha256(text) in digests

    def test_different_text_not_duplicate(self) -> None:
        digests: set[str] = set()
        digests.add(_sha256("Partial answer"))
        assert _sha256("Full final answer") not in digests

    def test_empty_set_allows_emission(self) -> None:
        digests: set[str] = set()
        assert _sha256("[RLM ERROR] No result") not in digests


# ---------------------------------------------------------------------------
# Orchestrator event-flow simulation tests
# ---------------------------------------------------------------------------


def _simulate_orchestrator_dedup(
    *,
    reasoning_events: list,
    final_text: str,
    is_error: bool = False,
) -> list:
    """Simulate the orchestrator's event yield logic with dedup.

    Mirrors the actual code path in _run_async_impl:
    1. Iterate reasoning events, record model text digests, yield all
    2. Compute final text from CompletionEnvelope
    3. Yield state_delta (always)
    4. Yield Content(role="model") only if text digest not already seen

    Returns the list of events the orchestrator would yield in phase 2
    (post-loop), NOT the reasoning events themselves.
    """
    _emitted_text_digests: set[str] = set()
    inv_id = "test-inv-001"
    author = "rlm_orchestrator"

    # Phase 1: simulate reasoning loop
    for event in reasoning_events:
        c = getattr(event, "content", None)
        if c and c.role == "model" and c.parts:
            for part in c.parts:
                if part.text:
                    _emitted_text_digests.add(_sha256(part.text))

    # Phase 2: simulate post-loop orchestrator logic
    post_events: list[Event] = []

    # State delta always emitted
    state_event = Event(
        invocation_id=inv_id,
        author=author,
        actions=EventActions(state_delta={"final_response_text": final_text}),
    )
    post_events.append(state_event)

    # Content event: gated by dedup
    digest = _sha256(final_text)
    if digest not in _emitted_text_digests:
        post_events.append(
            Event(
                invocation_id=inv_id,
                author=author,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=final_text)],
                ),
            )
        )

    return post_events


def _make_model_event(text: str, author: str = "reasoning_agent") -> Event:
    return Event(
        invocation_id="test-inv-001",
        author=author,
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
    )


def _make_tool_event(author: str = "reasoning_agent") -> Event:
    return Event(
        invocation_id="test-inv-001",
        author=author,
        actions=EventActions(state_delta={"some_key": "some_value"}),
    )


class TestOrchestratorDedup:
    """Test the orchestrator's dedup behavior via simulation."""

    def test_duplicate_model_content_suppressed(self) -> None:
        """When reasoning loop emitted the same text, orchestrator should
        NOT yield a second Content event with that text."""
        answer = "The answer is 42."
        reasoning_events = [_make_model_event(answer)]

        post_events = _simulate_orchestrator_dedup(
            reasoning_events=reasoning_events,
            final_text=answer,
        )

        content_events = _model_content_events(post_events)
        assert len(content_events) == 0, (
            f"Expected 0 Content events (suppressed), got {len(content_events)}"
        )

    def test_state_delta_always_emitted(self) -> None:
        """State delta events must always be yielded, even when Content
        is suppressed."""
        answer = "The answer is 42."
        reasoning_events = [_make_model_event(answer)]

        post_events = _simulate_orchestrator_dedup(
            reasoning_events=reasoning_events,
            final_text=answer,
        )

        deltas = _state_delta_events(post_events)
        assert len(deltas) == 1, f"Expected 1 state_delta event, got {len(deltas)}"

    def test_error_content_emitted_when_no_prior_model_event(self) -> None:
        """When reasoning loop emitted no model Content (e.g. tool-only),
        the error Content event should still be yielded."""
        error_msg = "[RLM ERROR] Reasoning agent completed without producing a final answer."
        reasoning_events = [_make_tool_event()]

        post_events = _simulate_orchestrator_dedup(
            reasoning_events=reasoning_events,
            final_text=error_msg,
            is_error=True,
        )

        texts = _content_texts(post_events)
        assert error_msg in texts, "Error Content event was suppressed but should have been emitted"

    def test_different_text_not_suppressed(self) -> None:
        """When reasoning loop emitted different text, orchestrator's
        Content event should still be yielded."""
        reasoning_events = [_make_model_event("Partial progress report")]

        post_events = _simulate_orchestrator_dedup(
            reasoning_events=reasoning_events,
            final_text="Full final answer with conclusions",
        )

        texts = _content_texts(post_events)
        assert "Full final answer with conclusions" in texts

    def test_error_path_suppressed_when_same_text(self) -> None:
        """Error-path Content should also be suppressed if the same text
        was already emitted in the reasoning loop."""
        error_msg = "[RLM ERROR] Something went wrong."
        reasoning_events = [_make_model_event(error_msg)]

        post_events = _simulate_orchestrator_dedup(
            reasoning_events=reasoning_events,
            final_text=error_msg,
            is_error=True,
        )

        content_events = _model_content_events(post_events)
        assert len(content_events) == 0

    def test_empty_reasoning_loop_emits_content(self) -> None:
        """When reasoning loop yielded no events at all, Content must be
        emitted."""
        post_events = _simulate_orchestrator_dedup(
            reasoning_events=[],
            final_text="Final answer from output_key fallback",
        )

        texts = _content_texts(post_events)
        assert "Final answer from output_key fallback" in texts

    def test_multiple_reasoning_model_events_all_tracked(self) -> None:
        """All model texts from reasoning loop should be recorded, and
        any matching post-loop text should be suppressed."""
        reasoning_events = [
            _make_model_event("Intermediate thought"),
            _make_model_event("The final answer"),
        ]

        post_events = _simulate_orchestrator_dedup(
            reasoning_events=reasoning_events,
            final_text="The final answer",
        )

        content_events = _model_content_events(post_events)
        assert len(content_events) == 0
