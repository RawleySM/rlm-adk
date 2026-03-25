"""Build a linearized flow transcript from the recursive invocation tree."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from rlm_adk.dashboard.flow_models import (
    FlowAgentCard,
    FlowArrow,
    FlowBlock,
    FlowChildCard,
    FlowCodeCell,
    FlowInspectorData,
    FlowOutputCell,
    FlowToolCallCell,
    FlowTranscript,
    LlmQueryLineInfo,
)

if TYPE_CHECKING:
    from rlm_adk.dashboard.live_models import LiveInvocationNode


def find_llm_query_lines(code: str) -> list[tuple[int, str, str | None]]:
    """Find ``llm_query`` / ``llm_query_batched`` call sites via AST.

    Returns a sorted list of ``(line_number, function_name, schema_name_or_none)``.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    _TARGET_NAMES = {"llm_query", "llm_query_batched"}
    results: list[tuple[int, str, str | None]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        func_name: str | None = None
        if isinstance(func, ast.Name) and func.id in _TARGET_NAMES:
            func_name = func.id
        elif isinstance(func, ast.Attribute) and func.attr in _TARGET_NAMES:
            func_name = func.attr
        if func_name is None:
            continue

        schema_name: str | None = None
        for kw in node.keywords:
            if kw.arg == "output_schema" and isinstance(kw.value, ast.Name):
                schema_name = kw.value.id
        results.append((node.lineno, func_name, schema_name))

    return sorted(results, key=lambda x: x[0])


def build_flow_transcript(
    nodes: list[LiveInvocationNode],
) -> FlowTranscript:
    """Linearize the invocation tree into a flat flow transcript."""
    blocks: list[FlowBlock] = []
    inspector: FlowInspectorData | None = None

    for node in nodes:
        node_blocks, node_inspector = _process_node(node)
        blocks.extend(node_blocks)
        if inspector is None and node_inspector is not None:
            inspector = node_inspector

    return FlowTranscript(blocks=blocks, inspector=inspector)


def _process_node(
    node: LiveInvocationNode,
) -> tuple[list[FlowBlock], FlowInspectorData | None]:
    """Process a single invocation node into flow blocks.

    Renders ALL available iterations sequentially (notebook style) so the
    user sees every reasoning turn's code cell and stdout appended in order.
    """
    blocks: list[FlowBlock] = []
    available_ids = [(avail.iteration, avail.invocation_id) for avail in node.available_invocations]

    for inv in node.available_invocations:
        is_selected = inv.invocation_id == node.invocation.invocation_id

        # 1. Agent card — use per-invocation context items when available.
        inv_context = node.context_items_by_invocation.get(
            inv.invocation_id,
            list(node.context_items) if is_selected else [],
        )
        agent_card = FlowAgentCard(
            pane_id=node.pane_id,
            invocation_id=inv.invocation_id,
            agent_name=inv.agent_name,
            depth=inv.depth,
            fanout_idx=inv.fanout_idx,
            status=inv.status,
            iteration=inv.iteration,
            available_iteration_ids=available_ids,
            input_tokens=inv.input_tokens,
            output_tokens=inv.output_tokens,
            thought_tokens=inv.thought_tokens,
            total_context_tokens=(
                node.invocation_context_tokens
                if is_selected
                else int(inv.raw_payload.get("total_request_tokens") or 0)
            ),
            model=inv.model,
            context_items=inv_context,
            state_items=list(inv.state_items),
            request_chunks=list(inv.request_chunks),
            model_events=list(inv.model_events),
        )
        blocks.append(agent_card)

        # 2. Code cell (if REPL code exists)
        code = inv.repl_submission or ""
        if code.strip():
            parse_source = code
            raw_lines = find_llm_query_lines(parse_source)

            # Match llm_query lines to child summaries by source order
            children = list(inv.child_summaries)
            llm_line_infos: list[LlmQueryLineInfo] = []
            for idx, (lineno, func_name, schema) in enumerate(raw_lines):
                child = children[idx] if idx < len(children) else None
                child_pane_id = (
                    _find_child_pane_id(node, child.depth, child.fanout_idx) if child else None
                )
                info = LlmQueryLineInfo(
                    line_number=lineno,
                    function_name=func_name,
                    schema_name=schema,
                    child_depth=child.depth if child else None,
                    child_fanout_idx=child.fanout_idx if child else None,
                    child_status=child.status if child else None,
                    child_prompt_preview=child.prompt_preview[:100] if child else "",
                    child_result_preview=(child.visible_output_preview[:100] if child else ""),
                    child_pane_id=child_pane_id,
                )
                llm_line_infos.append(info)

            blocks.append(
                FlowArrow(direction="down", arrow_kind="execute_code", label="execute_code")
            )
            blocks.append(
                FlowCodeCell(
                    code=code,
                    llm_query_lines=llm_line_infos,
                    pane_id=node.pane_id,
                    invocation_id=inv.invocation_id,
                )
            )

            # 3. Child cards for each dispatched child
            for child in children:
                child_pane_id = _find_child_pane_id(node, child.depth, child.fanout_idx)
                blocks.append(
                    FlowArrow(
                        direction="right",
                        arrow_kind="llm_query",
                        label=f"d{child.depth}:f{child.fanout_idx}",
                    )
                )
                blocks.append(
                    FlowChildCard(
                        depth=child.depth,
                        fanout_idx=child.fanout_idx,
                        status=child.status,
                        error=child.error,
                        error_message=child.error_message,
                        prompt_preview=child.prompt_preview[:120],
                        result_preview=child.result_text[:120] if child.result_text else "",
                        visible_output_preview=child.visible_output_preview[:120],
                        input_tokens=child.input_tokens,
                        output_tokens=child.output_tokens,
                        thought_tokens=child.thought_tokens,
                        elapsed_ms=child.elapsed_ms,
                        finish_reason=child.finish_reason,
                        model=child.model,
                        pane_id=child_pane_id,
                        structured_output=child.structured_output,
                    )
                )
                result_kind: str = "return_value" if not child.error else "set_model_response"
                blocks.append(
                    FlowArrow(
                        direction="left",
                        arrow_kind=result_kind,  # type: ignore[arg-type]
                        label="set_model_response" if not child.error else "error",
                    )
                )

            # 4. Output cell
            child_return_cards = [
                FlowChildCard(
                    depth=c.depth,
                    fanout_idx=c.fanout_idx,
                    status=c.status,
                    error=c.error,
                    result_preview=c.visible_output_preview[:120],
                    input_tokens=c.input_tokens,
                    output_tokens=c.output_tokens,
                )
                for c in children
            ]
            blocks.append(
                FlowOutputCell(
                    stdout=inv.repl_stdout,
                    stderr=inv.repl_stderr,
                    child_returns=child_return_cards,
                    has_errors=bool(inv.repl_stderr.strip()),
                    pane_id=node.pane_id,
                    invocation_id=inv.invocation_id,
                )
            )

        # 5. Non-execute_code tool calls (set_model_response, load_skill, list_skills)
        _TOOL_CALL_TOOLS = {"set_model_response", "load_skill", "list_skills"}
        for tool_event in inv.tool_events:
            if tool_event.tool_name not in _TOOL_CALL_TOOLS:
                continue
            blocks.append(
                FlowArrow(
                    direction="down",
                    arrow_kind=tool_event.tool_name,  # type: ignore[arg-type]
                    label=tool_event.tool_name,
                )
            )
            blocks.append(
                FlowToolCallCell(
                    tool_name=tool_event.tool_name,
                    tool_args=tool_event.tool_args or {},
                    tool_result=tool_event.payload or {},
                    result_text=tool_event.result_preview,
                    pane_id=node.pane_id,
                    invocation_id=inv.invocation_id,
                )
            )

    # Build inspector data from the selected (active) invocation
    sel = node.invocation
    inspector = FlowInspectorData(
        state_items=list(sel.state_items),
        skills=[],
        return_value_json=None,
        selected_pane_id=node.pane_id,
        context_items=list(node.context_items),
    )

    # Child nodes are accessed via drill-down (child window route),
    # not inlined in the main transcript.

    return blocks, inspector


def _find_child_pane_id(
    node: LiveInvocationNode,
    child_depth: int,
    child_fanout_idx: int,
) -> str | None:
    """Look up the pane_id for a child by depth/fanout in child_nodes."""
    for child_node in node.child_nodes:
        inv = child_node.invocation
        if inv.depth == child_depth and inv.fanout_idx == child_fanout_idx:
            return child_node.pane_id
    return None
