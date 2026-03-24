"""Code cell component for the flow transcript."""

from __future__ import annotations

import re as _re
from html import escape
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.flow_models import FlowCodeCell

# Simple keyword highlighting for Python tokens
_KEYWORDS = {
    "def",
    "class",
    "return",
    "import",
    "from",
    "if",
    "elif",
    "else",
    "for",
    "while",
    "try",
    "except",
    "finally",
    "with",
    "as",
    "in",
    "not",
    "and",
    "or",
    "is",
    "None",
    "True",
    "False",
    "yield",
    "async",
    "await",
    "raise",
    "pass",
    "break",
    "continue",
    "lambda",
}

_BUILTIN_NAMES = {
    "print",
    "len",
    "range",
    "str",
    "int",
    "float",
    "list",
    "dict",
    "set",
    "tuple",
    "type",
    "isinstance",
    "enumerate",
    "zip",
    "map",
    "filter",
    "sorted",
    "reversed",
    "any",
    "all",
    "open",
    "super",
}


def render_flow_code_pane(
    cell: FlowCodeCell,
    *,
    on_click_llm_query_line=None,
) -> None:
    """Render the full code cell with line numbers and syntax highlighting."""
    code = cell.code or cell.expanded_code
    if not code.strip():
        return

    llm_line_set = {info.line_number for info in cell.llm_query_lines}
    llm_line_map = {info.line_number: info for info in cell.llm_query_lines}
    lines = code.splitlines()

    with ui.element("div").style(
        "display: flex; flex-direction: column; min-width: 0; "
        "border-radius: 12px; overflow: hidden; "
        "border: 1px solid var(--border-1); "
        "background: var(--bg-2);"
    ):
        # Header bar
        with ui.element("div").style(
            "display: flex; align-items: center; justify-content: space-between; "
            "padding: 0.4rem 0.75rem; "
            "border-bottom: 1px solid var(--border-1); "
            "background: rgba(26,35,56,0.6);"
        ):
            ui.label("Code Cell").style(
                "color: var(--text-1); font-size: 0.72rem; font-weight: 700; "
                "letter-spacing: 0.06em; text-transform: uppercase;"
            )
            ui.label(f"{len(lines)} lines").style("color: var(--text-1); font-size: 0.68rem;")

        # Code lines
        with ui.element("div").style(
            "padding: 0.5rem 0; font-family: ui-monospace, SFMono-Regular, monospace; "
            "font-size: 0.82rem; line-height: 1.55; overflow-x: auto;"
        ):
            for idx, line in enumerate(lines, start=1):
                is_llm_line = idx in llm_line_set
                _render_code_line(
                    idx,
                    line,
                    is_llm_query=is_llm_line,
                    llm_info=llm_line_map.get(idx),
                    on_click=on_click_llm_query_line,
                )


def _render_code_line(
    line_number: int,
    line: str,
    *,
    is_llm_query: bool,
    llm_info,
    on_click,
) -> None:
    """Render a single line of code with gutter and optional llm_query indicator."""
    bg = "rgba(87,199,255,0.08)" if is_llm_query else "transparent"
    left_border = "3px solid var(--accent-root)" if is_llm_query else "3px solid transparent"
    cursor = "pointer" if is_llm_query and on_click else "default"

    el = ui.element("div").style(
        f"display: flex; align-items: center; gap: 0; min-width: 0; "
        f"background: {bg}; border-left: {left_border}; cursor: {cursor}; "
        "padding: 0 0.5rem 0 0;"
    )
    if is_llm_query and on_click and llm_info:
        el.on("click.stop", lambda _e, info=llm_info: on_click(info))

    with el:
        # Line number gutter
        ui.label(str(line_number)).style(
            "min-width: 2.8rem; text-align: right; padding-right: 0.75rem; "
            "color: var(--text-1); font-size: 0.72rem; user-select: none; "
            "opacity: 0.6; flex-shrink: 0;"
        )
        # Code content with basic highlighting
        highlighted = _highlight_line(line)
        ui.html(f'<span style="white-space: pre; color: var(--text-0);">{highlighted}</span>')
        # Rightward arrow + Child Agent chip on llm_query lines
        if is_llm_query and llm_info:
            child_label = "Child Agent"
            if llm_info.child_depth is not None:
                child_label = f"Child Agent (d{llm_info.child_depth}:f{llm_info.child_fanout_idx})"
            with ui.element("div").style(
                "margin-left: auto; display: flex; align-items: center; gap: 0.3rem; "
                "padding-left: 0.75rem; flex-shrink: 0;"
            ):
                ui.label("\u2192").style("color: var(--accent-root); font-size: 1rem;")
                with ui.element("div").style(
                    "display: inline-flex; align-items: center; "
                    "padding: 0.15rem 0.5rem; border-radius: 8px; "
                    "border: 1px solid var(--accent-root); "
                    "background: rgba(87,199,255,0.12);"
                ):
                    ui.label(child_label).style(
                        "color: var(--accent-root); font-size: 0.68rem; font-weight: 700;"
                    )


def _highlight_line(line: str) -> str:
    """Apply simple keyword-based syntax highlighting to a code line."""
    escaped = escape(line)
    if not escaped.strip():
        return escaped

    # Highlight comments
    stripped = escaped.lstrip()
    if stripped.startswith("#"):
        indent = escaped[: len(escaped) - len(stripped)]
        return f'{indent}<span style="color: #636d83; font-style: italic;">{stripped}</span>'

    # Single-pass keyword replacement — avoids corrupting spans inserted
    # by earlier passes (e.g. "or" inside "for"'s span content).
    return _HIGHLIGHT_RE.sub(_highlight_replacer, escaped)


# Build a single combined regex: longest keywords first to prevent
# partial matches (e.g. "llm_query_batched" before "llm_query").
_ALL_TOKENS: dict[str, str] = {}
for _fn in ("llm_query_batched", "llm_query"):
    _ALL_TOKENS[_fn] = f'<span style="color: var(--accent-root); font-weight: 700;">{_fn}</span>'
for _kw in sorted(_KEYWORDS, key=len, reverse=True):
    _ALL_TOKENS[_kw] = f'<span style="color: #c678dd;">{_kw}</span>'
for _bn in sorted(_BUILTIN_NAMES, key=len, reverse=True):
    _ALL_TOKENS[_bn] = f'<span style="color: #e5c07b;">{_bn}</span>'

# Group 1 matches HTML entities (skip them). Group 2 matches keywords.
_HIGHLIGHT_RE = _re.compile(
    r"(&\w+;)"  # group 1: HTML entities like &lt; — skip
    r"|"
    r"\b(" + "|".join(_re.escape(t) for t in _ALL_TOKENS) + r")\b"  # group 2: keyword
)


def _highlight_replacer(m: _re.Match) -> str:
    if m.group(1):  # HTML entity — pass through unchanged
        return m.group(1)
    return _ALL_TOKENS[m.group(2)]
