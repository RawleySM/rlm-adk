"""Recursive ping -- dispatches llm_query at each layer to test thread bridge."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecursivePingResult:
    layer: int
    prompt: str
    response: str
    children: list[RecursivePingResult] = field(default_factory=list)


def run_recursive_ping(
    prompt: str,
    *,
    starting_layer: int = 0,
    max_layer: int = 2,
    llm_query_fn=None,
) -> RecursivePingResult:
    """Recursively dispatch llm_query through thread bridge layers."""
    if starting_layer >= max_layer:
        return RecursivePingResult(
            layer=starting_layer,
            prompt=prompt,
            response=f"[terminal@layer{starting_layer}] {prompt}",
        )
    if llm_query_fn is None:
        raise RuntimeError(
            "llm_query_fn not available. "
            "Call run_recursive_ping from REPL with llm_query wired, "
            "or pass llm_query_fn explicitly."
        )
    child_prompt = f"[layer{starting_layer}] {prompt}"
    child_response = llm_query_fn(child_prompt)
    return RecursivePingResult(
        layer=starting_layer,
        prompt=prompt,
        response=str(child_response),
    )
