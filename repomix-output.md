This file is a merged representation of a subset of the codebase, containing specifically included files, combined into a single document by Repomix.
The content has been processed where content has been compressed (code blocks are separated by ⋮---- delimiter).

# File Summary

## Purpose
This file contains a packed representation of a subset of the repository's contents that is considered the most important context.
It is designed to be easily consumable by AI systems for analysis, code review,
or other automated processes.

## File Format
The content is organized as follows:
1. This summary section
2. Repository information
3. Directory structure
4. Repository files (if enabled)
5. Multiple file entries, each consisting of:
  a. A header with the file path (## File: path/to/file)
  b. The full contents of the file in a code block

## Usage Guidelines
- This file should be treated as read-only. Any changes should be made to the
  original repository files, not this packed version.
- When processing this file, use the file path to distinguish
  between different files in the repository.
- Be aware that this file may contain sensitive information. Handle it with
  the same level of security as you would the original repository.

## Notes
- Some files may have been excluded based on .gitignore rules and Repomix's configuration
- Binary files are not included in this packed representation. Please refer to the Repository Structure section for a complete list of file paths, including binary files
- Only files matching these patterns are included: rlm_adk/**/*.py
- Files matching patterns in .gitignore are excluded
- Files matching default ignore patterns are excluded
- Content has been compressed - code blocks are separated by ⋮---- delimiter
- Files are sorted by Git change count (files with more changes are at the bottom)

# Directory Structure
```
rlm_adk/
  callbacks/
    __init__.py
    orchestrator.py
    reasoning.py
    worker_retry.py
  dashboard/
    components/
      __init__.py
      api_usage.py
      child_window_header.py
      chunk_detail.py
      color_legend.py
      context_bar.py
      flow_code_pane.py
      flow_connectors.py
      flow_context_inspector.py
      flow_output_cell.py
      flow_reasoning_pane.py
      flow_tool_call_cell.py
      flow_transcript.py
      header.py
      live_context_banner.py
      live_context_viewer.py
      live_invocation_tree.py
      output_panel.py
      summary_bar.py
      token_charts.py
      worker_panel.py
    __init__.py
    __main__.py
    app.py
    controller.py
    data_loader.py
    data_models.py
    flow_builder.py
    flow_child_page.py
    flow_models.py
    gcloud_usage.py
    live_app.py
    live_controller.py
    live_loader.py
    live_models.py
    run_service.py
  eval/
    understand_bench/
      __init__.py
      file_type_registry.py
      loader.py
      runner.py
      scoring.py
      types.py
      workflow.py
    understand_bench_v2/
      __init__.py
      file_type_registry.py
      loader.py
      runner.py
      scoring.py
      types.py
      workflow.py
    __init__.py
    queries.py
    session_fork.py
    session_report.py
    trace_reader.py
  models/
    __init__.py
    litellm_router.py
  plugins/
    __init__.py
    cache.py
    context_snapshot.py
    dashboard_auto_launch.py
    google_cloud_analytics.py
    google_cloud_tracing.py
    langfuse_tracing.py
    litellm_cost_tracking.py
    migration.py
    observability.py
    policy.py
    repl_capture_plugin.py
    repl_tracing.py
    sqlite_tracing.py
    step_mode.py
  repl/
    __init__.py
    ipython_executor.py
    local_repl.py
    thread_bridge.py
    trace.py
  skills/
    obsolete/
      repl_skills/
        __init__.py
        ping.py
        repomix.py
      research/
        sources/
          substack/
            __init__.py
            client.py
            test_auth.py
          __init__.py
        __init__.py
      catalog.py
      polya_narrative_skill.py
      polya_understand_t1_workflow.py
      polya_understand_t2_flat.py
      polya_understand_t3_adaptive.py
      polya_understand_t4_debate.py
      polya_understand.py
      repomix_helpers.py
      repomix_skill.py
      skill_toolset.py
    recursive_ping/
      __init__.py
      ping.py
    test_skill/
      __init__.py
      skill.py
    __init__.py
    loader.py
  tools/
    __init__.py
    repl_tool.py
  utils/
    __init__.py
    parsing.py
    prompts.py
    user_context.py
  __init__.py
  agent.py
  artifacts.py
  dispatch.py
  orchestrator.py
  services.py
  state.py
  step_gate.py
  types.py
```

# Files

## File: rlm_adk/repl/__init__.py
````python
"""RLM ADK REPL - Local REPL execution and AST rewriting."""
````

## File: rlm_adk/utils/__init__.py
````python
"""RLM ADK Utilities - Parsing, prompts, and helper functions."""
````

## File: rlm_adk/__init__.py
````python
"""RLM ADK - Recursive Language Models on Google Agent Development Kit."""
⋮----
__all__ = [
````

## File: rlm_adk/callbacks/orchestrator.py
````python
"""Orchestrator-level test callbacks.

orchestrator_test_state_hook: Test-only before_agent_callback that writes a
    guillemet-marked dict to callback_context.state under ``cb_orchestrator_context``.
    Since before_agent_callback fires before the reasoning agent's first LLM
    call, the dict is available for ADK template resolution on ALL reasoning
    iterations (including call 0).
"""
⋮----
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
⋮----
return None  # Proceed with agent execution
````

## File: rlm_adk/dashboard/components/child_window_header.py
````python
"""Lineage header component for child drill-down pages."""
⋮----
"""Render the lineage header with back-link for a child window."""
fanout = "root" if fanout_idx is None else f"f{fanout_idx}"
child_label = f"d{depth}:{fanout}"
⋮----
child_label = f"{agent_name} ({child_label})"
⋮----
# Back link to parent session
parent_url = "/live"
⋮----
# Lineage breadcrumb
````

## File: rlm_adk/dashboard/components/color_legend.py
````python
"""Horizontal color legend for chunk categories.

NiceGUI review: use ``ui.badge`` with ``color=`` constructor parameter.
"""
⋮----
def build_color_legend() -> None
⋮----
"""Render a horizontal row of color swatches for each chunk category."""
⋮----
hex_color = CATEGORY_COLORS[category]
text_color = CATEGORY_TEXT_COLORS[category]
label = category.value.replace("_", " ").title()
````

## File: rlm_adk/dashboard/components/flow_context_inspector.py
````python
"""Right sidebar context inspector for the flow transcript."""
⋮----
"""Render the right sidebar Context Inspector."""
⋮----
def _state_items_section(data: FlowInspectorData, *, on_click_item) -> None
⋮----
"""Render the State/Context Items key-value table."""
⋮----
# Header row
⋮----
# Data rows (cap at 20 to keep DOM small)
⋮----
cursor = "pointer" if on_click_item else "default"
el = ui.element("div").style(
⋮----
# Key with depth annotation
key_text = item.base_key
depth_label = f"d{item.depth}"
⋮----
# Value preview
⋮----
def _skills_section(data: FlowInspectorData) -> None
⋮----
"""Render enabled skills as green-tinted chips."""
⋮----
def _return_value_section(data: FlowInspectorData) -> None
⋮----
"""Render the return value preview as syntax-highlighted JSON."""
⋮----
# Try to pretty-print JSON
⋮----
parsed = json.loads(data.return_value_json)
formatted = json.dumps(parsed, indent=2)
⋮----
formatted = data.return_value_json
````

## File: rlm_adk/dashboard/components/flow_output_cell.py
````python
"""Output cell component for the flow transcript."""
⋮----
def render_flow_output_cell(cell: FlowOutputCell) -> None
⋮----
"""Render the output cell below the code cell in notebook tradition."""
has_content = cell.stdout.strip() or cell.stderr.strip() or cell.child_returns
⋮----
"""Render a collapsible output section."""
bg = "rgba(255,107,159,0.06)" if error else "rgba(26,35,56,0.4)"
border_color = "var(--accent-child)" if error else "var(--border-1)"
⋮----
lines = text.strip().splitlines()
preview = "\n".join(lines[:50])
⋮----
def _child_returns_section(child_returns: list) -> None
⋮----
"""Render compact child return summary cards."""
⋮----
color = "var(--accent-child)" if child.error else "var(--accent-active)"
bg = "rgba(255,107,159,0.10)" if child.error else "rgba(126,240,160,0.10)"
⋮----
status = "ERR" if child.error else "OK"
````

## File: rlm_adk/dashboard/components/flow_tool_call_cell.py
````python
"""Renderer for non-execute_code tool call blocks in the flow transcript."""
⋮----
def render_flow_tool_call_cell(cell: FlowToolCallCell) -> None
⋮----
"""Dispatch to the appropriate per-tool renderer."""
⋮----
def _render_set_model_response(cell: FlowToolCallCell) -> None
⋮----
"""Render the populated output schema from set_model_response."""
# The tool result/args contain the schema fields (final_answer, reasoning_summary, etc.)
schema = cell.tool_result or cell.tool_args
⋮----
# Header
⋮----
# Schema fields as key-value rows
⋮----
display_value = _format_value(value)
⋮----
def _render_load_skill(cell: FlowToolCallCell) -> None
⋮----
"""Render skill name + collapsible instruction text (expanded by default)."""
skill_name = (cell.tool_args or {}).get("name", "unknown")
# The instruction text comes from the tool result
instruction = _extract_instruction(cell)
⋮----
def _render_list_skills(cell: FlowToolCallCell) -> None
⋮----
"""Render collapsible skill list text (expanded by default)."""
result_text = _format_value(cell.tool_result) if cell.tool_result else cell.result_text
⋮----
def _render_generic(cell: FlowToolCallCell) -> None
⋮----
"""Fallback renderer for unknown tool types."""
⋮----
def _extract_instruction(cell: FlowToolCallCell) -> str
⋮----
"""Extract instruction text from a load_skill tool result."""
result = cell.tool_result
⋮----
# ADK load_skill returns the instruction as a string or in a structured field
⋮----
# If the result is a dict with a single string value, use that
⋮----
def _format_value(value: object) -> str
⋮----
"""Format a value for display."""
````

## File: rlm_adk/dashboard/components/summary_bar.py
````python
"""Session summary bar -- stat cards for model, iterations, tokens, time."""
⋮----
def build_summary_bar(controller: DashboardController) -> None
⋮----
"""Render a row of stat cards summarizing the current session."""
summary = controller.state.session_summary
⋮----
duration = summary.end_time - summary.start_time if summary.end_time > summary.start_time else 0
⋮----
time_str = f"{duration / 60:.1f}m"
⋮----
time_str = f"{duration:.1f}s"
⋮----
cards = [
````

## File: rlm_adk/dashboard/__main__.py
````python
"""Entry point for ``python -m rlm_adk.dashboard``."""
````

## File: rlm_adk/dashboard/flow_child_page.py
````python
"""Dedicated child transcript page at /live/session/{session_id}/pane/{pane_id}."""
⋮----
# Import the CSS constant from live_app to reuse the same theme
⋮----
"""Find a node by pane_id in the invocation tree (DFS)."""
⋮----
found = _find_subtree_node(node.child_nodes, target_pane_id)
⋮----
@ui.page("/live/session/{session_id}/pane/{pane_id}")
async def child_transcript_page(session_id: str, pane_id: str) -> None
⋮----
"""Render a child agent's flow transcript rooted at the given pane."""
loader = LiveDashboardLoader()
controller = LiveDashboardController(loader)
⋮----
# Load the specific session
⋮----
# Find the target pane in the invocation tree
tree = controller.invocation_tree()
target_node = _find_subtree_node(tree, pane_id)
⋮----
inv = target_node.invocation
⋮----
# Build transcript rooted at this node
transcript = build_flow_transcript([target_node])
````

## File: rlm_adk/eval/understand_bench/__init__.py
````python
"""Understand-phase benchmark suite for RLM-ADK.

Evaluates whether an agent can detect insufficient context during the
Understand phase and emit a correct retrieval_order artifact identifying
missing external dependencies.
"""
⋮----
__all__ = [
⋮----
def __getattr__(name: str)
⋮----
_map = {
````

## File: rlm_adk/eval/understand_bench/file_type_registry.py
````python
"""Populated file type registry for tax-domain benchmark documents.

Provides FILE_TYPE_REGISTRY — a dict mapping type_id to FileTypeEntry.
"""
⋮----
_RAW: list[dict] = [
⋮----
# ---- IRS Forms ----
⋮----
# ---- Third-Party Documents ----
⋮----
# ---- Government/Regulatory ----
⋮----
# ---- User-Generated ----
⋮----
FILE_TYPE_REGISTRY: dict[str, FileTypeEntry] = {
````

## File: rlm_adk/eval/understand_bench/loader.py
````python
"""Loader for Understand-phase benchmark case fixtures.

Reads benchmark case JSON files, validates them against the
:class:`BenchmarkCase` Pydantic model, resolves gold retrieval orders,
and assembles the ``provided_context_dict`` with an injected ``_manifest``.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
# ---------------------------------------------------------------------------
# Package directory — used as the default base for case/gold discovery.
⋮----
_PACKAGE_DIR = Path(__file__).resolve().parent
⋮----
# Extension-to-type mapping for manifest auto-detection.
⋮----
_EXT_TYPE_MAP: dict[str, str] = {
⋮----
# Keys that carry suffixed format metadata (e.g. "receipt.png_format")
# and internal keys that should be excluded from the manifest.
_INTERNAL_KEYS = {"_manifest"}
⋮----
# Public API
⋮----
def load_case(case_path: str | Path) -> BenchmarkCase
⋮----
"""Load a benchmark case from a JSON fixture file.

    Reads the JSON, validates against :class:`BenchmarkCase`,
    resolves any file references in ``provided_context_dict``,
    and injects a ``_manifest`` key if one is not already present.

    Args:
        case_path: Path to a JSON case fixture.

    Returns:
        A validated :class:`BenchmarkCase` instance with ``_manifest``
        injected into ``provided_context_dict``.

    Raises:
        FileNotFoundError: If *case_path* does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        pydantic.ValidationError: If the JSON does not conform to
            the :class:`BenchmarkCase` schema.
    """
case_path = Path(case_path)
raw = json.loads(case_path.read_text(encoding="utf-8"))
case = BenchmarkCase.model_validate(raw)
⋮----
# Inject _manifest if not already present.
⋮----
def load_gold(gold_path: str | Path) -> list[str]
⋮----
"""Load a gold retrieval order from a JSON file.

    The gold file is expected to be a JSON array of strings representing
    the ordered list of missing artifact names.

    Args:
        gold_path: Path to a gold retrieval-order JSON file.

    Returns:
        Ordered list of artifact name strings.

    Raises:
        FileNotFoundError: If *gold_path* does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        TypeError: If the parsed JSON is not a list.
    """
gold_path = Path(gold_path)
data = json.loads(gold_path.read_text(encoding="utf-8"))
⋮----
"""Load a case and its corresponding gold retrieval order.

    The gold file is looked up at ``understand_bench/gold/{case_id}.json``.
    If that file does not exist, the function falls back to the case's
    own ``gold_retrieval_order`` field.

    Args:
        case_path: Path to a JSON case fixture.

    Returns:
        A ``(BenchmarkCase, gold_list)`` tuple where *gold_list* is the
        ordered list of artifact name strings from the gold file (or from
        the case's ``gold_retrieval_order`` if no gold file is found).
    """
case = load_case(case_path)
⋮----
# Attempt to load a separate gold file.
gold_file = _PACKAGE_DIR / "gold" / f"{case.case_id}.json"
⋮----
gold = load_gold(gold_file)
⋮----
gold = list(case.gold_retrieval_order)
⋮----
"""Discover all benchmark case fixture files.

    Searches ``cases/easy/``, ``cases/medium/``, ``cases/hard/`` under
    *base_dir*.  Optionally filters by difficulty level.

    Args:
        base_dir: Root directory of the understand_bench package.
            Defaults to the directory containing this module.
        difficulty: If provided, only return cases from the given
            difficulty sub-directory (``"easy"``, ``"medium"``, or
            ``"hard"``).

    Returns:
        Sorted list of :class:`Path` objects pointing to JSON fixture
        files.
    """
base = Path(base_dir) if base_dir is not None else _PACKAGE_DIR
cases_dir = base / "cases"
⋮----
difficulty = difficulty.lower()
subdirs = [cases_dir / difficulty]
⋮----
subdirs = [cases_dir / d for d in ("easy", "medium", "hard")]
⋮----
paths: list[Path] = []
⋮----
"""Build a manifest of documents in the provided context.

    Returns a list of dicts, one per user-facing entry in
    *provided_context_dict*, with the following keys:

    * ``filename`` -- the key in the dict.
    * ``type`` -- inferred from the filename extension / content
      (``"structured"``, ``"tabular"``, ``"text"``, ``"image"``,
      ``"document"``, or ``"unknown"``).
    * ``format`` -- the file extension without the leading dot
      (e.g. ``"json"``, ``"csv"``).
    * ``size_chars`` -- approximate character count of the serialised
      content.

    Internal keys (those starting with ``_``) are excluded.
    """
manifest: list[dict[str, Any]] = []
⋮----
# Skip internal keys.
⋮----
# Infer type from extension.
suffix = _extract_suffix(filename)
doc_type = _EXT_TYPE_MAP.get(suffix, "unknown")
fmt = suffix.lstrip(".") if suffix else "unknown"
⋮----
# Compute approximate size.
⋮----
size_chars = len(content)
⋮----
# Dicts / lists — measure the JSON representation.
size_chars = len(json.dumps(content, default=str))
⋮----
# Internal helpers
⋮----
def _extract_suffix(filename: str) -> str
⋮----
"""Return the file extension from *filename*.

    Handles compound pseudo-extensions like ``"school_enrollment.pdf_text"``
    by checking for known suffixes first, then falling back to
    :meth:`Path.suffix`.
    """
lower = filename.lower()
# Check known compound patterns first (e.g. ".pdf_text" -> treat as ".txt").
⋮----
# Standard extension.
suffix = Path(filename).suffix.lower()
````

## File: rlm_adk/eval/understand_bench/runner.py
````python
"""Runner for the Understand-phase benchmark suite.

Discovers and executes benchmark cases, scores agent outputs via
:func:`scoring.score_result`, and produces aggregate reports.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
_PACKAGE_DIR = Path(__file__).resolve().parent
⋮----
# Passing threshold: cases with total_score >= this value count as "passed".
_PASS_THRESHOLD = 60.0
⋮----
# ---------------------------------------------------------------------------
# Aggregate result model
⋮----
class BenchmarkSuiteResult(BaseModel)
⋮----
"""Aggregate results from running the full benchmark suite."""
⋮----
results: list[BenchmarkResult]
summary: dict[str, Any]
⋮----
# Runner
⋮----
class BenchmarkRunner
⋮----
"""Runs understand-phase benchmark cases and collects scored results.

    Usage::

        runner = BenchmarkRunner(difficulty_filter="easy")
        cases = runner.list_cases()
        result = runner.run_case("case_efile_auth", my_agent_fn)
        suite = runner.run_all(my_agent_fn)
        print(suite.summary)
    """
⋮----
"""Initialize the runner.

        Args:
            base_dir: Base directory for benchmark files.  Defaults to
                the ``understand_bench`` package directory.
            difficulty_filter: Optional filter for ``"easy"``,
                ``"medium"``, or ``"hard"``.
        """
⋮----
# Eagerly discover paths so callers get fast feedback on bad dirs.
⋮----
# Build an index: case_id -> path.
⋮----
# Parse just enough to extract case_id without full validation.
⋮----
raw = json.loads(path.read_text(encoding="utf-8"))
case_id = raw.get("case_id", path.stem)
⋮----
case_id = path.stem
⋮----
# ------------------------------------------------------------------
# Public API
⋮----
def list_cases(self) -> list[dict[str, str]]
⋮----
"""List available cases with ``case_id``, ``difficulty``, and ``path``.

        Returns:
            A list of dicts, each with keys ``"case_id"``,
            ``"difficulty"``, and ``"path"``.
        """
result: list[dict[str, str]] = []
⋮----
difficulty = raw.get("difficulty", "unknown")
⋮----
difficulty = "unknown"
⋮----
"""Run a single benchmark case.

        Args:
            case_id: The identifier of the case to run (must match a
                discovered case).
            agent_fn: An async callable that takes
                ``(broad_objective, provided_context_dict)`` and returns
                an :class:`AgentRetrievalOutput`.

        Returns:
            A scored :class:`BenchmarkResult`.

        Raises:
            KeyError: If *case_id* is not among the discovered cases.
        """
⋮----
available = sorted(self._case_index.keys())
⋮----
case_path = self._case_index[case_id]
⋮----
t0 = time.monotonic()
⋮----
agent_output = await agent_fn(case.broad_objective, case.provided_context_dict)
⋮----
elapsed = time.monotonic() - t0
⋮----
result = score_result(case, agent_output)
⋮----
"""Run all discovered cases and return aggregate results.

        Args:
            agent_fn: An async callable that takes
                ``(broad_objective, provided_context_dict)`` and returns
                an :class:`AgentRetrievalOutput`.

        Returns:
            A :class:`BenchmarkSuiteResult` with per-case results and
            a summary report.
        """
results: list[BenchmarkResult] = []
⋮----
result = await self.run_case(case_id, agent_fn)
⋮----
summary = self.run_suite_report(results)
⋮----
"""Generate a summary report from benchmark results.

        Args:
            results: List of scored :class:`BenchmarkResult` instances.

        Returns:
            A dict with:

            * ``total_cases`` -- number of cases run.
            * ``passed`` -- cases with ``total_score >= 60``.
            * ``failed`` -- cases with ``total_score < 60``.
            * ``avg_score``, ``min_score``, ``max_score`` -- score
              statistics.
            * ``by_difficulty`` -- breakdown by difficulty level, each
              with ``avg``, ``count``, ``passed``, ``failed``.
            * ``per_case`` -- list of per-case summaries with
              ``case_id``, ``score``, ``recall``, ``precision``,
              ``order_score``, ``halt_score``, ``penalties``.
        """
⋮----
scores = [r.total_score for r in results]
passed = sum(1 for s in scores if s >= _PASS_THRESHOLD)
failed = len(scores) - passed
⋮----
# Per-case summaries.
per_case: list[dict[str, Any]] = []
⋮----
# Group by difficulty.
by_difficulty: dict[str, dict[str, Any]] = {}
# We need to look up difficulty per case_id.  Use the index.
difficulty_map: dict[str, str] = {}
⋮----
# Build per-difficulty buckets.
difficulty_buckets: dict[str, list[float]] = {}
⋮----
diff = difficulty_map.get(r.case_id, "unknown")
⋮----
# Bridge agent_fn: runs the real RLM agent via create_rlm_runner
⋮----
"""Run the RLM agent against a benchmark case and extract retrieval output.

    Builds the pre-seeded session state with ``user_provided_ctx``, creates
    a Runner via :func:`rlm_adk.agent.create_rlm_runner`, executes the
    agent, and extracts ``retrieval_order`` and ``halted`` from the final
    REPL output or session state.

    Args:
        broad_objective: The case's broad objective string.
        provided_context_dict: The case's provided context dict (filename->content).
        model: LLM model identifier.  Defaults to ``RLM_ADK_MODEL`` env var
            or ``gemini-2.5-flash``.
        max_iterations: Maximum tool calls for the agent.
        max_depth: Maximum recursion depth for child dispatches.

    Returns:
        An :class:`AgentRetrievalOutput` extracted from the agent run.
    """
⋮----
resolved_model = model or os.getenv("RLM_ADK_MODEL", "gemini-2.5-flash")
⋮----
# Build manifest from provided_context_dict
filenames = sorted(k for k in provided_context_dict if not k.startswith("_"))
manifest_lines = [
⋮----
content = provided_context_dict[fn]
⋮----
chars = len(content)
⋮----
chars = len(json.dumps(content, default=str))
⋮----
manifest_str = "\n".join(manifest_lines)
⋮----
# Build query that steers the agent to use polya-understand skill
query = (
⋮----
runner = create_rlm_runner(
⋮----
# Create session with pre-seeded state
session = await runner.session_service.create_session(
⋮----
# Run the agent
raw_output_parts: list[str] = []
content_msg = types.Content(
⋮----
raw_output = "\n".join(raw_output_parts)
⋮----
# Extract retrieval_order and halted from output
# Look for patterns like: ['artifact1', 'artifact2']
# and: True / False for halted
retrieval_order: list[str] = []
halted = False
⋮----
# Try to extract from LAST_REPL_RESULT in session state
updated_session = await runner.session_service.get_session(
last_repl = ""
⋮----
last_repl = updated_session.state.get(LAST_REPL_RESULT, "")
⋮----
# Parse from LAST_REPL_RESULT first (contains only REPL stdout),
# fall back to raw_output tail.
parse_text = last_repl if last_repl else raw_output
⋮----
# Extract retrieval order: find last Python list pattern in text
list_matches = list(re.finditer(r"\[([^\]]*)\]", parse_text))
⋮----
# Use the LAST match — retrieval_order is printed after other output
list_content = list_matches[-1].group(1)
items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
retrieval_order = items
⋮----
# Extract halted: look for standalone True/False AFTER retrieval output
# Split on the last list match to avoid matching booleans in JSON data
halted_text = parse_text
⋮----
halted_text = parse_text[list_matches[-1].end():]
halted_match = re.search(r"\b(True|False)\b", halted_text)
⋮----
halted = halted_match.group(1) == "True"
⋮----
"""Create an async agent_fn for :meth:`BenchmarkRunner.run_case`.

    Returns an async callable with signature
    ``(broad_objective, provided_context_dict) -> AgentRetrievalOutput``.

    Args:
        model: LLM model identifier (default: env var or gemini-2.5-flash).
        max_iterations: Maximum tool calls.
        max_depth: Maximum recursion depth.

    Returns:
        An async callable for use as ``agent_fn``.
    """
⋮----
# CLI entry point — dry-run with a dummy agent
⋮----
"""A dummy agent that always halts with no retrievals.

    Useful for dry-run testing of the benchmark harness itself.
    """
⋮----
async def _main_async() -> None
⋮----
"""Async CLI entry point."""
⋮----
parser = argparse.ArgumentParser(
⋮----
args = parser.parse_args()
⋮----
runner = BenchmarkRunner(
⋮----
result = await runner.run_case(args.case, _dummy_agent)
⋮----
suite = await runner.run_all(_dummy_agent)
⋮----
def main() -> None
⋮----
"""CLI entry point."""
````

## File: rlm_adk/eval/understand_bench/scoring.py
````python
"""Scoring module for the Understand-phase benchmark.

Implements the rubric defined in Section 11 of understand_bench_plan.md:
  Recall 40%, Precision 20%, Order Score 20%, Halt Score 20%
  plus penalty deductions for hallucinations, proceeding without retrieval,
  and generic/vague retrievals.
"""
⋮----
# ---------------------------------------------------------------------------
# Category keyword map — used by _category_match to award 50% partial credit
# when the agent identifies the *kind* of missing context but not the exact
# artifact name.
⋮----
_CATEGORY_KEYWORDS: dict[MissingContextCategory, list[str]] = {
⋮----
# Patterns that signal a vague / generic retrieval.
_GENERIC_PATTERNS: list[re.Pattern[str]] = [
⋮----
# Scoring constants
_WEIGHT_RECALL = 40.0
_WEIGHT_PRECISION = 20.0
_WEIGHT_ORDER = 20.0
_WEIGHT_HALT = 20.0
_MAX_SCORE = 100.0
⋮----
_PENALTY_HALLUCINATED = -5.0
_PENALTY_PROCEEDING = -20.0
_PENALTY_GENERIC = -10.0
⋮----
# Output / Result models
⋮----
class AgentRetrievalOutput(BaseModel)
⋮----
"""What the agent produced as its retrieval order."""
⋮----
retrieved_artifacts: list[str]  # artifact names the agent identified
halted: bool  # did the agent explicitly say it cannot proceed?
raw_output: str = ""  # the agent's full text output for debugging
⋮----
class BenchmarkResult(BaseModel)
⋮----
"""Scored result for a single benchmark case."""
⋮----
case_id: str
recall: float  # 0.0-1.0
precision: float  # 0.0-1.0
order_score: float  # 0.0-1.0, Kendall tau for multi-hop
halt_score: float  # 0.0 or 1.0
penalties: dict[str, float] = Field(default_factory=dict)
total_score: float  # weighted composite
max_possible_score: float = _MAX_SCORE
details: dict[str, Any] = Field(default_factory=dict)
⋮----
# Helper functions
⋮----
_ARTICLES = re.compile(r"\b(a|an|the)\b")
_WHITESPACE = re.compile(r"\s+")
⋮----
def _normalize(s: str) -> str
⋮----
"""Lowercase, collapse whitespace, strip leading/trailing space, remove articles."""
s = s.lower()
s = _ARTICLES.sub("", s)
s = _WHITESPACE.sub(" ", s).strip()
⋮----
def _fuzzy_match(a: str, b: str) -> bool
⋮----
"""Check whether two artifact descriptions are similar enough.

    Considers a match when either:
    - One normalized string is a substring of the other, OR
    - The token-level overlap (Jaccard) is >= 0.6.
    """
na = _normalize(a)
nb = _normalize(b)
⋮----
# Substring containment (either direction).
⋮----
# Token-level Jaccard similarity.
tokens_a = set(na.split())
tokens_b = set(nb.split())
⋮----
intersection = tokens_a & tokens_b
union = tokens_a | tokens_b
⋮----
def _category_match(artifact_text: str, category: MissingContextCategory) -> bool
⋮----
"""Return True if *artifact_text* implies *category* via keyword overlap."""
normalized = _normalize(artifact_text)
keywords = _CATEGORY_KEYWORDS.get(category, [])
⋮----
def _kendall_tau(a: list[str], b: list[str]) -> float
⋮----
"""Compute Kendall tau rank correlation between two orderings.

    Both lists must contain the same set of elements (only the shared
    intersection is considered).  Returns a value in [-1, 1].
    """
# Restrict to shared elements, preserving order within each list.
shared = set(a) & set(b)
⋮----
# Need at least 2 items to compute a ranking correlation.
⋮----
order_a = [x for x in a if x in shared]
order_b = [x for x in b if x in shared]
⋮----
# Build rank map from order_b.
rank_b = {item: idx for idx, item in enumerate(order_b)}
⋮----
# Count concordant and discordant pairs.
n = len(order_a)
concordant = 0
discordant = 0
⋮----
# Compare the pair (order_a[i], order_a[j]) in both orderings.
a_diff = i - j  # always negative since i < j
b_diff = rank_b[order_a[i]] - rank_b[order_a[j]]
⋮----
total_pairs = concordant + discordant
⋮----
def _is_generic_retrieval(text: str) -> bool
⋮----
"""Return True if *text* looks like a vague/generic retrieval request."""
⋮----
# Main scoring function
⋮----
def score_result(case: BenchmarkCase, agent_output: AgentRetrievalOutput) -> BenchmarkResult
⋮----
"""Score an agent's retrieval output against a benchmark case's gold set.

    Returns a :class:`BenchmarkResult` with point breakdowns.
    """
gold_names: list[str] = [item.artifact_name for item in case.missing_artifacts]
gold_items = case.missing_artifacts
agent_names: list[str] = agent_output.retrieved_artifacts
⋮----
# ----- Match agent artifacts to gold artifacts -----
# For each gold artifact, track: "full", "category", or None.
gold_match_type: dict[str, str] = {}  # gold_name -> match type
matched_agent_indices: set[int] = set()
⋮----
best_match: str | None = None
best_type: str = ""
⋮----
best_match = agent_art
best_type = "full"
⋮----
# Try category-level partial match.
⋮----
best_type = "category"
⋮----
# ----- Recall (40 points) -----
⋮----
recall = 1.0
⋮----
recall_credits = 0.0
⋮----
match_type = gold_match_type.get(gold_item.artifact_name)
⋮----
# else: 0
recall = recall_credits / len(gold_items)
⋮----
recall_points = recall * _WEIGHT_RECALL
⋮----
# ----- Precision (20 points) -----
⋮----
precision = 1.0 if not gold_names else 0.0
⋮----
precision = len(matched_agent_indices) / len(agent_names)
⋮----
precision_points = precision * _WEIGHT_PRECISION
⋮----
# ----- Order Score (20 points) -----
⋮----
# No multi-hop requirement — full credit.
order_score = 1.0
⋮----
# Build agent ordering restricted to fully-matched gold items.
agent_matched_order: list[str] = []
⋮----
gn = _find_gold_name_for_agent(agent_names[i], gold_items)
⋮----
# Map agent artifacts back to gold names for comparison.
agent_gold_order: list[str] = []
⋮----
gn = _find_gold_name_for_agent(a, gold_items)
⋮----
order_score = 0.0
⋮----
tau = _kendall_tau(agent_gold_order, list(case.multi_hop_chain))
order_score = (tau + 1.0) / 2.0  # Normalize [-1,1] -> [0,1]
⋮----
order_points = order_score * _WEIGHT_ORDER
⋮----
# ----- Halt Score (20 points) -----
halt_score = 1.0 if agent_output.halted else 0.0
halt_points = halt_score * _WEIGHT_HALT
⋮----
# ----- Penalties -----
penalties: dict[str, float] = {}
⋮----
# Hallucinated retrievals: agent artifacts not matched to any gold item.
unmatched_agent = [
# Filter out near-misses (items that are category matches to *some* gold
# item but weren't consumed during matching because a better match existed).
hallucinated = [
⋮----
# Proceeding without retrieval: didn't halt AND missed most gold items.
⋮----
# Generic retrieval: vague request without specifying artifacts.
generic_hits = [art for art in agent_names if _is_generic_retrieval(art)]
⋮----
penalty_total = sum(penalties.values())
⋮----
# ----- Total -----
raw_total = recall_points + precision_points + order_points + halt_points
total_score = max(0.0, raw_total + penalty_total)
⋮----
# ----- Details -----
details: dict[str, Any] = {
⋮----
# Internal: map agent artifact text back to gold name via fuzzy match
⋮----
"""Return the gold artifact_name that fuzzy-matches *agent_text*, or None."""
````

## File: rlm_adk/eval/understand_bench/types.py
````python
"""Type system for the Understand-phase benchmark.

Defines the missing-context taxonomy (MissingContextCategory),
individual missing-context items (MissingContextItem), and the
benchmark case schema (BenchmarkCase).
"""
⋮----
# ---------------------------------------------------------------------------
# N0: Missing-Context Taxonomy
⋮----
class MissingContextCategory(str, Enum)
⋮----
"""Top-level classification of missing context."""
⋮----
DOCUMENT = "document"
CREDENTIAL = "credential"
AGENT_SKILL = "agent_skill"
HISTORICAL_RECORD = "historical"
THIRD_PARTY_RECORD = "third_party"
USER_ATTESTATION = "user_attestation"
REGULATORY_REFERENCE = "regulatory"
COMPUTATIONAL_PREREQ = "computational"
CROSS_DOMAIN_LINK = "cross_domain"
⋮----
class MissingContextItem(BaseModel)
⋮----
"""A single missing-context entry in a benchmark case."""
⋮----
category: MissingContextCategory
artifact_name: str = Field(..., description='Human-readable name, e.g. "Prior-year AGI"')
source_authority: str = Field(
why_non_derivable: str = Field(
detection_signal: str = Field(
retrieval_method: str = Field(
blocks_downstream: list[str] = Field(
difficulty_modifier: Literal["direct", "inferential", "multi-hop"] = "direct"
⋮----
# N4: File Type Registry
⋮----
class FileTypeCategory(str, Enum)
⋮----
"""Top-level classification of document types."""
⋮----
IRS_FORM = "irs_form"
THIRD_PARTY = "third_party"
GOVERNMENT = "government"
USER_GENERATED = "user_generated"
⋮----
class FileTypeEntry(BaseModel)
⋮----
"""A single entry in the file type registry."""
⋮----
type_id: str = Field(..., description='e.g. "w2", "1099_nec"')
display_name: str = Field(..., description='e.g. "W-2 (Wage and Tax Statement)"')
category: FileTypeCategory
formats: list[str] = Field(
role_in_workflow: str = ""
common_gap_pattern: str = ""
⋮----
# The registry is a flat list; see file_type_registry.py for the populated instance.
⋮----
# Benchmark Case schema
⋮----
class BenchmarkCase(BaseModel)
⋮----
"""A single understand-phase benchmark case."""
⋮----
case_id: str
task_name: str
difficulty: Literal["easy", "medium", "hard"]
persona_id: str
⋮----
broad_objective: str
provided_context_dict: dict[str, Any] = Field(
⋮----
missing_artifacts: list[MissingContextItem]
gold_retrieval_order: list[str] = Field(
⋮----
why_context_tempts_premature_progress: str = ""
what_bad_model_does: str = ""
what_good_model_does: str = ""
⋮----
scoring_notes: str = ""
multi_hop_chain: list[str] | None = None
⋮----
# Workflow Step model (N2)
⋮----
class WorkflowStep(BaseModel)
⋮----
"""A single step in the tax-preparation workflow."""
⋮----
step_number: int
name: str
description: str = ""
dependencies: list[str] = Field(default_factory=list, description="What this step needs")
potential_gaps: list[str] = Field(
depends_on_steps: list[int] = Field(
````

## File: rlm_adk/eval/understand_bench/workflow.py
````python
"""Tax-preparation workflow decomposition (N2).

Provides TAX_WORKFLOW — the ordered list of WorkflowStep objects
representing the end-to-end tax-preparation-and-filing pipeline.
"""
⋮----
TAX_WORKFLOW: list[WorkflowStep] = [
````

## File: rlm_adk/eval/understand_bench_v2/__init__.py
````python
"""Understand-Phase Benchmark v2 — file-based, multi-format tax return benchmark.

Unlike v1 (inline JSON context), v2 uses real files in diverse formats
(PDF, CSV, Excel, image, plain text, JSON) that require different
processing skills. The benchmark evaluates both:
  1. Missing-context detection (same as v1)
  2. Format-processing skill identification (new in v2)
"""
⋮----
__all__ = [
````

## File: rlm_adk/eval/understand_bench_v2/file_type_registry.py
````python
"""Populated file type registry for v2 benchmark documents.

Extends v1 registry with format-specific skill mappings and
multi-format support reflecting real-world document diversity.
"""
⋮----
# ---------------------------------------------------------------------------
# Format → required skills mapping
⋮----
FORMAT_SKILLS: dict[str, list[FormatSkill]] = {
⋮----
# Document type definitions with typical formats found in the wild
⋮----
DOC_TYPE_FORMATS: dict[str, dict] = {
⋮----
# IRS Forms — typically PDFs or structured data
⋮----
# Third-party documents — wide format diversity
⋮----
# User-generated documents — most format-diverse
⋮----
def get_skills_for_file(doc_type: str, fmt: str) -> list[FormatSkill]
⋮----
"""Return the processing skills needed for a given doc_type + format combination."""
entry = DOC_TYPE_FORMATS.get(doc_type)
⋮----
skills = entry.get("skills_by_format", {}).get(fmt)
````

## File: rlm_adk/eval/understand_bench_v2/loader.py
````python
"""Loader for Understand-phase benchmark v2 case fixtures.

Unlike v1 which embeds content inline, v2 resolves FileRef entries
to actual files on disk in the corpus/ directory. The loader:
  1. Reads the case JSON
  2. Validates against BenchmarkCaseV2
  3. Resolves each FileRef to a real file path
  4. Builds a manifest with format/size/skill metadata
  5. Optionally loads file contents for inline processing
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
_PACKAGE_DIR = Path(__file__).resolve().parent
_CORPUS_DIR = _PACKAGE_DIR / "corpus"
⋮----
def load_case(case_path: str | Path) -> BenchmarkCaseV2
⋮----
"""Load a benchmark case from a JSON fixture file.

    Validates file references exist on disk and enriches
    FileRef entries with size_bytes and skills_required.
    """
case_path = Path(case_path)
raw = json.loads(case_path.read_text(encoding="utf-8"))
case = BenchmarkCaseV2.model_validate(raw)
⋮----
# Enrich file references with on-disk metadata
⋮----
# Compute aggregate skills
all_skills = set()
⋮----
def load_gold(gold_path: str | Path) -> list[str]
⋮----
"""Load a gold retrieval order from a JSON file."""
gold_path = Path(gold_path)
data = json.loads(gold_path.read_text(encoding="utf-8"))
⋮----
"""Load a case and its corresponding gold retrieval order."""
case = load_case(case_path)
⋮----
gold_file = _PACKAGE_DIR / "gold" / f"{case.case_id}.json"
⋮----
gold = load_gold(gold_file)
⋮----
gold = list(case.gold_retrieval_order)
⋮----
"""Discover all benchmark case fixture files."""
base = Path(base_dir) if base_dir is not None else _PACKAGE_DIR
cases_dir = base / "cases"
⋮----
difficulty = difficulty.lower()
subdirs = [cases_dir / difficulty]
⋮----
subdirs = [cases_dir / d for d in ("easy", "medium", "hard")]
⋮----
paths: list[Path] = []
⋮----
def resolve_file_path(file_ref: FileRef, corpus_dir: Path | None = None) -> Path
⋮----
"""Resolve a FileRef to an absolute path in the corpus directory."""
base = corpus_dir or _CORPUS_DIR
⋮----
def build_manifest(case: BenchmarkCaseV2) -> list[dict[str, Any]]
⋮----
"""Build a manifest of all provided files with metadata.

    Returns a list suitable for injecting into the agent's context
    as a document inventory.
    """
manifest: list[dict[str, Any]] = []
⋮----
file_path = resolve_file_path(fref)
⋮----
def load_file_content(file_ref: FileRef, corpus_dir: Path | None = None) -> str | bytes
⋮----
"""Load the actual content of a file referenced by a FileRef.

    Returns str for text-based formats, bytes for binary formats.
    """
file_path = resolve_file_path(file_ref, corpus_dir)
⋮----
binary_formats = {"pdf", "xlsx", "png", "jpg", "jpeg", "heic", "tiff", "gif", "bmp"}
⋮----
# ---------------------------------------------------------------------------
# Internal helpers
⋮----
def _enrich_file_ref(fref: FileRef) -> None
⋮----
"""Enrich a FileRef with on-disk metadata and skill requirements."""
⋮----
# Set size if file exists
⋮----
# Compute skills if not already set
````

## File: rlm_adk/eval/understand_bench_v2/runner.py
````python
"""Benchmark runner for Understand-phase v2.

Discovers cases, runs an agent function against each, scores results,
and produces a suite summary. Includes a built-in dummy agent for
dry-run validation.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
# Type alias for agent functions
AgentFn = Callable[
# AgentFn signature: (broad_objective, manifest, file_metadata_list) -> AgentOutputV2
⋮----
class SuiteResult(BaseModel)
⋮----
"""Aggregate result for a full benchmark suite run."""
⋮----
results: list[BenchmarkResultV2]
total_cases: int = 0
passed: int = 0
failed: int = 0
avg_score: float = 0.0
summary: str = ""
⋮----
class BenchmarkRunnerV2
⋮----
"""Orchestrates benchmark case discovery, execution, and scoring."""
⋮----
def list_cases(self) -> list[dict[str, str]]
⋮----
"""Return a list of available case summaries."""
paths = discover_cases(self._base_dir, self._difficulty_filter)
summaries = []
⋮----
raw = json.loads(p.read_text(encoding="utf-8"))
⋮----
"""Run a single case and return the scored result."""
paths = discover_cases(self._base_dir)
case_path = None
⋮----
case_path = p
⋮----
manifest = build_manifest(case)
⋮----
# Build file metadata for the agent
file_metadata = []
⋮----
fpath = resolve_file_path(fref)
⋮----
agent_output = agent_fn(case.broad_objective, manifest, file_metadata)
⋮----
def run_all(self, agent_fn: AgentFn) -> SuiteResult
⋮----
"""Run all discovered cases and return aggregate results."""
⋮----
results: list[BenchmarkResultV2] = []
⋮----
result = score_result(case, agent_output)
⋮----
result = BenchmarkResultV2(
⋮----
# Aggregate
total = len(results)
passed = sum(1 for r in results if r.total_score >= self._pass_threshold)
failed = total - passed
avg = sum(r.total_score for r in results) / total if total > 0 else 0.0
⋮----
lines = [
⋮----
status = "PASS" if r.total_score >= self._pass_threshold else "FAIL"
⋮----
# ---------------------------------------------------------------------------
# Built-in dummy agent (always halts, no retrievals, no skills)
⋮----
"""Dummy agent that halts immediately with no output."""
⋮----
# CLI entry point
⋮----
def main() -> None
⋮----
parser = argparse.ArgumentParser(description="Understand Bench v2 Runner")
⋮----
args = parser.parse_args()
⋮----
runner = BenchmarkRunnerV2(difficulty_filter=args.difficulty)
⋮----
result = runner.run_case(args.case, _dummy_agent)
⋮----
suite = runner.run_all(_dummy_agent)
````

## File: rlm_adk/eval/understand_bench_v2/scoring.py
````python
"""Scoring module for the Understand-phase benchmark v2.

Extends v1 scoring with format-processing skill evaluation:
  - Recall 30% (missing-context detection)
  - Precision 15% (false positive penalty)
  - Order Score 15% (retrieval sequencing for multi-hop)
  - Halt Score 15% (did agent halt on gaps?)
  - Skill Score 25% (NEW: did agent identify required processing skills?)
"""
⋮----
# ---------------------------------------------------------------------------
# Category keyword map (same as v1)
⋮----
_CATEGORY_KEYWORDS: dict[MissingContextCategory, list[str]] = {
⋮----
# Skill keyword map for partial matching
_SKILL_KEYWORDS: dict[FormatSkill, list[str]] = {
⋮----
_GENERIC_PATTERNS: list[re.Pattern[str]] = [
⋮----
# v2 scoring weights (rebalanced for skill assessment)
_WEIGHT_RECALL = 30.0
_WEIGHT_PRECISION = 15.0
_WEIGHT_ORDER = 15.0
_WEIGHT_HALT = 15.0
_WEIGHT_SKILL = 25.0
_MAX_SCORE = 100.0
⋮----
_PENALTY_HALLUCINATED = -5.0
_PENALTY_PROCEEDING = -20.0
_PENALTY_GENERIC = -10.0
_PENALTY_WRONG_SKILL = -3.0
⋮----
# Output / Result models
⋮----
class AgentOutputV2(BaseModel)
⋮----
"""What the agent produced — extends v1 with skill identification."""
⋮----
retrieved_artifacts: list[str]
halted: bool
identified_skills: list[str] = Field(
processing_plan: list[str] = Field(
raw_output: str = ""
⋮----
class BenchmarkResultV2(BaseModel)
⋮----
"""Scored result for a single v2 benchmark case."""
⋮----
case_id: str
recall: float
precision: float
order_score: float
halt_score: float
skill_score: float  # NEW in v2
penalties: dict[str, float] = Field(default_factory=dict)
total_score: float
max_possible_score: float = _MAX_SCORE
details: dict[str, Any] = Field(default_factory=dict)
⋮----
# Helpers (shared with v1)
⋮----
_ARTICLES = re.compile(r"\b(a|an|the)\b")
_WHITESPACE = re.compile(r"\s+")
⋮----
def _normalize(s: str) -> str
⋮----
s = s.lower()
s = s.replace("_", " ")
s = _ARTICLES.sub("", s)
s = _WHITESPACE.sub(" ", s).strip()
⋮----
def _fuzzy_match(a: str, b: str) -> bool
⋮----
na = _normalize(a)
nb = _normalize(b)
⋮----
tokens_a = set(na.split())
tokens_b = set(nb.split())
⋮----
def _category_match(artifact_text: str, category: MissingContextCategory) -> bool
⋮----
normalized = _normalize(artifact_text)
keywords = _CATEGORY_KEYWORDS.get(category, [])
⋮----
def _skill_match(agent_skill_text: str, gold_skill: FormatSkill) -> bool
⋮----
normalized = _normalize(agent_skill_text)
keywords = _SKILL_KEYWORDS.get(gold_skill, [])
⋮----
def _kendall_tau(a: list[str], b: list[str]) -> float
⋮----
shared = set(a) & set(b)
⋮----
order_a = [x for x in a if x in shared]
order_b = [x for x in b if x in shared]
rank_b = {item: idx for idx, item in enumerate(order_b)}
n = len(order_a)
concordant = discordant = 0
⋮----
a_diff = i - j
b_diff = rank_b[order_a[i]] - rank_b[order_a[j]]
⋮----
total_pairs = concordant + discordant
⋮----
def _is_generic_retrieval(text: str) -> bool
⋮----
# Main scoring function
⋮----
def score_result(case: BenchmarkCaseV2, agent_output: AgentOutputV2) -> BenchmarkResultV2
⋮----
"""Score an agent's output against a v2 benchmark case."""
gold_items = case.missing_artifacts
gold_names = [item.artifact_name for item in gold_items]
agent_names = agent_output.retrieved_artifacts
⋮----
# ----- Match agent artifacts to gold (same as v1) -----
gold_match_type: dict[str, str] = {}
matched_agent_indices: set[int] = set()
⋮----
# ----- Recall (30 points) -----
⋮----
recall = 1.0
⋮----
credits = sum(
recall = credits / len(gold_items)
recall_points = recall * _WEIGHT_RECALL
⋮----
# ----- Precision (15 points) -----
⋮----
precision = 1.0 if not gold_names else 0.0
⋮----
precision = len(matched_agent_indices) / len(agent_names)
precision_points = precision * _WEIGHT_PRECISION
⋮----
# ----- Order Score (15 points) -----
⋮----
order_score = 1.0
⋮----
agent_gold_order: list[str] = []
⋮----
order_score = 0.0
⋮----
tau = _kendall_tau(agent_gold_order, list(case.multi_hop_chain))
order_score = (tau + 1.0) / 2.0
order_points = order_score * _WEIGHT_ORDER
⋮----
# ----- Halt Score (15 points) -----
halt_score = 1.0 if agent_output.halted else 0.0
halt_points = halt_score * _WEIGHT_HALT
⋮----
# ----- Skill Score (25 points) — NEW in v2 -----
gold_skills = set(case.total_skills_required)
agent_skill_texts = agent_output.identified_skills
⋮----
skill_score = 1.0
⋮----
matched_skills: set[FormatSkill] = set()
⋮----
skill_score = len(matched_skills) / len(gold_skills)
skill_points = skill_score * _WEIGHT_SKILL
⋮----
# ----- Penalties -----
penalties: dict[str, float] = {}
⋮----
unmatched_agent = [
hallucinated = [
⋮----
generic_hits = [art for art in agent_names if _is_generic_retrieval(art)]
⋮----
penalty_total = sum(penalties.values())
⋮----
# ----- Total -----
raw_total = recall_points + precision_points + order_points + halt_points + skill_points
total_score = max(0.0, raw_total + penalty_total)
⋮----
details: dict[str, Any] = {
````

## File: rlm_adk/eval/understand_bench_v2/types.py
````python
"""Type system for the Understand-phase benchmark v2.

Extends v1 types with:
  - FileRef: references to real files on disk (not inline JSON)
  - FormatSkill: processing capabilities needed per file format
  - ProcessingChallenge: format-specific obstacles the agent must overcome
  - BenchmarkCaseV2: cases built from file references, not inline dicts
"""
⋮----
# ---------------------------------------------------------------------------
# Missing-Context Taxonomy (same as v1, imported for consistency)
⋮----
class MissingContextCategory(str, Enum)
⋮----
DOCUMENT = "document"
CREDENTIAL = "credential"
AGENT_SKILL = "agent_skill"
HISTORICAL_RECORD = "historical"
THIRD_PARTY_RECORD = "third_party"
USER_ATTESTATION = "user_attestation"
REGULATORY_REFERENCE = "regulatory"
COMPUTATIONAL_PREREQ = "computational"
CROSS_DOMAIN_LINK = "cross_domain"
⋮----
class MissingContextItem(BaseModel)
⋮----
category: MissingContextCategory
artifact_name: str = Field(..., description='Human-readable name, e.g. "Prior-year AGI"')
source_authority: str = Field(
why_non_derivable: str = Field(
detection_signal: str = Field(
retrieval_method: str = Field(
blocks_downstream: list[str] = Field(
difficulty_modifier: Literal["direct", "inferential", "multi-hop"] = "direct"
⋮----
# v2-specific: Format-Processing Skills
⋮----
class FormatSkill(str, Enum)
⋮----
"""Processing capabilities an agent needs to handle diverse file formats."""
⋮----
PDF_TEXT_EXTRACT = "pdf_text_extract"
PDF_TABLE_EXTRACT = "pdf_table_extract"
PDF_FORM_FIELD_EXTRACT = "pdf_form_field_extract"
IMAGE_OCR = "image_ocr"
IMAGE_HANDWRITING_OCR = "image_handwriting_ocr"
CSV_PARSE = "csv_parse"
EXCEL_PARSE = "excel_parse"
EXCEL_MULTI_SHEET = "excel_multi_sheet"
JSON_PARSE = "json_parse"
XML_PARSE = "xml_parse"
MARKDOWN_PARSE = "markdown_parse"
PLAIN_TEXT_PARSE = "plain_text_parse"
HTML_PARSE = "html_parse"
FINANCIAL_TABLE_INTERPRET = "financial_table_interpret"
FORM_LAYOUT_UNDERSTAND = "form_layout_understand"
CROSS_REFERENCE = "cross_reference"
DATE_NORMALIZATION = "date_normalization"
CURRENCY_NORMALIZATION = "currency_normalization"
⋮----
class ProcessingChallenge(BaseModel)
⋮----
"""A format-specific obstacle the agent must overcome to extract information."""
⋮----
file_ref: str = Field(..., description="Which FileRef this challenge applies to")
required_skill: FormatSkill
description: str = Field(..., description="What makes this file hard to process")
extraction_target: str = Field(..., description="What specific information must be extracted")
difficulty: Literal["routine", "moderate", "hard"] = "routine"
⋮----
# v2-specific: File References
⋮----
class FileRef(BaseModel)
⋮----
"""A reference to a real file in the corpus directory."""
⋮----
ref_id: str = Field(..., description='Unique ID within the case, e.g. "w2_employer1"')
filename: str = Field(..., description="Filename relative to corpus/")
display_name: str = Field(..., description="Human-readable name shown to agent")
format: str = Field(
mime_type: str = Field(default="", description="MIME type if known")
size_bytes: int = Field(default=0, description="File size in bytes")
doc_type: str = Field(
description: str = Field(default="", description="Brief description of contents")
provenance: str = Field(
skills_required: list[FormatSkill] = Field(
key_fields: list[str] = Field(
⋮----
# Benchmark Case v2
⋮----
class BenchmarkCaseV2(BaseModel)
⋮----
"""A single understand-phase benchmark case (v2, file-based)."""
⋮----
case_id: str
task_name: str
difficulty: Literal["easy", "medium", "hard"]
persona_id: str
⋮----
broad_objective: str
⋮----
# v2: references to real files instead of inline content
provided_files: list[FileRef] = Field(
⋮----
# Processing challenges specific to the file formats in this case
processing_challenges: list[ProcessingChallenge] = Field(
⋮----
# Same gap-detection fields as v1
missing_artifacts: list[MissingContextItem]
gold_retrieval_order: list[str] = Field(
⋮----
why_context_tempts_premature_progress: str = ""
what_bad_model_does: str = ""
what_good_model_does: str = ""
⋮----
scoring_notes: str = ""
multi_hop_chain: list[str] | None = None
⋮----
# v2: aggregate skill requirements
total_skills_required: list[FormatSkill] = Field(
⋮----
# v2: expected processing pipeline
expected_processing_order: list[str] = Field(
````

## File: rlm_adk/eval/understand_bench_v2/workflow.py
````python
"""Tax-preparation workflow decomposition for v2.

Same workflow as v1 but annotated with format-processing skill
requirements at each step, reflecting the multi-format reality
of v2 benchmark cases.
"""
⋮----
class WorkflowStepV2(BaseModel)
⋮----
"""A single step in the tax-preparation workflow (v2)."""
⋮----
step_number: int
name: str
description: str = ""
dependencies: list[str] = Field(default_factory=list)
potential_gaps: list[str] = Field(default_factory=list)
depends_on_steps: list[int] = Field(default_factory=list)
typical_formats: list[str] = Field(
skills_needed: list[FormatSkill] = Field(
⋮----
TAX_WORKFLOW_V2: list[WorkflowStepV2] = [
````

## File: rlm_adk/eval/queries.py
````python
"""Evaluation query functions for comparing and analyzing session traces.

All functions operate through a TraceReader instance and return structured
dataclass instances suitable for programmatic consumption by evaluation agents.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
@dataclass
class InvocationTrace
⋮----
"""Structured representation of a single invocation within a session.

    An invocation corresponds to one user turn: all events sharing the
    same invocation_id.
    """
⋮----
invocation_id: str
events: list[dict[str, Any]]
state_deltas: list[dict[str, Any]]
timestamp_start: float
timestamp_end: float
author_sequence: list[str]
token_usage: dict[str, int] = field(default_factory=dict)
⋮----
@dataclass
class DivergencePoint
⋮----
"""A point where two sessions' trajectories diverge.

    Attributes:
        invocation_index: 0-based index of the invocation where divergence occurs.
        invocation_id_a: Invocation ID from session A at the divergence point.
        invocation_id_b: Invocation ID from session B at the divergence point.
        reason: Human-readable description of why divergence was detected.
        details: Additional context (e.g., differing state keys, different authors).
    """
⋮----
invocation_index: int
invocation_id_a: str
invocation_id_b: str
reason: str
details: dict[str, Any] = field(default_factory=dict)
⋮----
@dataclass
class SessionComparison
⋮----
"""Side-by-side comparison of two session trajectories.

    Attributes:
        session_id_a: First session ID.
        session_id_b: Second session ID.
        traces_a: List of InvocationTrace for session A.
        traces_b: List of InvocationTrace for session B.
        divergence_points: List of DivergencePoint instances.
        summary: Dict with high-level comparison metrics.
    """
⋮----
session_id_a: str
session_id_b: str
traces_a: list[InvocationTrace]
traces_b: list[InvocationTrace]
divergence_points: list[DivergencePoint]
summary: dict[str, Any] = field(default_factory=dict)
⋮----
"""Extract structured invocation-level traces from a session.

    Groups events by invocation_id and extracts state deltas, author
    sequences, and timing information from each invocation.

    Args:
        reader: An open TraceReader instance.
        app_name: Application name.
        user_id: User ID.
        session_id: Session ID.

    Returns:
        List of InvocationTrace objects, ordered chronologically.
    """
invocation_ids = reader.get_invocation_ids(app_name, user_id, session_id)
traces = []
⋮----
events = reader.get_events_raw(
⋮----
state_deltas: list[dict[str, Any]] = []
authors: list[str] = []
token_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
⋮----
ed = evt.get("event_data", {})
⋮----
ed = json.loads(ed)
⋮----
ed = {}
⋮----
# Extract state_delta from event_data.actions.state_delta
actions = ed.get("actions", {})
⋮----
sd = actions.get("state_delta")
⋮----
# Extract author
author = ed.get("author", "unknown")
⋮----
# Extract token usage from usage_metadata if present
usage = ed.get("usage_metadata", {})
⋮----
trace = InvocationTrace(
⋮----
"""Find invocations where two sessions' trajectories diverge.

    Compares sessions invocation-by-invocation. Divergence is detected when:
    1. Author sequences differ at the same invocation index.
    2. State delta keys differ at the same invocation index.
    3. One session has more invocations than the other (length mismatch).

    Args:
        reader: An open TraceReader instance.
        app_name: Application name.
        user_id: User ID.
        session_id_a: First session ID.
        session_id_b: Second session ID.

    Returns:
        List of DivergencePoint objects, ordered by invocation_index.
    """
traces_a = get_session_traces(reader, app_name, user_id, session_id_a)
traces_b = get_session_traces(reader, app_name, user_id, session_id_b)
⋮----
divergences: list[DivergencePoint] = []
min_len = min(len(traces_a), len(traces_b))
⋮----
ta = traces_a[idx]
tb = traces_b[idx]
⋮----
# Check author sequence divergence
⋮----
# Check state delta key divergence
keys_a: set[str] = set()
⋮----
keys_b: set[str] = set()
⋮----
# Length mismatch
⋮----
"""Full side-by-side comparison of two session trajectories.

    Combines get_session_traces() and get_divergence_points() into a
    single structured comparison with summary metrics.

    Args:
        reader: An open TraceReader instance.
        app_name: Application name.
        user_id: User ID.
        session_id_a: First session ID.
        session_id_b: Second session ID.

    Returns:
        SessionComparison with traces, divergence points, and summary.
    """
⋮----
divergences = get_divergence_points(
⋮----
# Compute summary metrics
total_tokens_a = sum(
total_tokens_b = sum(
⋮----
duration_a = (
duration_b = (
⋮----
summary = {
````

## File: rlm_adk/eval/session_fork.py
````python
"""Session forking for evaluation agents.

Provides fork_session() which creates a new session from an existing one,
copying events up to a specified invocation point. This enables trajectory
exploration without modifying the original session.

Pattern:
1. Identify divergence point (via eval/queries.py)
2. Fork original session at that point
3. Re-execute agent on the forked session with modified parameters
4. Compare original vs forked trajectories
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
"""Fork a session at a specific invocation point.

    Creates a new session with events copied from the source session up to
    (but not including) the specified invocation. The original session is
    unchanged.

    Args:
        session_service: The session service to use for both reading the
            source and creating the fork.
        app_name: Application name.
        user_id: User ID.
        source_session_id: ID of the session to fork from.
        fork_before_invocation_id: Fork point. Events with this invocation_id
            and later are NOT copied. Events before this point ARE copied.
        new_session_id: Optional explicit ID for the new session. If None,
            the session service generates a UUID.
        state_overrides: Optional dict of state keys to override in the
            forked session's initial state. Applied after copying events.

    Returns:
        The new (forked) session's ID.

    Raises:
        ValueError: If source session not found or invocation_id not found.
    """
# 1. Load the source session with all events
source = await session_service.get_session(
⋮----
# 2. Find the fork point
fork_index = None
⋮----
fork_index = i
⋮----
events_to_copy = source.events[:fork_index]
⋮----
# 3. Create new session
new_session = await session_service.create_session(
⋮----
# 4. Replay events into the new session
⋮----
# 5. Apply state overrides if provided
⋮----
last_inv_id = (
override_event = Event(
````

## File: rlm_adk/models/__init__.py
````python

````

## File: rlm_adk/models/litellm_router.py
````python
"""LiteLLM Router integration for RLM-ADK.

Provides RouterLiteLlmClient (drop-in LiteLLMClient replacement that delegates
to litellm.Router) and helper functions to build model lists from env vars.

Gated by RLM_ADK_LITELLM=1 env var at the call site (agent.py).
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
_litellm = None
_Router = None
⋮----
def _ensure_litellm()
⋮----
_litellm = _lit
_Router = _R
⋮----
class RouterLiteLlmClient(LiteLLMClient)
⋮----
"""LiteLLMClient subclass that routes through litellm.Router.

    Inherits from ADK's ``LiteLLMClient`` so Pydantic ``isinstance`` checks
    pass when injected via ``LiteLlm(llm_client=...)``.
    """
⋮----
router_kwargs: dict[str, Any] = {
⋮----
async def acompletion(self, model: str, messages: list, tools: Any, **kwargs: Any) -> Any
⋮----
# ---------------------------------------------------------------------------
# Provider configurations
⋮----
_PROVIDER_CONFIGS: list[tuple[str, str, list[tuple[str, str, dict[str, Any]]]]] = [
⋮----
def _build_openrouter_config() -> tuple[str, str, list[tuple[str, str, dict[str, Any]]]] | None
⋮----
"""Build OpenRouter provider config dynamically from env vars.

    Returns None if OPENROUTER_API_KEY is not set.
    Models are configurable via:
    - RLM_OPENROUTER_REASONING_MODEL (default: google/gemini-2.5-pro-preview)
    - RLM_OPENROUTER_WORKER_MODEL (default: google/gemini-2.5-flash-preview)
    """
⋮----
reasoning_model = os.environ.get(
worker_model = os.environ.get("RLM_OPENROUTER_WORKER_MODEL", "anthropic/claude-sonnet-4.6")
⋮----
"""Build a LiteLLM Router model list from environment variables.

    Each provider is included only if its API key env var is set.

    When ``RLM_LITELLM_PROVIDER`` is set (e.g. "openrouter"), only
    deployments whose prefix starts with that provider are included.
    """
configs: list[tuple[str, str, list[tuple[str, str, dict[str, Any]]]]] = list(
# Include dynamically-built OpenRouter config
or_config = _build_openrouter_config()
⋮----
provider_filter = os.environ.get("RLM_LITELLM_PROVIDER", "").strip().lower()
⋮----
# Parse OpenRouter fallback models
fallback_raw = os.environ.get("RLM_OPENROUTER_FALLBACK_MODELS", "").strip()
fallback_models: list[str] = (
⋮----
fallback_models = fallback_models[:3]
⋮----
model_list: list[dict[str, Any]] = []
⋮----
api_key = os.environ.get(env_var)
⋮----
# Apply provider filter: prefix is e.g. "openrouter/", filter is e.g. "openrouter"
⋮----
litellm_params: dict[str, Any] = {
# Attach OpenRouter native fallback if configured
⋮----
# Singleton client (CRIT-2: thread-safe with double-checked locking)
⋮----
_cached_client: RouterLiteLlmClient | None = None
_client_lock = threading.Lock()
⋮----
"""Return the singleton RouterLiteLlmClient, creating it if necessary.

    Uses double-checked locking (CRIT-2) for thread safety under
    concurrent asyncio.gather / threading scenarios.

    Raises RuntimeError if the resolved model list is empty (CRIT-4).
    """
⋮----
# Double-check inside lock
⋮----
model_list = build_model_list()
⋮----
# Read env var overrides (CRIT-3)
routing_strategy = os.environ.get("RLM_LITELLM_ROUTING_STRATEGY", "simple-shuffle")
num_retries = int(os.environ.get("RLM_LITELLM_NUM_RETRIES", "2"))
cooldown_time = int(os.environ.get("RLM_LITELLM_COOLDOWN_TIME", "60"))
timeout_str = os.environ.get("RLM_LITELLM_TIMEOUT")
timeout = int(timeout_str) if timeout_str else None
⋮----
_cached_client = RouterLiteLlmClient(
⋮----
# Factory
⋮----
"""Create an ADK ``LiteLlm`` model backed by the singleton Router.

    Args:
        logical_name: Logical tier name (e.g. "reasoning", "worker").
            Must match a ``model_name`` in the Router's model list.
        model_list: Override model list (mainly for testing).
        **router_kwargs: Extra kwargs forwarded to Router construction.
    """
⋮----
client = _get_or_create_client(model_list=model_list, **router_kwargs)
````

## File: rlm_adk/plugins/cache.py
````python
"""CachePlugin - Global LLM response cache using intervene pattern.

Trigger points: before_model_callback (check), after_model_callback (store)
State keys: cache:store, cache:hit_count, cache:miss_count, cache:last_hit_key
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
# State key for passing fingerprint from before_model to after_model
_CACHE_PENDING_FP = "cache_pending_fingerprint"
⋮----
class CachePlugin(BasePlugin)
⋮----
"""Caches LLM responses by request fingerprint.

    - before_model_callback: Check cache. If hit, return cached response (intervene).
      Also stores fingerprint in temp state for after_model_callback.
    - after_model_callback: Store response in cache using the pending fingerprint.
    """
⋮----
"""Check cache for matching request. Store fingerprint for after_model."""
⋮----
state = callback_context.state
fingerprint = _fingerprint(llm_request)
⋮----
# Always store fingerprint so after_model_callback can use it
⋮----
cache_store: dict = state.get(CACHE_STORE, {})
⋮----
entry = cache_store[fingerprint]
⋮----
"""Store response in cache after successful model call."""
⋮----
pending_fp = state.get(_CACHE_PENDING_FP)
⋮----
# LRU eviction if over capacity
⋮----
sorted_keys = sorted(
⋮----
def _fingerprint(llm_request: LlmRequest) -> str
⋮----
"""Generate cache key from LlmRequest.

    Key format: SHA-256(model || prompt_normalized || system_instruction_hash || temperature)
    """
parts: list[str] = []
⋮----
# Model name
model = (llm_request.model or "").lower().strip()
⋮----
# Prompt content - concatenate all text parts
content_text = ""
⋮----
# System instruction hash
sys_instruction = ""
⋮----
si = getattr(llm_request.config, "system_instruction", None)
⋮----
sys_instruction = str(si)
⋮----
# Temperature
temperature = 0.0
⋮----
temp = getattr(llm_request.config, "temperature", None)
⋮----
temperature = float(temp)
⋮----
combined = "||".join(parts)
⋮----
def _serialize_response(llm_response: LlmResponse) -> dict
⋮----
"""Serialize LlmResponse to JSON-safe dict."""
⋮----
text = ""
⋮----
def _deserialize_response(data: dict) -> LlmResponse
⋮----
"""Deserialize cached response back to LlmResponse."""
text = data.get("text", "")
````

## File: rlm_adk/plugins/dashboard_auto_launch.py
````python
"""Managed auto-launch for the NiceGUI dashboard."""
⋮----
logger = logging.getLogger(__name__)
⋮----
DASHBOARD_ACTIVE_ENV = "RLM_ADK_DASHBOARD_ACTIVE"
DASHBOARD_FINGERPRINT_ENV = "RLM_ADK_DASHBOARD_FINGERPRINT"
DASHBOARD_INSTANCE_FILE_ENV = "RLM_ADK_DASHBOARD_INSTANCE_FILE"
DISABLE_AUTOLAUNCH_ENV = "RLM_ADK_DISABLE_DASHBOARD_AUTOLAUNCH"
PLAYWRIGHT_DASHBOARD_DEV_ENV = "RLM_DASHBOARD_DEV"
PLAYWRIGHT_DASHBOARD_DEV_ALIAS_ENV = "DASHBOARD_DEV"
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8080/live"
DEFAULT_DASHBOARD_PORT = 8080
⋮----
def repo_root() -> Path
⋮----
def dashboard_instance_file_path(repo_root_path: str | Path | None = None) -> Path
⋮----
root = Path(repo_root_path).expanduser().resolve() if repo_root_path else repo_root()
⋮----
dashboard_dir = root / "rlm_adk" / "dashboard"
paths = sorted(dashboard_dir.rglob("*.py"))
⋮----
digest = hashlib.sha256()
path_list = (
⋮----
@dataclass(frozen=True)
class DashboardInstanceRecord
⋮----
pid: int
port: int
url: str
fingerprint: str
started_at: str
log_path: str
⋮----
@classmethod
    def from_path(cls, path: Path) -> DashboardInstanceRecord | None
⋮----
payload = json.loads(path.read_text())
⋮----
def write_to(self, path: Path) -> None
⋮----
@dataclass(frozen=True)
class DashboardLaunchPlan
⋮----
action: str
reason: str
target_pid: int | None = None
⋮----
def dashboard_command_matches(command: str | None) -> bool
⋮----
normalized = " ".join(command.split())
⋮----
def process_command_for_pid(pid: int | None) -> str | None
⋮----
result = subprocess.run(
⋮----
command = result.stdout.strip()
⋮----
def listening_pid_for_port(port: int) -> int | None
⋮----
text = result.stdout.strip()
⋮----
def pid_exists(pid: int | None) -> bool
⋮----
def dashboard_url_responding(url: str, *, timeout: float = 1.0) -> bool
⋮----
def dashboard_log_reports_ready(log_path: str | Path, base_url: str) -> bool
⋮----
text = Path(log_path).read_text()
⋮----
live_port_is_dashboard = dashboard_command_matches(live_port_command)
managed_pid = instance_record.pid if instance_record else None
managed_port_matches = instance_record is not None and instance_record.port == dashboard_port
managed_pid_live = managed_pid is not None and managed_pid == live_port_pid and live_port_is_dashboard
⋮----
class DashboardAutoLaunchPlugin(BasePlugin)
⋮----
"""Spawn the managed dashboard launcher once per process when a run starts."""
⋮----
_launch_lock = threading.Lock()
_launch_attempted = False
⋮----
def _should_skip(self) -> bool
⋮----
__all__ = [
````

## File: rlm_adk/plugins/google_cloud_analytics.py
````python
"""GoogleCloudAnalyticsPlugin - Exports session summaries to BigQuery Agent Analytics.

This plugin bridges ADK observability (obs: prefixed state keys) to the
official Google BigQuery Agent Analytics plugin. It ensures session
summaries are formatted correctly and sent to the cloud upon run completion.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class GoogleCloudAnalyticsPlugin(BasePlugin)
⋮----
"""Bridge to BigQueryAgentAnalyticsPlugin for cloud telemetry."""
⋮----
def _init_bq_plugin(self) -> None
⋮----
"""One-time initialization of the official BigQueryAgentAnalyticsPlugin."""
⋮----
"""Delegate to BigQueryAgentAnalyticsPlugin to send the final session summary."""
⋮----
# BigQueryAgentAnalyticsPlugin typically implements after_run_callback
# to extract obs: keys from session state and send them.
⋮----
@property
    def enabled(self) -> bool
````

## File: rlm_adk/plugins/google_cloud_tracing.py
````python
"""GoogleCloudTracingPlugin - OpenTelemetry tracing to Google Cloud Trace.

This plugin configures the OpenTelemetry SDK to export spans to Google Cloud
Trace using the CloudTraceSpanExporter. It instruments the Google ADK
automatically to capture agent calls, tool invocations, and model interactions.

This works alongside local tracing (SqliteTracingPlugin) and Langfuse.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
_INSTRUMENTED = False
⋮----
def _init_cloud_trace_instrumentation() -> bool
⋮----
"""One-time initialization of Cloud Trace + GoogleADK OTel instrumentation."""
⋮----
# Check if project ID is available
project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
⋮----
# Ensure a TracerProvider is set. If one already exists (e.g. from Langfuse),
# we add our exporter to it if possible, otherwise we set a new one.
provider = trace.get_tracer_provider()
⋮----
provider = TracerProvider()
⋮----
# Add Cloud Trace exporter
exporter = CloudTraceSpanExporter(project_id=project_id)
⋮----
# Instrument Google ADK with OpenInference (idempotent)
⋮----
_INSTRUMENTED = True
⋮----
class GoogleCloudTracingPlugin(BasePlugin)
⋮----
"""ADK Plugin that enables Google Cloud Trace OpenTelemetry tracing."""
⋮----
def __init__(self, *, name: str = "google_cloud_tracing")
⋮----
@property
    def enabled(self) -> bool
````

## File: rlm_adk/plugins/langfuse_tracing.py
````python
"""LangfuseTracingPlugin - OpenTelemetry-based tracing to self-hosted Langfuse.

Initializes the Langfuse client and Google ADK OpenInference instrumentor
so that every model call, tool invocation, and agent transition is captured
as an OTel span and forwarded to Langfuse automatically.

The plugin is a thin wrapper: all actual tracing is handled by the
``openinference-instrumentation-google-adk`` package.  This plugin simply
ensures initialization happens once and in the right order.

Requires environment variables:
    LANGFUSE_PUBLIC_KEY  - Project public key
    LANGFUSE_SECRET_KEY  - Project secret key
    LANGFUSE_BASE_URL    - Self-hosted Langfuse URL (e.g. http://localhost:3100)
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
_INSTRUMENTED = False
⋮----
def _init_langfuse_instrumentation() -> bool
⋮----
"""One-time initialization of Langfuse + GoogleADK OTel instrumentation.

    Returns True if instrumentation was successfully initialized.
    """
⋮----
public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
secret_key = os.getenv("LANGFUSE_SECRET_KEY")
base_url = os.getenv("LANGFUSE_BASE_URL")
⋮----
# Authenticate the Langfuse client
client = get_client()
⋮----
# Instrument Google ADK with OpenInference
⋮----
_INSTRUMENTED = True
⋮----
class LangfuseTracingPlugin(BasePlugin)
⋮----
"""ADK Plugin that enables Langfuse OpenTelemetry tracing.

    All actual span creation is handled automatically by the
    ``GoogleADKInstrumentor``.  This plugin's role is to:

    1. Trigger one-time initialization of the instrumentor.
    2. Provide a clean on/off toggle via the plugin system.
    3. Log whether tracing is active for operational visibility.

    The plugin is safe to include even when Langfuse env vars are not set:
    initialization is skipped with a warning and no callbacks fire.
    """
⋮----
def __init__(self, *, name: str = "langfuse_tracing")
⋮----
@property
    def enabled(self) -> bool
````

## File: rlm_adk/plugins/step_mode.py
````python
"""Plugin that pauses before each model call when step mode is active."""
⋮----
class StepModePlugin(BasePlugin)
⋮----
"""Global plugin that pauses before each model call when step mode is active."""
⋮----
def __init__(self) -> None
⋮----
"""If step mode is active, block here until the user advances."""
⋮----
# Extract agent name and depth from callback context
agent_name = ""
depth = 0
⋮----
agent = callback_context._invocation_context.agent
agent_name = getattr(agent, "name", "")
match = re.search(r"_d(\d+)", agent_name)
depth = int(match.group(1)) if match else 0
````

## File: rlm_adk/skills/obsolete/repl_skills/__init__.py
````python
"""Expandable REPL skill modules."""
````

## File: rlm_adk/skills/obsolete/repl_skills/ping.py
````python
"""Expandable REPL skill: recursive ping.

Registers source-expandable exports at import time so
``from rlm_repl_skills.ping import run_recursive_ping`` expands into
inline source before the AST rewriter runs.
"""
⋮----
# ---------------------------------------------------------------------------
# Constants
⋮----
_PING_TERMINAL_PAYLOAD_SRC = (
⋮----
_PING_REASONING_LAYER_1_SRC = (
⋮----
_PING_REASONING_LAYER_2_SRC = (
⋮----
_RECURSIVE_PING_RESULT_SRC = """\
⋮----
_BUILD_RECURSIVE_PING_PROMPT_SRC = """\
⋮----
_RUN_RECURSIVE_PING_SRC = """\
⋮----
# Registration (side-effect at import time)
````

## File: rlm_adk/skills/obsolete/repl_skills/repomix.py
````python
"""Expandable REPL skill: repomix helpers.

Registers source-expandable exports at import time so
``from rlm_repl_skills.repomix import probe_repo`` (etc.) expands into
inline source before the AST rewriter runs.

Source strings extracted from repomix_helpers.py.
"""
⋮----
_MODULE = "rlm_repl_skills.repomix"
⋮----
# ---------------------------------------------------------------------------
# Preamble: repomix package imports (executed once at expansion time)
⋮----
_REPOMIX_IMPORTS_SRC = """\
⋮----
# Dataclasses
⋮----
_PROBE_RESULT_SRC = """\
⋮----
_SHARD_RESULT_SRC = """\
⋮----
# Helper functions
⋮----
_MAKE_CONFIG_SRC = """\
⋮----
_IS_REMOTE_SRC = """\
⋮----
# Main functions
⋮----
_PROBE_REPO_SRC = '''\
⋮----
_PACK_REPO_SRC = '''\
⋮----
_SHARD_REPO_SRC = '''\
⋮----
# Registration (side-effect at import time)
````

## File: rlm_adk/skills/obsolete/research/sources/substack/__init__.py
````python

````

## File: rlm_adk/skills/obsolete/research/sources/substack/client.py
````python
"""Substack client with lazy cookie extraction and self-healing auth.

Cookie extraction pipeline:
  1. Try browser-cookie3 to read Chrome's cookie DB
  2. On failure, pip-upgrade browser-cookie3 and retry once
  3. On second failure, fall back to public-only API (no paywalled content)
"""
⋮----
log = logging.getLogger(__name__)
⋮----
_COOKIE_NAMES = ("substack.sid", "substack.lli")
_COOKIE_CACHE_PATH = Path.home() / ".config" / "substack" / "cookies.json"
⋮----
def _extract_cookies_from_chrome() -> list[dict[str, Any]] | None
⋮----
"""Extract Substack cookies from Chrome's local cookie store."""
⋮----
cj = browser_cookie3.chrome(domain_name=".substack.com")
cookies = []
⋮----
def _upgrade_browser_cookie3() -> bool
⋮----
"""Pip-upgrade browser-cookie3 in the current venv. Returns True on success."""
⋮----
result = subprocess.run(
⋮----
# Force reimport of the upgraded module
⋮----
def _extract_with_retry() -> list[dict[str, Any]] | None
⋮----
"""Try cookie extraction, upgrade browser-cookie3 on failure, retry once."""
cookies = _extract_cookies_from_chrome()
⋮----
def _save_cookie_cache(cookies: list[dict[str, Any]]) -> None
⋮----
def _load_cookie_cache() -> list[dict[str, Any]] | None
⋮----
cookies = json.loads(_COOKIE_CACHE_PATH.read_text())
⋮----
class SubstackClient
⋮----
"""Substack client with lazy auth and graceful degradation.

    Auth is resolved on first use, not at construction time.
    Paywalled content requires Chrome to be available for cookie extraction.
    Public content (posts, metadata, subscriptions) works without auth.
    """
⋮----
def __init__(self, username: str) -> None
⋮----
def _resolve_auth(self) -> SubstackAuth | None
⋮----
"""Lazy auth: extract cookies on first access, cache for process lifetime."""
⋮----
# Try fresh extraction from Chrome
cookies = _extract_with_retry()
⋮----
# Fall back to cached cookies
cached = _load_cookie_cache()
⋮----
@property
    def authenticated(self) -> bool
⋮----
def get_user(self) -> User
⋮----
def get_subscriptions(self) -> list[dict[str, Any]]
⋮----
"""Get subscriptions. Uses authenticated endpoint when available.

        The public profile API hides some paid subscriptions.
        The authenticated /api/v1/subscriptions endpoint returns the full list.
        """
auth = self._resolve_auth()
⋮----
resp = auth.get("https://substack.com/api/v1/subscriptions")
⋮----
data = resp.json()
pubs = {p["id"]: p for p in data.get("publications", [])}
results = []
⋮----
pub = pubs.get(s.get("publication_id"), {})
domain = (
⋮----
# Fallback to public API (incomplete for paid subs)
⋮----
def get_newsletter(self, url: str) -> Newsletter
⋮----
def get_post(self, url: str) -> Post
⋮----
def get_post_content(self, post_url: str) -> str
⋮----
"""Fetch full HTML content of a post. Auth enables paywalled access."""
content = self.get_post(post_url).get_content()
⋮----
def get_post_metadata(self, post_url: str) -> dict[str, Any]
⋮----
def get_recent_posts(self, newsletter_url: str, limit: int = 10) -> list[Post]
````

## File: rlm_adk/skills/obsolete/research/sources/substack/test_auth.py
````python
#!/usr/bin/env python3
"""Test script: authenticate and print subscriptions, then fetch a paywalled post.

Usage:
    python test_auth.py [username]

    # Default username from env
    SUBSTACK_USERNAME=rawleystanhope python test_auth.py
"""
⋮----
def main() -> None
⋮----
username = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUBSTACK_USERNAME")
⋮----
client = SubstackClient(username)
user = client.get_user()
⋮----
subscriptions = client.get_subscriptions()
⋮----
paid = [s for s in subscriptions if s.get("membership_state") == "subscribed"]
free = [s for s in subscriptions if s.get("membership_state") != "subscribed"]
⋮----
# Test paywalled content if authenticated
⋮----
newsletter_url = f"https://{paid[0]['domain']}"
posts = client.get_recent_posts(newsletter_url, limit=1)
⋮----
meta = posts[0].get_metadata()
content = posts[0].get_content()
````

## File: rlm_adk/skills/obsolete/research/sources/__init__.py
````python

````

## File: rlm_adk/skills/obsolete/research/__init__.py
````python

````

## File: rlm_adk/skills/obsolete/catalog.py
````python
"""Central catalog for prompt-visible RLM skills."""
⋮----
logger = logging.getLogger(__name__)
⋮----
@dataclass(frozen=True)
class PromptSkillRegistration
⋮----
"""Prompt-visible skill definition plus instruction-block builder."""
⋮----
skill: Skill
build_instruction_block: Callable[[], str]
side_effect_modules: tuple[str, ...] = field(default_factory=tuple)
⋮----
@property
    def name(self) -> str
⋮----
@property
    def description(self) -> str
⋮----
# Minimal Skill object for ping (no instruction block, only side-effect registration)
_PING_SKILL = Skill(
⋮----
def _noop_instruction_block() -> str
⋮----
"""Ping skill has no prompt instruction block."""
⋮----
PROMPT_SKILL_REGISTRY: dict[str, PromptSkillRegistration] = {
⋮----
DEFAULT_ENABLED_SKILL_NAMES: tuple[str, ...] = tuple(PROMPT_SKILL_REGISTRY.keys())
⋮----
def collect_skill_objects(enabled_skills: Iterable[str] | None) -> list[Skill]
⋮----
"""Collect ADK Skill objects for enabled skills that have instructions.

    Skills whose ``build_instruction_block()`` returns ``""`` (e.g. ping)
    are filtered out — they have no L2 instructions for ``load_skill`` to return.
    """
names = normalize_enabled_skill_names(enabled_skills)
⋮----
def normalize_enabled_skill_names(enabled_skills: Iterable[str] | None) -> tuple[str, ...]
⋮----
"""Return validated prompt-visible skill names in registry order."""
⋮----
requested = {name for name in enabled_skills}
unknown = sorted(requested - PROMPT_SKILL_REGISTRY.keys())
⋮----
"""Build prompt blocks for the selected prompt-visible skills."""
⋮----
"""Return `(name, description)` tuples for selected prompt-visible skills."""
⋮----
"""Import side-effect modules for enabled skills.

    Each module in ``side_effect_modules`` is imported to trigger
    ``register_skill_export()`` side effects for source-expandable skills.
    Returns the list of imported module paths for logging.
    """
imported: list[str] = []
⋮----
reg = PROMPT_SKILL_REGISTRY[name]
````

## File: rlm_adk/skills/obsolete/polya_narrative_skill.py
````python
"""ADK Skill definition + source-expandable REPL exports: Polya narrative loop.

Defines ``POLYA_NARRATIVE_SKILL`` using ``google.adk.skills.models.Skill`` and
provides ``build_polya_skill_instruction_block()`` which returns the XML
discovery block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_narrative import run_polya_narrative`` expands
into inline source before the AST rewriter runs.

The Polya loop orchestrates four phases per cycle:
  1. UNDERSTAND: Assess the narrative, identify gaps and strengths
  2. PLAN: Create work packets for enrichment (parallel-dispatchable)
  3. IMPLEMENT: Execute work packets via llm_query_batched (fanout)
  4. REFLECT: Evaluate quality, recommend CONTINUE or COMPLETE
"""
⋮----
# ===========================================================================
# ADK Skill definition (prompt discovery)
⋮----
POLYA_NARRATIVE_SKILL = Skill(
⋮----
def build_polya_skill_instruction_block() -> str
⋮----
"""Return the skill discovery XML + full instructions for prompt injection.

    Appended to ``static_instruction`` in :func:`create_reasoning_agent`.
    """
discovery_xml = format_skills_as_xml([POLYA_NARRATIVE_SKILL.frontmatter])
⋮----
# Source-expandable REPL exports (side-effect registration at import time)
⋮----
# ---------------------------------------------------------------------------
# Constants: Phase instructions
⋮----
_POLYA_UNDERSTAND_INSTRUCTIONS_SRC = '''\
⋮----
_POLYA_PLAN_INSTRUCTIONS_SRC = '''\
⋮----
_POLYA_IMPLEMENT_INSTRUCTIONS_SRC = '''\
⋮----
_POLYA_REFLECT_INSTRUCTIONS_SRC = '''\
⋮----
# Result classes
⋮----
_POLYA_PHASE_RESULT_SRC = '''\
⋮----
_POLYA_NARRATIVE_RESULT_SRC = '''\
⋮----
# Prompt builders
⋮----
_BUILD_UNDERSTAND_PROMPT_SRC = '''\
⋮----
_BUILD_PLAN_PROMPT_SRC = '''\
⋮----
_BUILD_IMPLEMENT_PROMPT_SRC = '''\
⋮----
_BUILD_REFLECT_PROMPT_SRC = '''\
⋮----
# Work packet extraction
⋮----
_EXTRACT_WORK_PACKETS_SRC = '''\
⋮----
# Main orchestrator function
⋮----
_RUN_POLYA_NARRATIVE_SRC = '''\
⋮----
# Registration (side-effect at import time)
⋮----
# Phase instruction constants
⋮----
# Work packet extractor
````

## File: rlm_adk/skills/obsolete/polya_understand_t1_workflow.py
````python
"""ADK Skill definition + source-expandable REPL exports: Polya T1 Workflow-First 3-Layer topology.

Defines ``POLYA_UNDERSTAND_T1_WORKFLOW_SKILL`` using ``google.adk.skills.models.Skill``
and provides ``build_polya_understand_t1_workflow_skill_instruction_block()`` which
returns the XML discovery block + usage instructions to append to the reasoning
agent's ``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand_t1_workflow import run_polya_understand_t1_workflow``
expands into inline source before the AST rewriter runs.

T1 Workflow-First 3-Layer Architecture:

  L0 (parent): sees manifest only -> generates workflow steps -> dispatches step assessors -> synthesizes
  L1 (step assessors): each gets one step + context packets -> assesses sufficiency -> optionally dispatches L2
  L2 (chunk assessors, conditional): each gets one chunk + step -> returns PRESENT/ABSENT/RELEVANCE
"""
⋮----
# ===========================================================================
# ADK Skill definition (prompt discovery)
⋮----
POLYA_UNDERSTAND_T1_WORKFLOW_SKILL = Skill(
⋮----
def build_polya_understand_t1_workflow_skill_instruction_block() -> str
⋮----
"""Return the skill discovery XML + full instructions for prompt injection."""
discovery_xml = format_skills_as_xml([POLYA_UNDERSTAND_T1_WORKFLOW_SKILL.frontmatter])
⋮----
# Source-expandable REPL exports (side-effect registration at import time)
⋮----
# ---------------------------------------------------------------------------
# Constants: Instruction prompts
⋮----
_T1_WORKFLOW_INSTRUCTIONS_SRC = """\
⋮----
_T1_ASSESS_INSTRUCTIONS_SRC = """\
⋮----
# Result classes
⋮----
_T1_STEP_ASSESSMENT_SRC = """\
⋮----
_T1_CHUNK_ASSESSMENT_SRC = """\
⋮----
_T1_WORKFLOW_RESULT_SRC = """\
⋮----
# Helpers: context preparation, manifest building, and extraction
# (copied from v1 polya_understand for self-contained expansion)
⋮----
_STRINGIFY_CONTEXT_SRC = """\
⋮----
_CHUNK_TEXT_SRC = """\
⋮----
_CONDENSE_PACKETS_SRC = """\
⋮----
_PREPARE_CONTEXT_PACKETS_SRC = """\
⋮----
_BUILD_CONTEXT_MANIFEST_SRC = '''\
⋮----
_EXTRACT_RETRIEVAL_ORDER_SRC = """\
⋮----
# T1-specific prompt builders
⋮----
_BUILD_WORKFLOW_PROMPT_SRC = '''\
⋮----
_PARSE_WORKFLOW_STEPS_SRC = """\
⋮----
_BUILD_STEP_ASSESSMENT_PROMPT_SRC = '''\
⋮----
_BUILD_CHUNK_ASSESSMENT_PROMPT_SRC = """\
⋮----
_PARSE_STEP_ASSESSMENT_SRC = """\
⋮----
_PARSE_CHUNK_ASSESSMENT_SRC = """\
⋮----
_NEEDS_L2_DISPATCH_SRC = """\
⋮----
_BUILD_SYNTHESIS_PROMPT_SRC = '''\
⋮----
# Main orchestrator function
⋮----
_RUN_POLYA_UNDERSTAND_T1_WORKFLOW_SRC = '''\
⋮----
# Registration (side-effect at import time)
⋮----
_MODULE = "rlm_repl_skills.polya_understand_t1_workflow"
````

## File: rlm_adk/skills/obsolete/polya_understand_t2_flat.py
````python
"""ADK Skill definition + source-expandable REPL exports: T2 Flat Open-Ended topology.

Defines ``POLYA_UNDERSTAND_T2_FLAT_SKILL`` using ``google.adk.skills.models.Skill`` and provides
``build_polya_understand_t2_flat_skill_instruction_block()`` which returns the XML discovery
block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand_t2_flat import run_polya_understand_t2_flat``
expands into inline source before the AST rewriter runs.

T2 Flat Open-Ended topology:
  L0 sees FULL context (key departure from v1). Generates open-ended probing
  questions locally (no LLM call), dispatches Q investigation children via
  ``llm_query_batched()``, then 1 synthesis child via ``llm_query()``.
  Total: Q+1 calls, no cycles.
"""
⋮----
# ===========================================================================
# ADK Skill definition (prompt discovery)
⋮----
POLYA_UNDERSTAND_T2_FLAT_SKILL = Skill(
⋮----
def build_polya_understand_t2_flat_skill_instruction_block() -> str
⋮----
"""Return the skill discovery XML + full instructions for prompt injection."""
discovery_xml = format_skills_as_xml([POLYA_UNDERSTAND_T2_FLAT_SKILL.frontmatter])
⋮----
# Source-expandable REPL exports (side-effect registration at import time)
⋮----
_MODULE = "rlm_repl_skills.polya_understand_t2_flat"
⋮----
# ---------------------------------------------------------------------------
# Constants: T2 Flat instructions
⋮----
_T2_FLAT_INSTRUCTIONS_SRC = """\
⋮----
# Result class
⋮----
_T2_FLAT_RESULT_SRC = """\
⋮----
# Helpers: context preparation
⋮----
_STRINGIFY_CONTEXT_SRC = """\
⋮----
_BUILD_CONTEXT_STRING_SRC = """\
⋮----
# Question generation (local heuristic, no LLM call)
⋮----
_GENERATE_PROBING_QUESTIONS_SRC = '''\
⋮----
# Prompt builders
⋮----
_BUILD_INVESTIGATION_PROMPT_SRC = '''\
⋮----
_BUILD_SYNTHESIS_PROMPT_SRC = '''\
⋮----
# Extraction helpers
⋮----
_EXTRACT_VERDICT_SRC = """\
⋮----
_EXTRACT_GAPS_SRC = """\
⋮----
_EXTRACT_COVERAGE_SRC = """\
⋮----
_EXTRACT_UNDERSTANDING_SRC = """\
⋮----
# Main entry point
⋮----
_RUN_POLYA_UNDERSTAND_T2_FLAT_SRC = '''\
⋮----
# Registration (side-effect at import time)
````

## File: rlm_adk/skills/obsolete/polya_understand_t3_adaptive.py
````python
"""ADK Skill definition + source-expandable REPL exports: T3 Dimension-Adaptive Round-Trip.

Defines ``POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL`` using ``google.adk.skills.models.Skill``
and provides ``build_polya_understand_t3_adaptive_skill_instruction_block()`` which
returns the XML discovery block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand_t3_adaptive import run_polya_understand_t3_adaptive``
expands into inline source before the AST rewriter runs.

T3 Architecture (Dimension-Adaptive Round-Trip):

  L0: SELECT (llm_query) -> selects 3-5 relevant Polya dimensions
  L0: PROBE round 1 (llm_query_batched) -> one child per selected dimension
      Each gets: dimension question + context packet
      Returns: DIMENSION/EVIDENCE/GAPS/CONFIDENCE
  L0: GAP ANALYSIS (local Python) -> parse CONFIDENCE, identify low-confidence dims
  L0: RE-PROBE round 2 (llm_query_batched, conditional) -> only gap dimensions
  L0: SYNTHESIZE (llm_query) -> combine round 1 + round 2 results
"""
⋮----
# ===========================================================================
# ADK Skill definition (prompt discovery)
⋮----
POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL = Skill(
⋮----
def build_polya_understand_t3_adaptive_skill_instruction_block() -> str
⋮----
"""Return the skill discovery XML + full instructions for prompt injection."""
discovery_xml = format_skills_as_xml([POLYA_UNDERSTAND_T3_ADAPTIVE_SKILL.frontmatter])
⋮----
# Source-expandable REPL exports (side-effect registration at import time)
⋮----
# ---------------------------------------------------------------------------
# Constants: Polya dimension definitions (self-contained copy)
⋮----
_POLYA_DIMENSIONS_SRC = """\
⋮----
# Constants: T3-specific phase instructions
⋮----
_T3_SELECT_INSTRUCTIONS_SRC = """\
⋮----
_T3_PROBE_INSTRUCTIONS_SRC = """\
⋮----
# Result classes
⋮----
_T3_PROBE_RESULT_SRC = """\
⋮----
_T3_ADAPTIVE_RESULT_SRC = """\
⋮----
# Helpers: context preparation, manifest building, and extraction
# (self-contained copies from v1 for independence)
⋮----
_STRINGIFY_CONTEXT_SRC = """\
⋮----
_CHUNK_TEXT_SRC = """\
⋮----
_CONDENSE_PACKETS_SRC = """\
⋮----
_PREPARE_CONTEXT_PACKETS_SRC = """\
⋮----
_BUILD_CONTEXT_MANIFEST_SRC = '''\
⋮----
# T3-specific helpers
⋮----
_ASSIGN_PACKETS_TO_DIMENSIONS_SRC = '''\
⋮----
_EXTRACT_RETRIEVAL_ORDER_SRC = """\
⋮----
# Prompt builders
⋮----
_BUILD_SELECT_PROMPT_SRC = '''\
⋮----
_PARSE_SELECTED_DIMENSIONS_SRC = '''\
⋮----
_BUILD_PROBE_PROMPT_SRC = '''\
⋮----
_PARSE_PROBE_RESPONSE_SRC = '''\
⋮----
_IDENTIFY_GAPS_SRC = """\
⋮----
_BUILD_REPROBE_PROMPT_SRC = '''\
⋮----
_BUILD_SYNTHESIS_PROMPT_SRC = '''\
⋮----
# Main orchestrator function
⋮----
_RUN_POLYA_UNDERSTAND_T3_ADAPTIVE_SRC = '''\
⋮----
# Registration (side-effect at import time)
⋮----
_MODULE = "rlm_repl_skills.polya_understand_t3_adaptive"
⋮----
# --- Constants ---
⋮----
# --- Classes ---
⋮----
# --- Context helpers ---
⋮----
# --- T3-specific functions ---
````

## File: rlm_adk/skills/obsolete/polya_understand_t4_debate.py
````python
"""ADK Skill definition + source-expandable REPL exports: Polya T4 adversarial debate.

Defines ``POLYA_UNDERSTAND_T4_DEBATE_SKILL`` using ``google.adk.skills.models.Skill``
and provides ``build_polya_understand_t4_debate_skill_instruction_block()`` which
returns the XML discovery block + usage instructions to append to the reasoning
agent's ``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand_t4_debate import run_polya_understand_t4_debate``
expands into inline source before the AST rewriter runs.

The T4 topology dispatches 2 advocates (optimist + critic) concurrently via
``llm_query_batched``, then 1 judge via ``llm_query``.  The judge receives
ONLY the advocate arguments, never raw context -- this is the key design
invariant that prevents the judge from anchoring on noisy context artifacts.

Flow:
  1. ADVOCATE phase: ``llm_query_batched([optimist_prompt, critic_prompt])``
  2. JUDGE phase: ``llm_query(judge_prompt)`` -- judge sees only advocate outputs
  3. Parse and return ``T4DebateResult``
"""
⋮----
# ===========================================================================
# ADK Skill definition (prompt discovery)
⋮----
POLYA_UNDERSTAND_T4_DEBATE_SKILL = Skill(
⋮----
def build_polya_understand_t4_debate_skill_instruction_block() -> str
⋮----
"""Return the skill discovery XML + full instructions for prompt injection."""
discovery_xml = format_skills_as_xml(
⋮----
# Source-expandable REPL exports (side-effect registration at import time)
⋮----
_MODULE = "rlm_repl_skills.polya_understand_t4_debate"
⋮----
# ---------------------------------------------------------------------------
# Constants: Advocate + Judge instructions
⋮----
_T4_OPTIMIST_INSTRUCTIONS_SRC = """\
⋮----
_T4_CRITIC_INSTRUCTIONS_SRC = """\
⋮----
_T4_JUDGE_INSTRUCTIONS_SRC = """\
⋮----
# Result classes
⋮----
_T4_OPTIMIST_CASE_SRC = """\
⋮----
_T4_CRITIC_CASE_SRC = """\
⋮----
_T4_VERDICT_SRC = """\
⋮----
_T4_DEBATE_RESULT_SRC = """\
⋮----
# Helpers: context preparation and extraction
⋮----
_STRINGIFY_CONTEXT_SRC = """\
⋮----
_BUILD_CONTEXT_STRING_SRC = """\
⋮----
_BUILD_CONTEXT_MANIFEST_SRC = '''\
⋮----
_EXTRACT_SECTION_SRC = """\
⋮----
_EXTRACT_RETRIEVAL_ORDER_SRC = """\
⋮----
_EXTRACT_CONFIDENCE_MAP_SRC = """\
⋮----
# Prompt builders
⋮----
_BUILD_OPTIMIST_PROMPT_SRC = '''\
⋮----
_BUILD_CRITIC_PROMPT_SRC = '''\
⋮----
_BUILD_JUDGE_PROMPT_SRC = '''\
⋮----
# Response parsers
⋮----
_PARSE_OPTIMIST_RESPONSE_SRC = """\
⋮----
_PARSE_CRITIC_RESPONSE_SRC = """\
⋮----
_PARSE_JUDGE_RESPONSE_SRC = """\
⋮----
# Main orchestrator function
⋮----
_RUN_POLYA_UNDERSTAND_T4_DEBATE_SRC = '''\
⋮----
# Registration (side-effect at import time)
````

## File: rlm_adk/skills/obsolete/polya_understand.py
````python
"""ADK Skill definition + source-expandable REPL exports: Polya understand loop.

Defines ``POLYA_UNDERSTAND_SKILL`` using ``google.adk.skills.models.Skill`` and
provides ``build_polya_understand_skill_instruction_block()`` which returns the
XML discovery block + usage instructions to append to the reasoning agent's
``static_instruction``.

Also registers source-expandable exports at import time so
``from rlm_repl_skills.polya_understand import run_polya_understand`` expands
into inline source before the AST rewriter runs.

The loop is designed for large or incomplete project contexts.  The parent
(layer 0 reasoning agent) acts as a **reframer** that transforms the user's
objective into structured Polya probing questions dispatched to children:

  1. REFRAME: Transform the objective into Polya-structured probing questions
  2. PROBE: Dispatch probing questions via llm_query_batched() to children
  3. SYNTHESIZE: Collect structured responses and build composite understanding
  4. VALIDATE: Judge whether composite understanding is sufficient to proceed
  5. REFLECT: Critique the validation, repair ordering, decide COMPLETE/CONTINUE
"""
⋮----
# ===========================================================================
# ADK Skill definition (prompt discovery)
⋮----
POLYA_UNDERSTAND_SKILL = Skill(
⋮----
def build_polya_understand_skill_instruction_block() -> str
⋮----
"""Return the skill discovery XML + full instructions for prompt injection."""
discovery_xml = format_skills_as_xml([POLYA_UNDERSTAND_SKILL.frontmatter])
⋮----
# Source-expandable REPL exports (side-effect registration at import time)
⋮----
# ---------------------------------------------------------------------------
# Constants: Polya dimension definitions
⋮----
_POLYA_DIMENSIONS_SRC = """\
⋮----
# Constants: Phase instructions
⋮----
_POLYA_REFRAME_INSTRUCTIONS_SRC = """\
⋮----
_POLYA_PROBE_INSTRUCTIONS_SRC = """\
⋮----
_POLYA_SYNTHESIZE_INSTRUCTIONS_SRC = """\
⋮----
_POLYA_VALIDATE_INSTRUCTIONS_SRC = """\
⋮----
_POLYA_REFLECT_INSTRUCTIONS_SRC = """\
⋮----
# Result classes
⋮----
_POLYA_UNDERSTAND_PHASE_RESULT_SRC = """\
⋮----
_POLYA_UNDERSTAND_RESULT_SRC = """\
⋮----
# Helpers: context preparation, manifest building, and extraction
⋮----
_STRINGIFY_CONTEXT_SRC = """\
⋮----
_CHUNK_TEXT_SRC = """\
⋮----
_CONDENSE_PACKETS_SRC = """\
⋮----
_PREPARE_CONTEXT_PACKETS_SRC = """\
⋮----
_BUILD_CONTEXT_MANIFEST_SRC = '''\
⋮----
_EXTRACT_MARKER_VALUE_SRC = """\
⋮----
_EXTRACT_RETRIEVAL_ORDER_SRC = """\
⋮----
# Prompt builders
⋮----
_BUILD_REFRAME_PROMPT_SRC = '''\
⋮----
_BUILD_PROBE_PROMPT_SRC = '''\
⋮----
_BUILD_SYNTHESIZE_PROMPT_SRC = '''\
⋮----
_BUILD_VALIDATE_PROMPT_SRC = '''\
⋮----
_BUILD_REFLECT_PROMPT_SRC = '''\
⋮----
# Helpers: reframe parsing and probe dispatch assembly
⋮----
_PARSE_REFRAMED_QUESTIONS_SRC = '''\
⋮----
_ASSIGN_PACKETS_TO_DIMENSIONS_SRC = '''\
⋮----
# Main orchestrator function
⋮----
_RUN_POLYA_UNDERSTAND_SRC = '''\
⋮----
# Registration (side-effect at import time)
````

## File: rlm_adk/skills/obsolete/repomix_helpers.py
````python
"""Pre-built REPL helper functions for repomix-python.

These functions are injected into the REPL globals so the reasoning agent
can call them directly with zero imports.  They encapsulate the 6+ deep-
subpackage imports, the ``split_output`` dead-code workaround, and the
``repo_url=`` keyword pitfall.
"""
⋮----
@dataclass
class ProbeResult
⋮----
"""Lightweight stats returned by :func:`probe_repo`."""
⋮----
total_files: int
total_chars: int
total_tokens: int
file_tree: dict
file_char_counts: dict[str, int]
file_token_counts: dict[str, int]
⋮----
def __str__(self) -> str
⋮----
@dataclass
class ShardResult
⋮----
"""Result of :func:`shard_repo` containing split chunks."""
⋮----
chunks: list[str]
⋮----
def _make_config(calculate_tokens: bool) -> RepomixConfig
⋮----
"""Build a standard RepomixConfig for XML output."""
config = RepomixConfig()
⋮----
def _is_remote(source: str) -> bool
⋮----
"""Return True if *source* looks like a remote URL."""
⋮----
def probe_repo(source: str, calculate_tokens: bool = True) -> ProbeResult
⋮----
"""Quick stats: file count, token count, file tree.  No full content returned.

    Args:
        source: Local directory path or remote git URL.
        calculate_tokens: Whether to count tokens (slower but useful for
            deciding between single-shot and sharded analysis).

    Returns:
        A :class:`ProbeResult` with file counts, token counts, and tree.
    """
config = _make_config(calculate_tokens)
⋮----
processor = RepoProcessor(repo_url=source, config=config)
⋮----
processor = RepoProcessor(source, config=config)
result = processor.process()
⋮----
def pack_repo(source: str, calculate_tokens: bool = True) -> str
⋮----
"""Pack entire repo into an XML string.  For small repos (<125K tokens).

    Args:
        source: Local directory path or remote git URL.
        calculate_tokens: Whether to count tokens.

    Returns:
        The full packed XML content as a string.
    """
⋮----
"""Pack + split into chunks at directory boundaries.

    For large repos, use the returned ``chunks`` list with
    ``llm_query_batched()`` for concurrent analysis.

    Args:
        source: Local directory path or remote git URL.
        max_bytes_per_shard: Maximum bytes per output chunk (default 500KB).
        calculate_tokens: Whether to count tokens.

    Returns:
        A :class:`ShardResult` with the list of XML chunk strings.
    """
⋮----
# Determine local path — clone if remote
tmp_dir: Path | None = None
⋮----
tmp_dir = create_temp_directory()
⋮----
local_path = str(tmp_dir)
⋮----
local_path = source
⋮----
# Run the file pipeline
search_result = search_files(local_path, config)
raw_files = collect_files(search_result.file_paths, local_path)
processed_files = process_files(raw_files, config)
⋮----
file_char_counts = {pf.path: len(pf.content) for pf in processed_files}
file_token_counts = {pf.path: 0 for pf in processed_files}
all_file_paths = [pf.path for pf in processed_files]
⋮----
parts = generate_split_output_parts(
⋮----
chunks = [part.content for part in parts]
total_chars = sum(len(c) for c in chunks)
total_files = len(processed_files)
total_tokens = sum(file_token_counts.values())
````

## File: rlm_adk/skills/obsolete/repomix_skill.py
````python
"""ADK Skill definition for the repomix REPL helpers.

Defines ``REPOMIX_SKILL`` using ``google.adk.skills.models.Skill`` and
provides ``build_skill_instruction_block()`` which returns the XML discovery
block + full usage instructions to append to the reasoning agent's
``static_instruction``.
"""
⋮----
REPOMIX_SKILL = Skill(
⋮----
def build_skill_instruction_block() -> str
⋮----
"""Return the skill discovery XML + full instructions for prompt injection.

    Appended to ``static_instruction`` in :func:`create_reasoning_agent`.
    """
discovery_xml = format_skills_as_xml([REPOMIX_SKILL.frontmatter])
````

## File: rlm_adk/skills/obsolete/skill_toolset.py
````python
"""RLMSkillToolset — hybrid prompt-injection + tool-use skill discovery.

Implements the ADK SkillToolset pattern locally (upstream doesn't ship one yet):
- L1 discovery: ``process_llm_request`` appends lightweight XML to system_instruction
- L2 on-demand: ``load_skill`` tool call returns full markdown instructions
- State tracking: writes skill activation keys via ``tool_context.state`` (AR-CRIT-001)

Lineage is automatic: sqlite_tracing's ``before_tool_callback`` captures depth,
fanout_idx, branch, invocation_id for all tool calls including ``load_skill``.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class RLMSkillToolset(BaseTool)
⋮----
"""Hybrid skill discovery tool.

    On each LLM request:
      1. Injects L1 XML (``<available_skills>`` block) into ``system_instruction``
      2. Registers a ``load_skill`` function declaration

    When the model calls ``load_skill(skill_name=...)``:
      1. Returns ``{skill_name, instructions, frontmatter}``
      2. Writes ``skill_last_loaded``, ``skill_load_count``, ``skill_loaded_names``
         to ``tool_context.state`` (AR-CRIT-001 compliant)
    """
⋮----
def __init__(self, *, enabled_skills: Iterable[str] | None = None)
⋮----
skills = collect_skill_objects(enabled_skills)
⋮----
def _get_declaration(self) -> types.FunctionDeclaration | None
⋮----
"""OpenAPI spec for the load_skill tool."""
⋮----
"""Inject L1 XML into system_instruction, then register the tool."""
# L1: lightweight frontmatter XML for skill discovery
frontmatters = [s.frontmatter for s in self._skills.values()]
⋮----
xml = format_skills_as_xml(frontmatters)
⋮----
# Register load_skill function declaration via BaseTool default
⋮----
"""Load L2 instructions for the requested skill."""
skill_name = args.get("skill_name", "")
skill = self._skills.get(skill_name)
⋮----
available = sorted(self._skills.keys())
⋮----
# AR-CRIT-001: all state writes via tool_context.state
⋮----
current_count = tool_context.state.get("skill_load_count", 0) or 0
⋮----
current_names = tool_context.state.get("skill_loaded_names") or []
````

## File: rlm_adk/skills/recursive_ping/__init__.py
````python
"""Recursive-ping skill: diagnostic for thread bridge dispatch."""
⋮----
SKILL_EXPORTS = ["run_recursive_ping", "RecursivePingResult"]
````

## File: rlm_adk/skills/recursive_ping/ping.py
````python
"""Recursive ping -- dispatches llm_query at each layer to test thread bridge."""
⋮----
@dataclass
class RecursivePingResult
⋮----
layer: int
prompt: str
response: str
children: list[RecursivePingResult] = field(default_factory=list)
⋮----
"""Recursively dispatch llm_query through thread bridge layers."""
⋮----
child_prompt = f"[layer{starting_layer}] {prompt}"
child_response = llm_query_fn(child_prompt)
````

## File: rlm_adk/skills/test_skill/__init__.py
````python
"""Architecture introspection skill for provider-fake e2e testing."""
⋮----
SKILL_EXPORTS = ["run_test_skill", "TestSkillResult"]
````

## File: rlm_adk/tools/__init__.py
````python

````

## File: rlm_adk/services.py
````python
"""ADK CLI service registry for RLM-ADK.

This module is auto-discovered by ``google.adk.cli.service_registry.load_services_module()``
when ``adk run rlm_adk`` or ``adk web rlm_adk`` is invoked.  It overrides the
built-in ``sqlite`` and ``file`` schemes so the CLI-created Runner gets the same
WAL-pragma'd SQLite session service and file-based artifact service that
``create_rlm_runner()`` provides programmatically — no CLI flags needed.

Registered schemes (override built-ins):
    sqlite://<db_path>  -- SqliteSessionService with WAL mode + performance pragmas
    file://<root_dir>   -- FileArtifactService with the given root directory
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
def _rlm_session_factory(uri: str, **kwargs)
⋮----
"""Create a SqliteSessionService with WAL pragmas from a URI.

    Reuses ``_default_session_service()`` from ``rlm_adk.agent`` to avoid
    duplicating the WAL pragma logic.

    URI format: ``sqlite://<db_path>``
    If no path is provided, falls back to the default path (RLM_SESSION_DB
    env var or ``.adk/session.db``).
    """
⋮----
parsed = urlparse(uri)
# netloc + path gives the full file path after the scheme
db_path = parsed.netloc + parsed.path if (parsed.netloc or parsed.path) else None
# Pass None to let _default_session_service use its own default resolution
⋮----
def _rlm_artifact_factory(uri: str, **kwargs)
⋮----
"""Create a FileArtifactService from a URI.

    URI format: ``file://<root_dir>``
    If no path is provided, falls back to the default ``.adk/artifacts``.
    """
⋮----
root_dir = parsed.netloc + parsed.path if (parsed.netloc or parsed.path) else _DEFAULT_ARTIFACT_ROOT
⋮----
def register_services(registry: ServiceRegistry | None = None) -> None
⋮----
"""Register RLM-ADK service factories in the given (or global) registry.

    Args:
        registry: The ServiceRegistry to register on.  When ``None``,
            uses the global singleton from ``get_service_registry()``.
    """
⋮----
registry = get_service_registry()
⋮----
# Auto-register when this module is imported (ADK CLI discovery path).
````

## File: rlm_adk/step_gate.py
````python
"""Shared in-process async gate primitive for step-mode execution."""
⋮----
class StepGate
⋮----
"""Async gate that blocks agent execution until the user advances."""
⋮----
def __init__(self) -> None
⋮----
async def wait_for_advance(self, *, agent_name: str = "", depth: int = 0) -> None
⋮----
"""Block until the user advances. No-op if step mode is off."""
⋮----
def set_step_mode(self, enabled: bool) -> None
⋮----
"""Toggle step mode on/off. If disabling while a waiter is blocked, release it."""
⋮----
def advance(self) -> None
⋮----
"""Signal the gate to release one blocked waiter."""
⋮----
@property
    def step_mode_enabled(self) -> bool
⋮----
@property
    def waiting(self) -> bool
⋮----
"""True if the gate is currently blocked (plugin is paused)."""
⋮----
@property
    def paused_agent_name(self) -> str | None
⋮----
"""Name of the agent currently blocked at the gate."""
⋮----
@property
    def paused_depth(self) -> int | None
⋮----
"""Depth of the agent currently blocked at the gate."""
⋮----
step_gate = StepGate()
````

## File: rlm_adk/callbacks/__init__.py
````python
"""Callback functions for RLM ADK agents."""
⋮----
__all__ = [
````

## File: rlm_adk/dashboard/components/context_bar.py
````python
"""ECharts stacked horizontal bar for context window visualization.

NiceGUI review corrections applied:
- One series per chunk (not per category) for click identification
- ``:formatter`` (colon prefix) with JS function for tooltip
- ``on_point_click`` constructor parameter on ``ui.echart``
"""
⋮----
def build_context_bar_options(window: ContextWindow) -> dict
⋮----
"""Build ECharts options for a stacked horizontal bar.

    One series per chunk so that ``on_point_click`` can identify
    individual chunks via ``e.series_name`` (= chunk_id).
    """
series = []
total_tokens = sum(c.estimated_tokens for c in window.chunks)
⋮----
# NiceGUI review: use ':formatter' for JS function (colon prefix)
formatter_js = (
````

## File: rlm_adk/dashboard/components/flow_code_pane.py
````python
"""Code cell component for the flow transcript."""
⋮----
# Simple keyword highlighting for Python tokens
_KEYWORDS = {
⋮----
_BUILTIN_NAMES = {
⋮----
"""Render the full code cell with line numbers and syntax highlighting."""
code = cell.code
⋮----
llm_line_set = {info.line_number for info in cell.llm_query_lines}
llm_line_map = {info.line_number: info for info in cell.llm_query_lines}
lines = code.splitlines()
⋮----
# Header bar
⋮----
# Code lines
⋮----
is_llm_line = idx in llm_line_set
⋮----
"""Render a single line of code with gutter and optional llm_query indicator."""
bg = "rgba(87,199,255,0.08)" if is_llm_query else "transparent"
left_border = "3px solid var(--accent-root)" if is_llm_query else "3px solid transparent"
cursor = "pointer" if is_llm_query and on_click else "default"
⋮----
el = ui.element("div").style(
⋮----
# Line number gutter
⋮----
# Code content with basic highlighting
highlighted = _highlight_line(line)
⋮----
# Rightward arrow + Child Agent chip on llm_query lines
⋮----
child_label = "Child Agent"
⋮----
child_label = f"Child Agent (d{llm_info.child_depth}:f{llm_info.child_fanout_idx})"
⋮----
def _highlight_line(line: str) -> str
⋮----
"""Apply simple keyword-based syntax highlighting to a code line."""
escaped = escape(line)
⋮----
# Highlight comments
stripped = escaped.lstrip()
⋮----
indent = escaped[: len(escaped) - len(stripped)]
⋮----
# Single-pass keyword replacement — avoids corrupting spans inserted
# by earlier passes (e.g. "or" inside "for"'s span content).
⋮----
# Build a single combined regex: longest keywords first to prevent
# partial matches (e.g. "llm_query_batched" before "llm_query").
_ALL_TOKENS: dict[str, str] = {}
⋮----
# Group 1 matches HTML entities (skip them). Group 2 matches keywords.
_HIGHLIGHT_RE = _re.compile(
⋮----
r"(&\w+;)"  # group 1: HTML entities like &lt; — skip
⋮----
r"\b(" + "|".join(_re.escape(t) for t in _ALL_TOKENS) + r")\b"  # group 2: keyword
⋮----
def _highlight_replacer(m: _re.Match) -> str
⋮----
if m.group(1):  # HTML entity — pass through unchanged
````

## File: rlm_adk/dashboard/components/flow_connectors.py
````python
"""Flow connectors: directional arrows and inline child agent cards."""
⋮----
# Arrow unicode + color by kind/direction
_ARROW_UNICODE = {
⋮----
_ARROW_COLORS = {
⋮----
_STATUS_COLORS = {
⋮----
def render_flow_arrow(arrow: FlowArrow) -> None
⋮----
"""Render a directional arrow connector between flow blocks."""
color = _ARROW_COLORS.get(arrow.arrow_kind, "var(--text-1)")
unicode_arrow = _ARROW_UNICODE.get(arrow.direction, "\u2193")
⋮----
justify = "center"
⋮----
justify = "flex-start"
⋮----
justify = "flex-end"
⋮----
padding_left = "3.5rem" if arrow.direction == "right" else "0"
padding_right = "3.5rem" if arrow.direction == "left" else "0"
⋮----
"""Render a compact inline child agent card."""
error_border = "var(--accent-child)" if child.error else "var(--border-1)"
error_bg = "rgba(255,107,159,0.10)" if child.error else "rgba(159,176,209,0.06)"
⋮----
# Header: Child Agent label + depth/fanout + status + tokens + elapsed
⋮----
status_color = _STATUS_COLORS.get(child.status, "var(--text-1)")
status_text = "ERROR" if child.error else child.status.upper()
⋮----
# Prompt preview
⋮----
# Result preview
⋮----
# Error message
⋮----
# Action buttons
````

## File: rlm_adk/dashboard/components/flow_reasoning_pane.py
````python
"""Reasoning agent header card for the flow transcript."""
⋮----
_SCOPE_ORDER = [
⋮----
_SCOPE_LABELS = {
⋮----
_STATUS_COLORS = {
⋮----
"""Render the reasoning agent header card."""
⋮----
def _header_row(card: FlowAgentCard) -> None
⋮----
# Agent name
⋮----
# Depth / fanout badge
fanout = "root" if card.fanout_idx is None else f"f{card.fanout_idx}"
⋮----
# Status chip
status_color = _STATUS_COLORS.get(card.status, "var(--text-1)")
⋮----
# Token summary + depth/fanout
⋮----
def _context_rows(card: FlowAgentCard, *, on_open_context) -> None
⋮----
"""Render context items grouped by scope."""
grouped: dict[str, list] = {}
⋮----
items = grouped.get(scope)
⋮----
scope_color = {
⋮----
chip_label = (
bg = {
border = {
text_color = {
⋮----
token_text = "n/a"
⋮----
token_text = f"{item.token_count} tok"
⋮----
token_text = f"~{item.token_count} tok"
chip_label = f"{item.label} ({token_text})"
bg = "rgba(126,240,160,0.16)" if item.present else "rgba(159,176,209,0.08)"
border = "var(--accent-active)" if item.present else "var(--border-1)"
text_color = "var(--accent-active)" if item.present else "var(--text-1)"
⋮----
el = ui.element("div").style(
````

## File: rlm_adk/dashboard/components/flow_transcript.py
````python
"""Main flow transcript renderer — dispatches to component render functions."""
⋮----
# Graceful imports — works with partial merges
⋮----
except ImportError:  # pragma: no cover
render_flow_reasoning_pane = None  # type: ignore[assignment]
⋮----
render_flow_code_pane = None  # type: ignore[assignment]
⋮----
render_flow_arrow = None  # type: ignore[assignment]
render_flow_child_card = None  # type: ignore[assignment]
⋮----
render_flow_output_cell = None  # type: ignore[assignment]
⋮----
render_flow_context_inspector = None  # type: ignore[assignment]
⋮----
render_flow_tool_call_cell = None  # type: ignore[assignment]
⋮----
"""Render the complete flow transcript as a scrollable notebook."""
⋮----
"""Dispatch to the appropriate component render function."""
kind = block.kind
⋮----
block,  # type: ignore[arg-type]
⋮----
render_flow_arrow(block)  # type: ignore[arg-type]
⋮----
render_flow_output_cell(block)  # type: ignore[arg-type]
⋮----
render_flow_tool_call_cell(block)  # type: ignore[arg-type]
⋮----
# Fallback: show block kind label
````

## File: rlm_adk/dashboard/components/header.py
````python
"""Header bar with title and session selector."""
⋮----
"""Render the header bar with title and session selector dropdown.

    NiceGUI review corrections applied:
    - ui.select uses ``on_change``, ``with_input=True``, ``value=current``
    """
⋮----
sessions = controller.state.available_sessions
current = controller.state.selected_session_id
⋮----
async def handle_change(e: Any) -> None
````

## File: rlm_adk/dashboard/components/live_context_banner.py
````python
"""Pinned context banner for the live dashboard."""
⋮----
_SCOPE_ORDER = [
⋮----
_SCOPE_LABELS = {
⋮----
"""Render grouped banner chips for the active pane."""
grouped: dict[str, list[LiveContextBannerItem]] = {}
⋮----
fanout = "root" if fanout_idx is None else str(fanout_idx)
⋮----
scope_items = grouped.get(scope, [])
⋮----
def _chip(item: LiveContextBannerItem, *, on_open_text=None) -> None
⋮----
token_text = (
bg = "rgba(126,240,160,0.16)" if item.present else "rgba(159,176,209,0.08)"
border = "var(--accent-active)" if item.present else "var(--border-1)"
text = "var(--accent-active)" if item.present else "var(--text-1)"
clickable = on_open_text is not None
chip = ui.element("div").style(
````

## File: rlm_adk/dashboard/components/live_context_viewer.py
````python
"""Shared dialog content for live context text inspection."""
⋮----
"""Render the single shared context viewer body."""
⋮----
text = selection.text if selection is not None else "No state key selected."
````

## File: rlm_adk/dashboard/components/output_panel.py
````python
"""Reasoning output panel -- model response text + worker details."""
⋮----
def render_output_panel(controller: DashboardController) -> None
⋮----
"""Render the model output panel for the current iteration.

    Shows reasoning agent output text with preview/expansion,
    token badges, and per-worker output summary.
    """
it_data = controller.state.current_iteration_data
⋮----
reasoning_out = it_data.reasoning_output
worker_outs = it_data.worker_outputs
⋮----
# --- Reasoning output ---
⋮----
# Token badges
⋮----
# Worker summary line
⋮----
total_worker_input = sum(w.input_tokens for w in worker_outs)
⋮----
# Error message
⋮----
# Output text preview
⋮----
# Full output expansion
⋮----
# Per-worker details expansion
⋮----
def _render_output_preview(head: str, tail: str) -> None
⋮----
"""Render head/tail preview with ellipsis."""
⋮----
def _render_output_text(text: str) -> None
⋮----
"""Render output text in a styled pre block."""
escaped = html_mod.escape(text)
⋮----
def _render_worker_output_row(wo: ModelOutput) -> None
⋮----
"""Render a single worker output row with badges."""
````

## File: rlm_adk/dashboard/components/worker_panel.py
````python
"""Worker context window panel with collapse at >=6 workers."""
⋮----
COLLAPSE_THRESHOLD = 6
⋮----
"""Render worker context window bars.

    Collapse rules:
    - 0 workers: panel hidden (caller checks)
    - 1-5 workers: individual bars shown
    - 6+ workers: collapsed summary with ui.expansion toggle
    """
⋮----
count = len(worker_windows)
total_tokens = sum(w.total_tokens for w in worker_windows)
⋮----
# Show individual bars
⋮----
# Collapsed summary with expansion toggle
⋮----
"""Render a single worker's stacked horizontal bar."""
options = build_context_bar_options(window)
⋮----
def on_bar_click(e) -> None
⋮----
chunk_id = e.series_name
# Search in worker windows
````

## File: rlm_adk/dashboard/__init__.py
````python
"""RLM Context Window Dashboard.

NiceGUI-based visualization of context window token composition
across reasoning and worker agent iterations.

Usage:
    python -m rlm_adk.dashboard
    # or
    from rlm_adk.dashboard import launch_dashboard
    launch_dashboard()
"""
⋮----
"""Launch the NiceGUI dashboard (lazy import to avoid requiring NiceGUI at import time)."""
⋮----
__all__ = ["launch_dashboard"]
````

## File: rlm_adk/dashboard/gcloud_usage.py
````python
"""Cloud Monitoring REST API client for token usage reconciliation.

Fetches ``generativelanguage.googleapis.com`` quota metrics from Google
Cloud Monitoring.  Uses ``gcloud auth print-access-token`` for OAuth
bearer tokens.

Graceful degradation:
- Returns ``None`` if no gcloud credentials are available
- Returns ``None`` if the Cloud Monitoring API is unreachable
- Never raises -- all errors are caught and logged
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
_INPUT_TOKEN_METRIC = (
_REQUEST_COUNT_METRIC = "generativelanguage.googleapis.com/quota/generate_requests_per_model/usage"
_MONITORING_API_BASE = "https://monitoring.googleapis.com/v3"
⋮----
class GCloudUsageClient
⋮----
"""Fetches token usage from Google Cloud Monitoring API."""
⋮----
def __init__(self, project_id: str | None = None)
⋮----
"""Fetch token usage for a time range.

        Returns ``None`` if credentials are unavailable or API errors out.
        """
⋮----
token = await self._get_access_token()
⋮----
project = project_id or self._project_id
start_iso = datetime.fromtimestamp(start_time, tz=timezone.utc).strftime(
# Extend end time by 5 minutes to account for monitoring ingest delay
end_iso = datetime.fromtimestamp(end_time + 300, tz=timezone.utc).strftime(
⋮----
# Fetch input token counts
input_data = await self._query_metric(
⋮----
# Fetch request counts
request_data = await self._query_metric(
⋮----
# Parse time series into per-model usage
per_model: dict[str, ModelTokenUsage] = {}
total_input = 0
total_calls = 0
⋮----
model = ts.get("metric", {}).get("labels", {}).get("model", "unknown")
tokens = sum(
⋮----
# Deduplicate by taking max across limit_name entries
⋮----
total_input = max(total_input, sum(m.input_tokens for m in per_model.values()))
⋮----
calls = sum(
⋮----
total_calls = sum(m.calls for m in per_model.values())
⋮----
# Recompute totals from deduplicated per-model data
total_input = sum(m.input_tokens for m in per_model.values())
⋮----
total_output_tokens=0,  # Cloud Monitoring does not track output tokens
⋮----
async def _get_access_token(self) -> str | None
⋮----
"""Get OAuth access token via ``gcloud auth print-access-token``."""
⋮----
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(
⋮----
token = result.stdout.strip()
⋮----
"""Query a specific metric from Cloud Monitoring REST API."""
⋮----
filter_str = f'metric.type="{metric_type}"'
params = urllib.parse.urlencode(
⋮----
url = f"{_MONITORING_API_BASE}/projects/{project}/timeSeries?{params}"
⋮----
req = urllib.request.Request(url)
⋮----
response = await loop.run_in_executor(
data = json.loads(response.read().decode("utf-8"))
````

## File: rlm_adk/eval/__init__.py
````python
"""RLM ADK Evaluation utilities - DuckDB analytics and session forking."""
⋮----
__all__ = ["TraceReader"]
⋮----
def __getattr__(name: str)
````

## File: rlm_adk/eval/session_report.py
````python
"""Session Assessment Report - Consolidates session telemetry into machine-readable JSON.

Queries all 4 SQLite tables (traces, telemetry, session_state_events, spans)
for a given trace_id and produces a structured JSON report designed for
debugging, performance analysis, documentation, and code review personas.

Usage:
    python -m rlm_adk.eval.session_report --trace-id <trace_id> --db .adk/traces.db
"""
⋮----
# ---- Value truncation ----
⋮----
_MAX_VALUE_LEN = 200
⋮----
def _trunc(value: Any, max_len: int = _MAX_VALUE_LEN) -> Any
⋮----
"""Truncate string/JSON values to max_len chars for compact output."""
⋮----
# ---- Agent name -> depth mapping ----
⋮----
_AGENT_DEPTH_RE = re.compile(r'_d(\d+)(?:f\d+)?$')
⋮----
def _agent_depth(agent_name: Optional[str]) -> int
⋮----
"""Extract depth from agent_name pattern (reasoning_agent=0, child_reasoning_d1f0=1, etc)."""
⋮----
return -1  # unknown
⋮----
m = _AGENT_DEPTH_RE.search(agent_name)
⋮----
# ---- Percentile helper ----
⋮----
def _percentile(sorted_values: list[float], p: float) -> float
⋮----
"""Compute percentile from a pre-sorted list. Returns 0 if empty."""
⋮----
k = (len(sorted_values) - 1) * (p / 100.0)
f = math.floor(k)
c = math.ceil(k)
⋮----
# ---- DB query helpers ----
⋮----
def _query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]
⋮----
"""Execute SQL and return list of dicts."""
⋮----
cursor = conn.execute(sql, params)
cols = [d[0] for d in cursor.description]
⋮----
def _query_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[dict[str, Any]]
⋮----
"""Execute SQL and return first row as dict, or None."""
rows = _query(conn, sql, params)
⋮----
def _parse_json_value(value: Any, default: Any) -> Any
⋮----
"""Parse JSON text into a Python value, returning default on failure."""
⋮----
def _has_table(conn: sqlite3.Connection, table_name: str) -> bool
⋮----
"""Check if a table exists."""
row = _query_one(
⋮----
# ---- Report sections ----
⋮----
def _build_overview(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]
⋮----
"""Build the overview section from the traces table."""
trace = _query_one(conn, "SELECT * FROM traces WHERE trace_id = ?", (trace_id,))
⋮----
# Compute wall clock from telemetry if traces.end_time is missing
wall_clock_s = None
⋮----
wall_clock_s = round(trace["end_time"] - trace["start_time"], 2)
⋮----
# Fallback: span from earliest to latest telemetry timestamp
bounds = _query_one(
⋮----
wall_clock_s = round(bounds["t_max"] - bounds["t_min"], 2)
⋮----
# Token totals from telemetry (more reliable than traces table for running traces)
tok = None
⋮----
tok = _query_one(
⋮----
# Iteration count from SSE
iter_row = None
⋮----
iter_row = _query_one(
⋮----
# Tool call count (guarded)
tool_count_row = None
⋮----
tool_count_row = _query_one(
⋮----
def _depth_key(depth: int) -> str
⋮----
"""Convert numeric depth to a display key (depth_unknown for -1)."""
⋮----
def _build_layer_tree(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]
⋮----
"""Build hierarchical layer view grouped by depth."""
⋮----
rows = _query(
⋮----
layers: dict[int, dict[str, Any]] = {}
⋮----
depth = _agent_depth(row["agent_name"])
⋮----
layer = layers[depth]
⋮----
# Convert sets to lists for JSON serialization
result = {}
⋮----
def _build_performance(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]
⋮----
"""Build performance section with per-layer latency stats."""
⋮----
# Per-layer model call latency stats
model_rows = _query(
⋮----
layer_durations: dict[int, list[float]] = {}
⋮----
latency_by_layer = {}
⋮----
vals = sorted(layer_durations[depth])
⋮----
# Rate limit impact: error rows with RESOURCE in error_message
rate_limit = _query_one(
⋮----
# REPL execution times
repl_rows = _query(
repl_durations = [r["duration_ms"] for r in repl_rows]
repl_stats = {}
⋮----
repl_stats = {
⋮----
def _build_errors(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]
⋮----
"""Build errors section: telemetry errors + REPL stderr errors."""
⋮----
# Telemetry errors grouped by agent and error type
error_rows = _query(
⋮----
telemetry_errors = []
⋮----
# REPL errors from result_preview (stderr content)
repl_error_rows = _query(
⋮----
repl_errors = []
⋮----
# Error chain: which depths had errors
error_by_depth = {}
⋮----
d = e["depth"]
⋮----
def _build_repl_outcomes(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]
⋮----
"""Build REPL outcomes section from tool_call telemetry."""
⋮----
tool_rows = _query(
⋮----
error_patterns: dict[str, int] = {}
by_depth: dict[int, dict[str, int]] = {}
reasoning_calls: list[dict[str, Any]] = []
⋮----
stats = by_depth[depth]
⋮----
# Only include per-call detail for depth-0 (reasoning agent) to keep output compact
⋮----
# Extract Python error types from result_preview
⋮----
err_type = match.group(1)
⋮----
total = sum(s["total"] for s in by_depth.values())
total_errors = sum(s["errors"] for s in by_depth.values())
⋮----
def _build_state_timeline(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]
⋮----
"""Build state timeline from session_state_events."""
sse_rows = _query(
⋮----
events = []
by_category: dict[str, list[dict[str, Any]]] = {}
⋮----
# Resolve value
value: Any = None
⋮----
value = row["value_int"]
⋮----
value = row["value_float"]
⋮----
value = _trunc(row["value_text"])
⋮----
value = json.loads(row["value_json"]) if row["value_json"] else None
⋮----
value = _trunc(row["value_json"])
⋮----
value = bool(row["value_int"])
⋮----
value = None
⋮----
# Truncate nested values
⋮----
s = json.dumps(value)
⋮----
value = _trunc(s)
⋮----
entry = {
⋮----
"""Flatten a persisted obs:child_summary payload for evaluator consumption."""
structured_output = summary.get("structured_output", {})
⋮----
structured_output = {}
⋮----
nested_dispatch = summary.get("nested_dispatch", {})
⋮----
nested_dispatch = {}
⋮----
def _build_child_outcomes(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]
⋮----
"""Build evaluator-facing child summary/error/structured-output outcomes."""
trace = _query_one(conn, "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)) or {}
child_error_counts = _parse_json_value(trace.get("child_error_counts"), {})
⋮----
child_error_counts = {}
⋮----
latest_summaries: dict[tuple[int, int | None], dict[str, Any]] = {}
⋮----
summary = None
⋮----
summary = _parse_json_value(row["value_json"], None)
⋮----
summary = _parse_json_value(row["value_text"], None)
⋮----
summaries = sorted(
⋮----
structured_output_outcomes: dict[str, int] = {}
child_error_categories: dict[str, int] = {}
⋮----
outcome = summary["structured_output"].get("outcome")
⋮----
error_category = summary.get("error_category")
⋮----
# ---- Main report builder ----
⋮----
def build_session_report(trace_id: str, db_path: str = ".adk/traces.db") -> dict[str, Any]
⋮----
"""Build a complete session assessment report for a trace.

    Args:
        trace_id: The trace identifier to report on.
        db_path: Path to the SQLite traces database.

    Returns:
        Structured dict with sections: overview, layer_tree, performance,
        errors, repl_outcomes, state_timeline.

    Raises:
        FileNotFoundError: If db_path does not exist.
        sqlite3.Error: If the database cannot be opened.
    """
db_file = Path(db_path)
⋮----
conn = sqlite3.connect(str(db_file))
⋮----
report: dict[str, Any] = {}
⋮----
# ---- CLI ----
⋮----
def main() -> None
⋮----
parser = argparse.ArgumentParser(
⋮----
args = parser.parse_args()
⋮----
report = build_session_report(args.trace_id, args.db)
⋮----
print()  # trailing newline
````

## File: rlm_adk/plugins/__init__.py
````python
"""RLM ADK Plugins - Before/after agent callbacks for cross-cutting concerns."""
⋮----
# SqliteTracingPlugin is conditionally imported -- Track B creates the module.
⋮----
SqliteTracingPlugin = None  # type: ignore[assignment,misc]
⋮----
MigrationPlugin = None  # type: ignore[assignment,misc]
⋮----
__all__ = [
````

## File: rlm_adk/plugins/policy.py
````python
"""PolicyPlugin - Auth/safety guardrails.

Trigger points: before_model_callback, before_tool_callback, on_user_message_callback
Intervene pattern: blocks when policy violated.
Fail fast, fail loud per rlm culture.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class PolicyPlugin(BasePlugin)
⋮----
"""Enforces auth/safety policies.

    - on_user_message_callback: Generate request_id and idempotency_key.
    - before_model_callback: Check blocked patterns against prompt.
    - before_tool_callback: Check auth level against tool requirements.
    """
⋮----
# AR-CRIT-001: pending values stashed by on_user_message_callback,
# persisted via delta-tracked callback_context in before_agent_callback.
⋮----
"""Capture user message for idempotency key generation.

        AR-CRIT-001: on_user_message_callback only receives invocation_context
        (no callback_context), so we cannot write to delta-tracked state here.
        We stash the computed values on the plugin instance and persist them in
        before_agent_callback which has a properly-wired callback_context.
        """
# Generate unique request ID
⋮----
# Generate idempotency key from message content
message_text = ""
⋮----
user_id = invocation_context.session.user_id or ""
session_id = invocation_context.session.id or ""
idem_source = f"{user_id}:{session_id}:{message_text}"
⋮----
"""Persist pending request_id and idempotency_key via delta-tracked state.

        This fires on every agent entry, but we only write the pending values
        once (the first time after on_user_message_callback stashes them).
        """
⋮----
"""Check blocked patterns against prompt content."""
⋮----
# Extract text from request contents
prompt_text = ""
⋮----
# Check each blocked pattern
⋮----
match = pattern.search(prompt_text)
⋮----
request_id = callback_context.state.get(REQUEST_ID, "unknown")
violation = f"blocked: pattern '{pattern.pattern}' matched"
⋮----
"""Check auth level against tool requirements."""
state = tool_context.state
⋮----
# Check if tool has an auth_level requirement (convention: tool attribute)
required_level = getattr(tool, "required_auth_level", None)
⋮----
user_auth_level = state.get("user:auth_level", "user")
# Simple level hierarchy: admin > user > guest
level_order = {"guest": 0, "user": 1, "admin": 2}
user_rank = level_order.get(user_auth_level, 0)
required_rank = level_order.get(required_level, 0)
⋮----
request_id = state.get(REQUEST_ID, "unknown")
tool_name = getattr(tool, "name", str(tool))
violation = (
````

## File: rlm_adk/plugins/repl_tracing.py
````python
"""REPLTracingPlugin - Persists REPL traces as JSON artifacts per iteration.

Captures trace summaries from LAST_REPL_RESULT events and saves accumulated
traces as a single JSON artifact at the end of the run.

Enabled via RLM_REPL_TRACE > 0 env var.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class REPLTracingPlugin(BasePlugin)
⋮----
"""Persists REPL traces as JSON artifacts per iteration."""
⋮----
def __init__(self, name: str = "repl_tracing")
⋮----
"""Capture LAST_REPL_RESULT events that contain trace data."""
⋮----
sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
⋮----
trace_summary = repl_result.get("trace_summary")
⋮----
iteration_key = depth_key(ITERATION_COUNT, depth, fanout)
iteration = sd.get(iteration_key, 0)
trace_key = f"d{depth}:i{iteration}"
⋮----
"""Save accumulated traces as artifact."""
⋮----
artifact_service = invocation_context.artifact_service
⋮----
trace_data = json.dumps(self._traces_by_iteration, indent=2)
artifact = types.Part.from_bytes(
````

## File: rlm_adk/repl/thread_bridge.py
````python
"""Thread bridge: sync wrappers for cross-thread async dispatch.

This module provides factory functions that create synchronous callables
which dispatch work to an asyncio event loop from a worker thread using
``asyncio.run_coroutine_threadsafe()``.

ContextVar visibility boundary
------------------------------
ContextVars set in the event-loop thread are NOT visible in the worker
thread, and vice versa. The thread bridge crosses this boundary via
``run_coroutine_threadsafe`` -- the submitted coroutine runs in the
event-loop thread (where ADK's invocation context, tool context, and
session state live), while the calling code runs in a worker thread
(where the REPL executes user code). Data flows across this boundary
only through function arguments and return values.
"""
⋮----
# Thread-depth counter to prevent runaway recursive dispatch.
_THREAD_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
⋮----
"""Create a sync ``llm_query()`` callable that dispatches to *loop*.

    Parameters
    ----------
    llm_query_async:
        The async dispatch coroutine (e.g. from ``dispatch.py``).
    loop:
        The running event loop (must be alive in another thread).
    timeout:
        Seconds to wait for the async dispatch to complete.
    max_thread_depth:
        Maximum recursive thread-bridge depth.  Defaults to
        ``RLM_MAX_THREAD_DEPTH`` env var, then 10.
    cancelled:
        Optional ``threading.Event`` set by ``execute_code_threaded``
        when the outer timeout fires.  Checked before each
        ``run_coroutine_threadsafe`` to prevent orphaned worker threads
        from submitting new child dispatches (GAP-EL-004).

    Returns
    -------
    A sync callable ``llm_query(prompt, **kwargs) -> result`` that blocks
    the calling (worker) thread until the async dispatch completes.
    """
_timeout = timeout
_max_depth = max_thread_depth if max_thread_depth is not None else int(
⋮----
def llm_query(prompt: str, **kwargs: Any) -> Any
⋮----
depth = _THREAD_DEPTH.get(0)
⋮----
future = asyncio.run_coroutine_threadsafe(
⋮----
"""Create a sync ``llm_query_batched()`` callable that dispatches to *loop*.

    Parameters
    ----------
    llm_query_batched_async:
        The async batched dispatch coroutine (e.g. from ``dispatch.py``).
    loop:
        The running event loop (must be alive in another thread).
    timeout:
        Seconds to wait for the async dispatch to complete.
    cancelled:
        Optional ``threading.Event`` set by ``execute_code_threaded``
        when the outer timeout fires.  Checked before each
        ``run_coroutine_threadsafe`` to prevent orphaned worker threads
        from submitting new child dispatches (GAP-EL-004).

    Returns
    -------
    A sync callable ``llm_query_batched(prompts, **kwargs) -> list`` that
    blocks the calling (worker) thread until all children complete.
    """
⋮----
def llm_query_batched(prompts: list[str], **kwargs: Any) -> list[Any]
````

## File: rlm_adk/skills/test_skill/skill.py
````python
"""Architecture introspection skill: exercises full rlm_adk pipeline.

Module-import delivery: discovered by loader.py, exports injected into REPL
globals. llm_query_fn is auto-injected by the loader wrapper.

Key difference from source-expansion: this function cannot access REPL globals
via globals(). The rlm_state parameter must be passed explicitly from REPL code.
"""
⋮----
@dataclass
class TestSkillResult
⋮----
"""Typed result from run_test_skill(). All fields are JSON-serializable."""
⋮----
state_snapshot: dict[str, Any]
execution_mode: str
thread_bridge_latency_ms: float
child_result: str
timestamps: dict[str, float]
batched_probe_results: list[str] | None = None
⋮----
"""Exercise the full rlm_adk architecture pipeline and return diagnostic data.

    Args:
        child_prompt: Prompt to send to the child orchestrator.
        emit_debug: Whether to print [TEST_SKILL:...] tagged lines.
        rlm_state: The _rlm_state dict from REPL globals (pass explicitly).
        llm_query_fn: Auto-injected by loader wrapper. The sync llm_query callable.
        llm_query_batched_fn: Auto-injected by loader wrapper. The sync
            llm_query_batched callable for parallel child dispatch.

    Returns:
        TestSkillResult with all captured diagnostic data.
    """
⋮----
def _tag(key: str, value: Any) -> None
⋮----
timestamps: dict[str, float] = {}
⋮----
# ------------------------------------------------------------------
# Step 1: Capture _rlm_state (passed explicitly, not from globals())
⋮----
state_snapshot: dict[str, Any] = {}
_state = rlm_state or {}
⋮----
# Step 2: Detect execution mode at runtime
# Thread bridge runs REPL code in a worker thread (not MainThread).
# Detecting the thread name proves the bridge is actually in use.
⋮----
_thread_name = threading.current_thread().name
execution_mode = "thread_bridge" if _thread_name != "MainThread" else "direct"
⋮----
# Step 3: Exercise child dispatch via llm_query_fn()
⋮----
child_result = llm_query_fn(child_prompt)
⋮----
latency_ms = (timestamps["t2_after_llm_query"] - timestamps["t1_before_llm_query"]) * 1000.0
⋮----
# Step 3b: Exercise batched child dispatch via llm_query_batched_fn()
# Only runs if llm_query_batched_fn is provided (not None).
⋮----
raw_batched = llm_query_batched_fn(["batch_probe_1", "batch_probe_2"])
batched_probe_results = [str(r) for r in raw_batched]
⋮----
batched_latency_ms = (
⋮----
# Step 4: Final summary
````

## File: rlm_adk/skills/loader.py
````python
"""Skill discovery and REPL-globals collection for the thread-bridge architecture."""
⋮----
log = logging.getLogger(__name__)
⋮----
_SKILLS_DIR: Path = Path(__file__).parent
⋮----
_SKIP_DIRS: set[str] = {"obsolete", "__pycache__", "repl_skills", "research"}
⋮----
"""Scan the skills directory for valid skill packages (those containing SKILL.md).

    Args:
        enabled_skills: If provided, only return dirs whose name is in this set.

    Returns:
        Sorted list of Path objects for discovered skill directories.
    """
results: list[Path] = []
⋮----
# Support both underscore and kebab-case matching
normalised = entry.name.replace("-", "_")
enabled_normalised = {s.replace("-", "_") for s in enabled_skills}
⋮----
# ---------------------------------------------------------------------------
# llm_query_fn injection helpers
⋮----
def _has_llm_query_fn_param(fn: Callable) -> bool
⋮----
"""Return True if *fn* has a parameter named ``llm_query_fn``."""
⋮----
sig = inspect.signature(fn)
⋮----
def _has_llm_query_batched_fn_param(fn: Callable) -> bool
⋮----
"""Return True if *fn* has a parameter named ``llm_query_batched_fn``."""
⋮----
"""Return a wrapper that injects ``llm_query_fn`` and/or ``llm_query_batched_fn``.

    The wrapper reads from *repl_globals* lazily so the dict can be populated
    after wrapping (e.g. when the orchestrator wires the REPL).

    If the caller already passes either kwarg explicitly the wrapper does not
    override it.
    """
needs_query = _has_llm_query_fn_param(fn)
needs_batched = _has_llm_query_batched_fn_param(fn)
⋮----
# Determine whether the parameters are optional (have defaults) so we
# can skip injection silently instead of raising when the global is absent.
_query_optional = False
_batched_optional = False
⋮----
p = sig.parameters["llm_query_fn"]
_query_optional = p.default is not inspect.Parameter.empty
⋮----
p = sig.parameters["llm_query_batched_fn"]
_batched_optional = p.default is not inspect.Parameter.empty
⋮----
@functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any
⋮----
llm_query = repl_globals.get("llm_query")
⋮----
# Optional param — let the function's default (e.g. None) stand.
⋮----
llm_query_batched = repl_globals.get("llm_query_batched")
⋮----
# Module name resolution
⋮----
_CANONICAL_SKILLS_DIR: Path = Path(__file__).parent
"""The real on-disk skills directory (never monkeypatched)."""
⋮----
def _module_name_for(skill_dir: Path) -> str
⋮----
"""Return the importable dotted module name for *skill_dir*.

    If *skill_dir* lives under the canonical ``rlm_adk/skills/`` package the
    fully-qualified name ``rlm_adk.skills.<name>`` is returned.  Otherwise
    (e.g. in tests that monkeypatch ``_SKILLS_DIR`` to a ``tmp_path``) the
    bare directory name is returned so that callers can add the parent to
    ``sys.path`` themselves.
    """
⋮----
# REPL globals collection
⋮----
"""Import discovered skill modules and collect their SKILL_EXPORTS.

    Callable exports that accept ``llm_query_fn`` are wrapped so the REPL's
    ``llm_query`` is injected at call time (lazy binding).  Non-callable
    exports (e.g. dataclasses, type aliases) pass through unwrapped.

    Args:
        enabled_skills: forwarded to :func:`discover_skill_dirs`.
        repl_globals: mutable dict that will later contain ``llm_query``.
            If *None* a fresh dict is created (useful for testing).

    Returns:
        Dict mapping export names to their objects.
    """
⋮----
repl_globals = {}
⋮----
collected: dict[str, Any] = {}
⋮----
module_name = _module_name_for(skill_dir)
⋮----
mod = importlib.import_module(module_name)
⋮----
exports: list[str] | None = getattr(mod, "SKILL_EXPORTS", None)
⋮----
obj = getattr(mod, name, None)
⋮----
obj = _wrap_with_llm_query_injection(obj, repl_globals)
⋮----
# ADK Skill loading (for SkillToolset L1/L2 discovery)
⋮----
def _load_skill_from_dir(skill_dir: Path) -> Skill
⋮----
"""Load a Skill from a directory, tolerating name/dirname mismatch.

    ADK's ``load_skill_from_dir`` enforces ``dir.name == frontmatter.name``
    but our skill directories use Python package names (underscores) while
    frontmatter names use kebab-case.  This function parses SKILL.md manually.
    """
skill_md = skill_dir / "SKILL.md"
text = skill_md.read_text()
parts = text.split("---", 2)
⋮----
fm_data = yaml.safe_load(parts[1])
fm = Frontmatter(**fm_data)
instructions = parts[2].strip()
⋮----
"""Load ADK Skill objects from discovered skill directories.

    Returns a list of :class:`Skill` objects suitable for passing to
    :class:`SkillToolset`.
    """
skills: list[Skill] = []
⋮----
skill = _load_skill_from_dir(skill_dir)
````

## File: rlm_adk/utils/parsing.py
````python
"""Parsing utilities for RLM trajectories."""
⋮----
def find_final_answer(text: str, environment: Any = None) -> str | None
⋮----
"""
    Find FINAL(...) or FINAL_VAR(...) statement in response and return the final answer string.

    If FINAL_VAR is found and an environment is provided, executes code to retrieve the variable value.
    Returns None if neither pattern is found.

    Args:
        text: The response text to parse
        environment: Optional environment to execute code for FINAL_VAR retrieval

    Returns:
        The final answer string, or None if no final answer pattern is found
    """
# Check for FINAL_VAR pattern first - must be at start of line
final_var_pattern = r"^\s*FINAL_VAR\((.*?)\)"
match = re.search(final_var_pattern, text, re.MULTILINE | re.DOTALL)
⋮----
variable_name = match.group(1).strip().strip('"').strip("'")
⋮----
result = environment.execute_code(f"print(FINAL_VAR({variable_name!r}))")
final_answer = result.stdout.strip()
⋮----
final_answer = result.stderr.strip() or ""
⋮----
# Check for FINAL pattern - must be at start of line
# Use greedy matching to capture content with nested parentheses
final_pattern = r"^\s*FINAL\((.*)\)\s*$"
match = re.search(final_pattern, text, re.MULTILINE | re.DOTALL)
````

## File: rlm_adk/utils/user_context.py
````python
"""User-provided context directory serialization.

Walks a user-supplied directory, reads textual files, and packs as many as
possible into a ``ctx`` dict (smallest-first) until a character budget is
exhausted.  Files that don't fit are recorded in ``unserialized`` so the
agent can load them on demand via ``open()``.
"""
⋮----
_TEXTUAL_EXTENSIONS: frozenset[str] = frozenset({
⋮----
@dataclass
class UserContextResult
⋮----
"""Result of loading a user-provided context directory."""
⋮----
ctx: dict[str, str] = field(default_factory=dict)
serialized: list[str] = field(default_factory=list)
unserialized: list[str] = field(default_factory=list)
exceeded: bool = False
total_chars: int = 0
dir_path: str = ""
⋮----
def build_manifest(self) -> str
⋮----
"""Build a manifest string for dynamic instruction injection."""
lines: list[str] = []
⋮----
chars = len(self.ctx[name])
⋮----
full_path = os.path.join(self.dir_path, name)
# We need the size; read the file to get it
⋮----
size = len(open(full_path, encoding="utf-8").read())  # noqa: SIM115
⋮----
size = 0
⋮----
total_files = len(self.serialized) + len(self.unserialized)
pre = len(self.serialized)
req_open = len(self.unserialized)
⋮----
"""Load textual files from *dir_path* into a context dict.

    Files are sorted smallest-first so the budget accommodates the maximum
    number of files.  Files that don't fit are recorded in ``unserialized``.
    """
collected: list[tuple[str, str, int]] = []  # (rel_path, content, size)
⋮----
ext = os.path.splitext(fname)[1].lower()
⋮----
full = os.path.join(root, fname)
rel = os.path.relpath(full, dir_path)
⋮----
content = open(full, encoding="utf-8").read()  # noqa: SIM115
⋮----
# Sort smallest first
⋮----
ctx: dict[str, str] = {}
serialized: list[str] = []
unserialized: list[str] = []
running = 0
````

## File: rlm_adk/dashboard/components/api_usage.py
````python
"""Worker token usage panel -- horizontal badge bar."""
⋮----
"""Render a horizontal workers bar: ``worker_1 <in><out> | worker_2 ...``

    Spans full width, sitting directly below the reasoning agent context bar.
    When *on_worker_click* is provided, the ``{N} in`` badges become
    clickable and trigger the callback with the worker's ``agent_name``.
    """
it_data = controller.state.current_iteration_data
````

## File: rlm_adk/dashboard/components/chunk_detail.py
````python
"""Chunk detail panel -- text preview with expand/collapse.

NiceGUI review corrections applied:
- ``ui.code`` only for REPL_CODE chunks; ``ui.html('<pre>...')`` for all others
- ``ui.badge`` uses constructor ``color=`` parameter
- ``ui.scroll_area`` uses ``max-height: 400px`` inside expansions
"""
⋮----
def render_chunk_detail(controller: DashboardController) -> None
⋮----
"""Render the chunk detail panel (called from @ui.refreshable scope)."""
chunk = controller.state.selected_chunk
⋮----
is_code = chunk.category == ChunkCategory.REPL_CODE
⋮----
# Stat badges (NiceGUI review: use color= constructor param)
⋮----
# Percentage of iteration total
it_data = controller.state.current_iteration_data
⋮----
total = it_data.reasoning_window.total_tokens
⋮----
pct = chunk.estimated_tokens / total * 100
⋮----
# Preview: head
⋮----
# Ellipsis separator if head != tail
⋮----
# Full text expansion (NiceGUI review: max-height, not height)
⋮----
def render_worker_detail(controller: DashboardController) -> None
⋮----
"""Render the worker prompt detail panel (right-most of three panels)."""
chunk = controller.state.selected_worker_chunk
⋮----
def _render_text_preview(text: str) -> None
⋮----
"""Render arbitrary text faithfully without markdown interpretation.

    NiceGUI review: use ``ui.html('<pre>...')`` for non-code text,
    not ``ui.code()`` which processes through markdown rendering.
    """
escaped = html_mod.escape(text)
````

## File: rlm_adk/dashboard/components/token_charts.py
````python
"""Cumulative token line chart and per-iteration breakdown table.

NiceGUI review corrections applied:
- markLine inside series, NOT at top level of options dict
- Table row click uses ``table.on("rowClick", handler, [[], ["iter"], None])``
"""
⋮----
def build_cumulative_chart_options(iterations: list[IterationData], current_iter: int) -> dict
⋮----
"""Build ECharts options for the cumulative token line chart.

    NiceGUI review correction: markLine must be inside a series,
    not at the top level of the options dict.
    """
cum_input: list[int] = []
cum_output: list[int] = []
running_in = 0
running_out = 0
⋮----
worker_iters = [i for i, it in enumerate(iterations) if it.has_workers]
⋮----
# Combine both markLines into the first series
mark_line_data = [
⋮----
"""Build a clickable per-iteration breakdown table.

    NiceGUI review correction: use ``table.on("rowClick", handler, ...)``
    with the ``args`` parameter to control which JS event arguments are
    forwarded to Python.
    """
columns = [
⋮----
rows = []
prev_total = 0
⋮----
total_in = it.reasoning_input_tokens + it.worker_input_tokens
total_out = it.reasoning_output_tokens + it.worker_output_tokens
current_total = total_in + total_out
delta = current_total - prev_total
worker_count = len(it.worker_windows)
⋮----
prev_total = current_total
⋮----
table = ui.table(
⋮----
# Highlight the current iteration row with a distinct background.
# Custom body slot replaces Quasar's default <q-tr> which normally emits
# row-click, so we re-emit it via @click on the <q-tr>.
⋮----
# NiceGUI review: wire row click via Quasar's rowClick event.
# With the custom body slot, args come from our explicit $emit above:
# args[0] = {} (empty event placeholder), args[1] = row data, args[2] = rowIndex
def handle_row_click(e) -> None
⋮----
row_data = e.args[1]
⋮----
iter_index = row_data.get("iter", 0)
````

## File: rlm_adk/dashboard/controller.py
````python
"""Dashboard controller -- business logic with no UI dependencies.

Manages state transitions, data loading, and navigation.  Fully testable
without NiceGUI imports.
"""
⋮----
@dataclass
class DashboardState
⋮----
"""Observable state for the dashboard UI."""
⋮----
available_sessions: list[str] = field(default_factory=list)
selected_session_id: str | None = None
session_summary: SessionSummary | None = None
iterations: list[IterationData] = field(default_factory=list)
current_iteration: int = 0
selected_chunk: ContextChunk | None = None
selected_worker_chunk: ContextChunk | None = None
api_usage: APITokenUsage | None = None
reconciliation: TokenReconciliation | None = None
is_loading: bool = False
⋮----
@property
    def current_iteration_data(self) -> IterationData | None
⋮----
"""Return the IterationData for the current iteration index."""
⋮----
@property
    def current_reasoning_output(self) -> ModelOutput | None
⋮----
"""Return the ModelOutput for the reasoning agent in the current iteration."""
it_data = self.current_iteration_data
⋮----
@property
    def total_iterations(self) -> int
⋮----
class DashboardController
⋮----
"""Coordinates data loading and state transitions.

    Contains no UI logic -- all UI interaction goes through
    DashboardUI.refresh_all().
    """
⋮----
def __init__(self, loader: DashboardDataLoader)
⋮----
async def select_session(self, session_id: str) -> None
⋮----
"""Load a session and populate state."""
⋮----
def navigate(self, delta: int) -> None
⋮----
"""Move current_iteration by delta, clamped to valid range."""
⋮----
new_idx = self.state.current_iteration + delta
new_idx = max(0, min(new_idx, len(self.state.iterations) - 1))
⋮----
def navigate_to(self, index: int) -> None
⋮----
"""Jump to a specific iteration index."""
⋮----
index = max(0, min(index, len(self.state.iterations) - 1))
⋮----
def select_chunk(self, chunk: ContextChunk) -> None
⋮----
"""Select a chunk for detail display."""
⋮----
def select_worker_chunk(self, chunk: ContextChunk) -> None
⋮----
"""Select a worker chunk for the worker detail panel."""
⋮----
def find_chunk_by_id(self, chunk_id: str) -> ContextChunk | None
⋮----
"""Find a chunk by its chunk_id in the current iteration."""
it_data = self.state.current_iteration_data
⋮----
"""Return all chunks matching a category in the current iteration."""
⋮----
result: list[ContextChunk] = []
⋮----
def set_reconciliation(self, api_usage: APITokenUsage | None) -> None
⋮----
"""Compute reconciliation from local summary and gcloud data."""
⋮----
def reconcile(local: SessionSummary | None, gcloud: APITokenUsage | None) -> TokenReconciliation
⋮----
"""Reconcile local token counts against GCloud monitoring data."""
⋮----
input_delta = gcloud.total_input_tokens - local.total_input_tokens
threshold = local.total_input_tokens * 0.05 if local.total_input_tokens > 0 else 0
⋮----
api_output_tokens=0,  # Cloud Monitoring does not track output tokens
⋮----
output_match=True,  # Cannot verify output tokens
⋮----
class DashboardUI
⋮----
"""Coordinates UI refresh across multiple refreshable sections.

    NiceGUI review correction: provides a concrete refresh_all() method
    that the keyboard handler and navigation buttons can call.
    """
⋮----
def __init__(self, controller: DashboardController)
⋮----
def register(self, refreshable_fn: Any) -> None
⋮----
"""Register a @ui.refreshable for coordinated refresh."""
⋮----
def refresh_all(self) -> None
⋮----
"""Refresh all registered UI sections."""
````

## File: rlm_adk/dashboard/data_models.py
````python
"""Data models for the Context Window Dashboard.

All dataclasses, enums, color maps, and token estimation used by
the data loader, controller, and visualization components.
"""
⋮----
# ---------------------------------------------------------------------------
# Chunk categories
⋮----
class ChunkCategory(str, Enum)
⋮----
STATIC_INSTRUCTION = "static_instruction"
DYNAMIC_INSTRUCTION = "dynamic_instruction"
USER_PROMPT = "user_prompt"
LLM_RESPONSE = "llm_response"
REPL_CODE = "repl_code"
REPL_OUTPUT = "repl_output"
CONTEXT_VAR = "context_var"
WORKER_PROMPT = "worker_prompt"
WORKER_RESPONSE = "worker_response"
⋮----
# Color palette  (colorblind-safe, WCAG contrast-compliant)
⋮----
CATEGORY_COLORS: dict[ChunkCategory, str] = {
⋮----
CATEGORY_TEXT_COLORS: dict[ChunkCategory, str] = {
⋮----
# Core data classes
⋮----
@dataclass
class ContextChunk
⋮----
chunk_id: str
category: ChunkCategory
title: str
char_count: int
estimated_tokens: int
iteration_origin: int  # -1 for static content
text_preview_head: str  # first 5 lines
text_preview_tail: str  # last 5 lines
full_text: str
⋮----
@dataclass
class ContextWindow
⋮----
agent_type: str  # "reasoning" | "worker"
agent_name: str
iteration: int
chunks: list[ContextChunk]
total_chars: int
total_tokens: int  # from usage_metadata.prompt_token_count
output_tokens: int  # from usage_metadata.candidates_token_count
model: str
⋮----
@dataclass
class ModelOutput
⋮----
timestamp: float
session_id: str
⋮----
model_version: str
output_text: str
output_chars: int
thought_chars: int
input_tokens: int
output_tokens: int
thoughts_tokens: int
error: bool = False
error_message: str | None = None
⋮----
@property
    def text_preview_head(self) -> str
⋮----
"""First 5 lines of output text."""
lines = self.output_text.split("\n")
⋮----
@property
    def text_preview_tail(self) -> str
⋮----
"""Last 5 lines of output text."""
⋮----
@dataclass
class IterationData
⋮----
iteration_index: int
reasoning_window: ContextWindow | None
worker_windows: list[ContextWindow] = field(default_factory=list)
reasoning_input_tokens: int = 0
reasoning_output_tokens: int = 0
worker_input_tokens: int = 0
worker_output_tokens: int = 0
has_workers: bool = False
timestamp_start: float = 0.0
timestamp_end: float = 0.0
reasoning_output: ModelOutput | None = None
worker_outputs: list[ModelOutput] = field(default_factory=list)
⋮----
@dataclass
class SessionSummary
⋮----
app_name: str
⋮----
total_iterations: int
total_input_tokens: int
total_output_tokens: int
total_calls: int
reasoning_calls: int
worker_calls: int
start_time: float
end_time: float
⋮----
# API Token Reconciliation
⋮----
@dataclass
class ModelTokenUsage
⋮----
calls: int
⋮----
@dataclass
class APITokenUsage
⋮----
source: str  # "local" | "gcloud_monitoring"
⋮----
per_model: dict[str, ModelTokenUsage] = field(default_factory=dict)
⋮----
@dataclass
class TokenReconciliation
⋮----
local_input_tokens: int
local_output_tokens: int
api_input_tokens: int
api_output_tokens: int
input_delta: int
output_delta: int
input_match: bool
output_match: bool
error_message: str | None
⋮----
# Token estimation
⋮----
def estimate_tokens_for_chunks(chunks: list[ContextChunk], known_total_tokens: int) -> None
⋮----
"""Distribute known total tokens proportionally by character count.

    Mutates ``chunk.estimated_tokens`` in place.  Calibrates to the
    actual Gemini tokenizer output for the specific request (via
    ``usage_metadata``), which is more accurate than a flat chars/4
    heuristic.
    """
total_chars = sum(c.char_count for c in chunks)
````

## File: rlm_adk/dashboard/flow_builder.py
````python
"""Build a linearized flow transcript from the recursive invocation tree."""
⋮----
def find_llm_query_lines(code: str) -> list[tuple[int, str, str | None]]
⋮----
"""Find ``llm_query`` / ``llm_query_batched`` call sites via AST.

    Returns a sorted list of ``(line_number, function_name, schema_name_or_none)``.
    """
⋮----
tree = ast.parse(code)
⋮----
_TARGET_NAMES = {"llm_query", "llm_query_batched"}
results: list[tuple[int, str, str | None]] = []
⋮----
func = node.func
func_name: str | None = None
⋮----
func_name = func.id
⋮----
func_name = func.attr
⋮----
schema_name: str | None = None
⋮----
schema_name = kw.value.id
⋮----
"""Linearize the invocation tree into a flat flow transcript."""
blocks: list[FlowBlock] = []
inspector: FlowInspectorData | None = None
⋮----
inspector = node_inspector
⋮----
"""Process a single invocation node into flow blocks.

    Renders ALL available iterations sequentially (notebook style) so the
    user sees every reasoning turn's code cell and stdout appended in order.
    """
⋮----
available_ids = [(avail.iteration, avail.invocation_id) for avail in node.available_invocations]
⋮----
is_selected = inv.invocation_id == node.invocation.invocation_id
⋮----
# 1. Agent card — use per-invocation context items when available.
inv_context = node.context_items_by_invocation.get(
agent_card = FlowAgentCard(
⋮----
# 2. Code cell (if REPL code exists)
code = inv.repl_submission or ""
⋮----
parse_source = code
raw_lines = find_llm_query_lines(parse_source)
⋮----
# Match llm_query lines to child summaries by source order
children = list(inv.child_summaries)
llm_line_infos: list[LlmQueryLineInfo] = []
⋮----
child = children[idx] if idx < len(children) else None
child_pane_id = (
info = LlmQueryLineInfo(
⋮----
# 3. Child cards for each dispatched child
⋮----
child_pane_id = _find_child_pane_id(node, child.depth, child.fanout_idx)
⋮----
result_kind: str = "return_value" if not child.error else "set_model_response"
⋮----
arrow_kind=result_kind,  # type: ignore[arg-type]
⋮----
# 4. Output cell
child_return_cards = [
⋮----
# 5. Non-execute_code tool calls (set_model_response, load_skill, list_skills)
_TOOL_CALL_TOOLS = {"set_model_response", "load_skill", "list_skills"}
⋮----
arrow_kind=tool_event.tool_name,  # type: ignore[arg-type]
⋮----
# Build inspector data from the selected (active) invocation
sel = node.invocation
inspector = FlowInspectorData(
⋮----
# Child nodes are accessed via drill-down (child window route),
# not inlined in the main transcript.
⋮----
"""Look up the pane_id for a child by depth/fanout in child_nodes."""
⋮----
inv = child_node.invocation
````

## File: rlm_adk/dashboard/flow_models.py
````python
"""Data models for the recursive notebook flow view."""
⋮----
FlowBlockKind = Literal[
⋮----
ArrowDirection = Literal["down", "right", "left"]
⋮----
ArrowKind = Literal[
⋮----
@dataclass(frozen=True)
class FlowAgentCard
⋮----
"""Reasoning agent header card in the flow transcript."""
⋮----
kind: FlowBlockKind = "agent_card"
pane_id: str = ""
invocation_id: str = ""
agent_name: str = ""
depth: int = 0
fanout_idx: int | None = None
status: str = "idle"
iteration: int = 0
available_iteration_ids: list[tuple[int, str]] = field(default_factory=list)
input_tokens: int = 0
output_tokens: int = 0
thought_tokens: int = 0
total_context_tokens: int = 0
model: str = ""
context_items: list[Any] = field(default_factory=list)
state_items: list[Any] = field(default_factory=list)
request_chunks: list[Any] = field(default_factory=list)
model_events: list[Any] = field(default_factory=list)
⋮----
@dataclass(frozen=True)
class LlmQueryLineInfo
⋮----
"""Metadata for a single llm_query call site in a code cell."""
⋮----
line_number: int
function_name: str = "llm_query"
schema_name: str | None = None
child_depth: int | None = None
child_fanout_idx: int | None = None
child_status: str | None = None
child_prompt_preview: str = ""
child_result_preview: str = ""
child_pane_id: str | None = None
⋮----
@dataclass(frozen=True)
class FlowCodeCell
⋮----
"""Code pane block in the flow transcript."""
⋮----
kind: FlowBlockKind = "code_cell"
code: str = ""
llm_query_lines: list[LlmQueryLineInfo] = field(default_factory=list)
⋮----
@dataclass(frozen=True)
class FlowArrow
⋮----
"""Directional connector between flow blocks."""
⋮----
kind: FlowBlockKind = "arrow"
direction: ArrowDirection = "down"
arrow_kind: ArrowKind = "execute_code"
label: str = ""
⋮----
@dataclass(frozen=True)
class FlowChildCard
⋮----
"""Compact inline child agent card."""
⋮----
kind: FlowBlockKind = "child_card"
⋮----
fanout_idx: int = 0
⋮----
error: bool = False
error_message: str | None = None
prompt_preview: str = ""
result_preview: str = ""
visible_output_preview: str = ""
⋮----
elapsed_ms: float | None = None
finish_reason: str | None = None
model: str | None = None
pane_id: str | None = None
structured_output: dict[str, Any] | None = None
⋮----
@dataclass(frozen=True)
class FlowOutputCell
⋮----
"""Output cell below the code cell."""
⋮----
kind: FlowBlockKind = "output_cell"
stdout: str = ""
stderr: str = ""
child_returns: list[FlowChildCard] = field(default_factory=list)
has_errors: bool = False
⋮----
@dataclass(frozen=True)
class FlowToolCallCell
⋮----
"""Tool call display block for non-execute_code tools."""
⋮----
kind: FlowBlockKind = "tool_call_cell"
tool_name: str = ""
tool_args: dict[str, Any] = field(default_factory=dict)
tool_result: dict[str, Any] = field(default_factory=dict)
result_text: str = ""
⋮----
@dataclass(frozen=True)
class FlowInspectorData
⋮----
"""Data for the right sidebar context inspector."""
⋮----
skills: list[tuple[str, str]] = field(default_factory=list)
return_value_json: str | None = None
selected_pane_id: str = ""
⋮----
FlowBlock = (
⋮----
@dataclass(frozen=True)
class FlowTranscript
⋮----
"""Complete linearized flow transcript."""
⋮----
blocks: list[FlowBlock] = field(default_factory=list)
inspector: FlowInspectorData | None = None
````

## File: rlm_adk/eval/trace_reader.py
````python
"""TraceReader - DuckDB analytical overlay for SQLite session data.

Provides columnar, vectorized read access against the ADK session database.
DuckDB attaches the SQLite file directly (zero-copy) and enables SQL analytics
(aggregations, window functions, JSON extraction) that would be slow in SQLite.

Usage:
    reader = TraceReader(".adk/session.db")
    traces = reader.list_sessions("my_app")
    reader.close()

    # Or as context manager:
    with TraceReader(".adk/session.db") as reader:
        sessions = reader.list_sessions("my_app")
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class TraceReader
⋮----
"""DuckDB-backed read-only analytics against SQLite session data.

    Attaches the SQLite session database in read-only mode and provides
    structured query methods for evaluation agents.

    Attributes:
        db_path: Path to the SQLite database file.
        conn: The DuckDB connection with the SQLite file attached.
    """
⋮----
def __init__(self, db_path: str, *, read_only: bool = True)
⋮----
"""Initialize the TraceReader.

        Args:
            db_path: Path to the SQLite session database file.
            read_only: If True, attach SQLite in read-only mode (default).
                This is safe for concurrent access while the agent is writing.

        Raises:
            FileNotFoundError: If db_path does not exist.
            duckdb.Error: If the SQLite file cannot be attached.
        """
⋮----
@property
    def conn(self) -> Any
⋮----
"""The underlying DuckDB connection."""
⋮----
def close(self) -> None
⋮----
"""Close the DuckDB connection and detach the SQLite file."""
⋮----
def __enter__(self) -> "TraceReader"
⋮----
def __exit__(self, *_exc: object) -> None
⋮----
def execute(self, sql: str, params: Optional[list] = None) -> list[dict[str, Any]]
⋮----
"""Execute a SQL query and return results as list of dicts.

        Args:
            sql: SQL query string. Tables are prefixed with ``sdb.`` (the
                attached SQLite schema).
            params: Optional positional parameters for the query.

        Returns:
            List of dicts, one per row, with column names as keys.
        """
⋮----
result = self._conn.execute(sql, params or [])
columns = [desc[0] for desc in result.description]
⋮----
"""List all sessions, optionally filtered by user_id.

        Args:
            app_name: Application name filter.
            user_id: Optional user ID filter.

        Returns:
            List of session dicts with keys: id, app_name, user_id,
            create_time, update_time, event_count.
        """
⋮----
sql = """
⋮----
"""Return the total number of events in a session.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.

        Returns:
            Integer event count.
        """
⋮----
rows = self.execute(sql, [app_name, user_id, session_id])
⋮----
"""Return the current state dict for a session.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.

        Returns:
            Parsed JSON state dict, or empty dict if session not found.
        """
⋮----
"""Return distinct invocation IDs in chronological order.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.

        Returns:
            Ordered list of invocation ID strings.
        """
⋮----
"""Return raw event rows with parsed event_data JSON.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.
            invocation_id: Optional filter for a single invocation.
            limit: Optional maximum number of events to return.

        Returns:
            List of event dicts with keys: id, invocation_id, timestamp,
            event_data (parsed dict).
        """
conditions = [
params: list[Any] = [app_name, user_id, session_id]
⋮----
where = " AND ".join(conditions)
limit_clause = f"LIMIT {limit}" if limit else ""
⋮----
sql = f"""
rows = self.execute(sql, params)
⋮----
pass  # Leave as string if not valid JSON
⋮----
# ------------------------------------------------------------------
# Helper: table existence check (for graceful degradation)
⋮----
def _has_table(self, table_name: str) -> bool
⋮----
"""Check if a table exists in the attached SQLite schema."""
⋮----
rows = self.execute(
⋮----
# traces table methods
⋮----
"""List traces ordered by start_time DESC.

        Args:
            limit: Optional maximum number of traces to return.
            status: Optional status filter ('running', 'completed', etc.).

        Returns:
            List of trace dicts, or empty list if traces table is absent.
        """
⋮----
conditions: list[str] = []
params: list[Any] = []
⋮----
where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
⋮----
def get_trace(self, trace_id: str) -> Optional[dict[str, Any]]
⋮----
"""Return a single trace dict by trace_id, or None.

        Args:
            trace_id: The trace identifier.

        Returns:
            Trace dict or None if not found.
        """
⋮----
sql = "SELECT * FROM sdb.traces WHERE trace_id = $1"
rows = self.execute(sql, [trace_id])
⋮----
def get_trace_summary(self, trace_id: str) -> Optional[dict[str, Any]]
⋮----
"""Return key metrics for a trace.

        Args:
            trace_id: The trace identifier.

        Returns:
            Dict with keys: trace_id, status, total_input_tokens,
            total_output_tokens, total_calls, iterations, duration_s,
            child_dispatch_count, structured_output_failures.
            Returns None if trace not found.
        """
⋮----
# telemetry table methods
⋮----
"""Return telemetry rows for a trace.

        Args:
            trace_id: The trace identifier.
            event_type: Optional filter ('model_call' or 'tool_call').

        Returns:
            List of telemetry dicts ordered by start_time,
            or empty list if telemetry table is absent.
        """
⋮----
conditions = ["trace_id = $1"]
params: list[Any] = [trace_id]
⋮----
def get_model_calls(self, trace_id: str) -> list[dict[str, Any]]
⋮----
"""Shorthand for get_telemetry filtered to model_call.

        Args:
            trace_id: The trace identifier.

        Returns:
            List of model_call telemetry dicts.
        """
⋮----
def get_tool_calls(self, trace_id: str) -> list[dict[str, Any]]
⋮----
"""Shorthand for get_telemetry filtered to tool_call.

        Args:
            trace_id: The trace identifier.

        Returns:
            List of tool_call telemetry dicts.
        """
⋮----
def get_token_usage(self, trace_id: str) -> dict[str, Any]
⋮----
"""Return token usage totals and per-model breakdown from telemetry.

        Args:
            trace_id: The trace identifier.

        Returns:
            Dict with keys: total_input_tokens, total_output_tokens, per_model.
            per_model maps model name to {input_tokens, output_tokens, calls}.
        """
⋮----
total_in = 0
total_out = 0
per_model: dict[str, dict[str, int]] = {}
⋮----
model = row["model"] or "unknown"
in_tok = row["input_tokens"]
out_tok = row["output_tokens"]
⋮----
def get_iteration_timeline(self, trace_id: str) -> list[dict[str, Any]]
⋮----
"""Return per-iteration timing and token counts from telemetry.

        Args:
            trace_id: The trace identifier.

        Returns:
            List of dicts per iteration with keys: iteration,
            total_input_tokens, total_output_tokens, model_calls,
            tool_calls, total_duration_ms.
        """
⋮----
# session_state_events table methods
⋮----
"""Return session state event rows for a trace.

        Args:
            trace_id: The trace identifier.
            key_category: Optional filter by key_category.
            state_key: Optional filter by exact state_key.

        Returns:
            List of state event dicts ordered by seq,
            or empty list if session_state_events table is absent.
        """
⋮----
"""Return ordered value changes for a specific state key.

        Args:
            trace_id: The trace identifier.
            state_key: The state key to track.

        Returns:
            List of state event dicts for that key, ordered by seq.
        """
⋮----
def get_error_summary(self, trace_id: str) -> dict[str, Any]
⋮----
"""Return error summary from telemetry and state events.

        Args:
            trace_id: The trace identifier.

        Returns:
            Dict with keys: telemetry_errors (count), error_types (list),
            worker_error_counts (dict or None).
        """
# Telemetry errors
telemetry_errors = 0
error_types: list[str] = []
⋮----
# Worker error counts from SSE
worker_error_counts: Optional[dict] = None
⋮----
worker_error_counts = json.loads(rows[0]["value_json"])
````

## File: rlm_adk/plugins/litellm_cost_tracking.py
````python
"""LiteLLMCostTrackingPlugin - Per-call and cumulative cost tracking.

Uses ``litellm.completion_cost()`` to estimate costs from usage metadata
on each model response.  Writes state key:

- ``obs:litellm_total_cost`` — running total across all model calls

Per-call cost is stored on the plugin instance (``last_call_cost``)
for programmatic access, not in session state (per-call provenance
belongs in the lineage plane, not the state plane).

LIMITATION (MED-2): This plugin only tracks costs for the root reasoning
agent's model calls.  Child orchestrator costs (from llm_query /
llm_query_batched) are NOT tracked because ADK gives child agents isolated
invocation contexts that do not fire plugin callbacks.  For complete cost
tracking across all agents (including workers and child orchestrators),
configure ``litellm.success_callback`` at the Router level — this hooks
into every LiteLLM completion call regardless of which ADK agent initiated
it.
"""
⋮----
litellm = None  # type: ignore[assignment]
⋮----
logger = logging.getLogger(__name__)
⋮----
class LiteLLMCostTrackingPlugin(BasePlugin)
⋮----
"""Track per-model-call costs via litellm.completion_cost().

    LIMITATION: This plugin only tracks costs for the root reasoning agent's
    model calls. Child orchestrator costs (from llm_query/llm_query_batched)
    are NOT tracked because ADK gives child agents isolated invocation contexts
    that do not fire plugin callbacks. For complete cost tracking, use
    litellm.success_callback at the Router level.
    """
⋮----
def __init__(self)
⋮----
"""Record per-call cost from litellm.completion_cost()."""
⋮----
usage = llm_response.usage_metadata
⋮----
cost = litellm.completion_cost(
⋮----
# Session aggregate — state plane
````

## File: rlm_adk/plugins/migration.py
````python
"""MigrationPlugin - End-of-session batch migration from SQLite to PostgreSQL.

Implements the Strategy B (End-of-Session Migration) from the database
strategy report. Triggers on after_run_callback to migrate the completed
session's data to a PostgreSQL long-term store.

Configuration via environment variables:
    RLM_MIGRATION_ENABLED   - "1" or "true" to enable (default: disabled)
    RLM_POSTGRES_URL        - SQLAlchemy async Postgres URL
                              (e.g., postgresql+asyncpg://user:pass@host/db)
    RLM_SESSION_DB           - Path to the local SQLite session database
                              (default: .adk/session.db)
    RLM_MIGRATION_RETENTION  - Number of sessions to retain locally after
                              migration (default: 50). Set to 0 to disable pruning.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class MigrationPlugin(BasePlugin)
⋮----
"""End-of-session batch migration from SQLite to PostgreSQL.

    The plugin reads session data directly from the SQLite file (not through
    ADK's session service) to avoid holding locks during migration. It writes
    to PostgreSQL via SQLAlchemy's async engine.

    The plugin is safe to include when PostgreSQL is not configured:
    initialization logs a warning and all callbacks become no-ops.

    Migration flow (in after_run_callback):
    1. Read completed session from SQLite (sessions + events tables)
    2. Upsert session record to Postgres
    3. Batch-insert events to Postgres (with ON CONFLICT DO NOTHING)
    4. Mark session as migrated in state
    5. Optionally prune old migrated sessions from SQLite (FIFO)
    """
⋮----
"""Initialize the MigrationPlugin.

        Args:
            name: Plugin name.
            postgres_url: SQLAlchemy async PostgreSQL URL. Falls back to
                ``RLM_POSTGRES_URL`` env var.
            sqlite_db_path: Path to the local SQLite database. Falls back to
                ``RLM_SESSION_DB`` env var, then ``.adk/session.db``.
            retention_count: Number of sessions to retain locally after
                migration. Falls back to ``RLM_MIGRATION_RETENTION`` env var,
                then 50. Set to 0 to disable pruning.
        """
⋮----
# AR-CRIT-001: after_run_callback has no delta-tracked channel
# (no callback_context), so migration status is stored on the
# plugin instance for programmatic access / logging only.
⋮----
async def _get_engine(self)
⋮----
"""Lazily create the SQLAlchemy async engine.

        Returns:
            An AsyncEngine instance, or None if creation fails.
        """
⋮----
# Ensure target tables exist
⋮----
async def _ensure_postgres_schema(self)
⋮----
"""Create migration target tables in PostgreSQL if they don't exist.

        Uses the same schema as SqliteSessionService for compatibility,
        with Postgres-specific types (JSONB instead of TEXT for state/event_data).
        """
⋮----
create_sql = text(
⋮----
"""Migrate the completed session to PostgreSQL.

        This is the main migration entry point, called by the ADK Runner
        after the agent run completes.
        """
⋮----
session = invocation_context.session
app_name = invocation_context.app_name
user_id = session.user_id
session_id = session.id
⋮----
start_time = time.time()
⋮----
engine = await self._get_engine()
⋮----
# Read session data from SQLite
⋮----
# Upsert to PostgreSQL
⋮----
# Update migration tracking on the plugin instance.
# AR-CRIT-001: invocation_context.session.state writes bypass
# delta tracking — store on instance instead.
elapsed = time.time() - start_time
⋮----
# Prune old migrated sessions from SQLite
⋮----
pruned = self._prune_local_sessions(app_name, self._retention)
⋮----
# AR-CRIT-001: store on instance, not session state.
⋮----
"""Read session and events from the local SQLite database.

        Uses a synchronous sqlite3 connection (separate from the ADK
        session service's aiosqlite connections) to avoid lock contention.

        Returns:
            (session_dict, events_list) or (None, []) if not found.
        """
⋮----
conn = sqlite3.connect(self._sqlite_path)
⋮----
row = conn.execute(
⋮----
session_data = dict(row)
⋮----
events = conn.execute(
events_data = [dict(e) for e in events]
⋮----
"""Upsert session and events to PostgreSQL.

        Uses ON CONFLICT DO UPDATE for the session and ON CONFLICT DO NOTHING
        for events (events are immutable once written).
        """
⋮----
# Upsert session
⋮----
# Batch insert events
⋮----
def _prune_local_sessions(self, app_name: str, retention: int) -> int
⋮----
"""Remove oldest sessions from SQLite, keeping ``retention`` most recent.

        Prunes any sessions beyond the retention count for the given app,
        ordered by ``update_time`` ascending (oldest first). Associated events
        are cascade-deleted via foreign key constraints.

        Returns:
            Number of sessions deleted.
        """
⋮----
# Count total sessions for the app
total = conn.execute(
⋮----
# Delete oldest sessions beyond retention limit
to_delete = total - retention
⋮----
# VACUUM to reclaim space (only if significant deletions)
⋮----
async def close(self) -> None
⋮----
"""Clean up the SQLAlchemy engine on runner shutdown."""
````

## File: rlm_adk/plugins/repl_capture_plugin.py
````python
"""REPLCapturePlugin — captures full REPL execution data for JSON export.

Fires for ALL agents (parent + child orchestrators) since child_ctx
preserves plugin_manager via ctx.model_copy().  Captures submitted code,
expanded code, stdout/stderr, variables, and lineage metadata at every
execute_code tool invocation across all depths/fanouts.

Usage::

    plugin = REPLCapturePlugin()
    result = await run_fixture_contract_with_plugins(
        fixture_path, extra_plugins=[plugin],
    )
    plugin.write_json(Path("/tmp/capture.json"), extra={...})
"""
⋮----
def _repl_globals_inventory(repl_globals: dict[str, Any] | None = None) -> dict[str, Any]
⋮----
"""Build a static inventory of known REPL namespace injections.

    When *repl_globals* is provided (from a live REPL), classifies each
    entry.  Otherwise returns the canonical inventory from code analysis.
    """
# Canonical inventory from codebase exploration
canonical: dict[str, Any] = {
⋮----
# LocalREPL.__init__ (local_repl.py:201-209)
⋮----
# Sync LLM query callables (thread_bridge.py)
⋮----
# LLMResult class (orchestrator.py:260)
⋮----
# State snapshot (repl_tool.py:220)
⋮----
live: dict[str, Any] = {}
⋮----
entry = canonical.get(name, {})
⋮----
# Merge canonical entries not in live
⋮----
class REPLCapturePlugin(BasePlugin)
⋮----
"""Captures full REPL execution data at every execute_code invocation."""
⋮----
def __init__(self) -> None
⋮----
self._pending: dict[int, dict[str, Any]] = {}  # keyed by id(tool_context)
# Populated by test code after run completes
⋮----
inv = tool_context._invocation_context
agent = inv.agent
depth = getattr(agent, "_rlm_depth", 0)
⋮----
pending = self._pending.pop(id(tool_context), None)
⋮----
depth = pending["depth"]
⋮----
# Read the _rlm_state snapshot that was active during execution
rlm_state = None
repl = getattr(tool, "repl", None)
⋮----
rlm_state_raw = repl.globals.get("_rlm_state")
⋮----
rlm_state = dict(rlm_state_raw)
⋮----
# Extract result fields
stdout = ""
stderr = ""
variables = {}
llm_calls_made = False
call_number = 0
⋮----
stdout = result.get("stdout", "")
stderr = result.get("stderr", "")
variables = result.get("variables", {})
llm_calls_made = result.get("llm_calls_made", False)
call_number = result.get("call_number", 0)
⋮----
entry: dict[str, Any] = {
⋮----
"""Build the full JSON-serializable output dict."""
output: dict[str, Any] = {
⋮----
"""Write captured data to a JSON file."""
output = self.build_output(
⋮----
def _safe_serialize(obj: Any) -> Any
⋮----
"""Recursively convert to JSON-safe types."""
````

## File: rlm_adk/dashboard/components/__init__.py
````python
"""Dashboard visualization components."""
⋮----
# Flow transcript components
⋮----
__all__ = [
````

## File: rlm_adk/dashboard/run_service.py
````python
"""In-process replay launch helpers for the live dashboard."""
⋮----
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REPLAY_FIXTURE = "tests_rlm_adk/replay/recursive_ping.json"
⋮----
@dataclass(frozen=True)
class ReplayLaunchHandle
⋮----
"""Prepared replay run with a persisted session and executable queries."""
⋮----
runner: Any
user_id: str
session_id: str
queries: tuple[str, ...]
⋮----
async def run(self) -> None
⋮----
content = types.Content(
⋮----
@dataclass(frozen=True)
class ProviderFakeLaunchHandle
⋮----
"""Prepared provider-fake run backed by a FakeGeminiServer."""
⋮----
prompt: str
_server: Any  # FakeGeminiServer
_saved_env: dict[str, str | None] = field(repr=False)
⋮----
# ── Provider-fake env helpers (mirror contract_runner logic) ──
⋮----
_PF_ENV_KEYS = (
⋮----
# LiteLLM mode keys — must be disabled so requests hit the Gemini fake
# server directly (mirrors contract_runner._ENV_KEYS).
⋮----
def _save_provider_fake_env() -> dict[str, str | None]
⋮----
def _restore_provider_fake_env(saved: dict[str, str | None]) -> None
⋮----
def _set_provider_fake_env(base_url: str, config: dict[str, Any]) -> None
⋮----
# Disable LiteLLM so requests hit the Gemini fake server directly
⋮----
"""Return stable replay fixture paths for the dashboard launch picker."""
resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else _REPO_ROOT
resolved_replay_dir = (
⋮----
fixtures: list[str] = []
⋮----
"""Return sorted provider-fake fixture stems for the dashboard picker."""
⋮----
resolved_fixture_dir = (
⋮----
stems: list[str] = []
⋮----
"""Resolve the full filesystem path for a fixture selection.

    *kind* is ``"replay"`` or ``"provider_fake"``.
    Returns ``None`` when the path cannot be resolved or does not exist.
    """
⋮----
path = _resolve_replay_path(value)
⋮----
path = resolved_repo_root / "tests_rlm_adk" / "fixtures" / "provider_fake" / f"{value}.json"
⋮----
def default_replay_fixture(fixtures: Iterable[str]) -> str
⋮----
fixture_list = list(fixtures)
⋮----
def _resolve_replay_path(replay_path: str | Path) -> Path
⋮----
raw_path = Path(replay_path).expanduser()
⋮----
repo_relative = (_REPO_ROOT / raw_path).resolve()
⋮----
def _load_replay_file(replay_path: str | Path) -> dict[str, Any]
⋮----
path = _resolve_replay_path(replay_path)
⋮----
payload = json.load(fh)
⋮----
state = payload.get("state")
queries = payload.get("queries")
⋮----
"""Create a persisted session for a replay run and return an executable handle."""
payload = _load_replay_file(replay_path)
resolved_skills = tuple(enabled_skills) if enabled_skills else ()
initial_state = dict(payload["state"])
⋮----
runner = create_rlm_runner(
session = await runner.session_service.create_session(
⋮----
"""Start a FakeGeminiServer and create a runner for a provider-fake fixture."""
⋮----
fixture_path = resolve_fixture_file_path("provider_fake", fixture_stem)
⋮----
router = ScenarioRouter.from_file(fixture_path)
server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)
⋮----
saved_env = _save_provider_fake_env()
base_url = await server.start()
⋮----
resolved_skills = (
⋮----
initial_state = dict(router.config.get("initial_state") or {})
````

## File: rlm_adk/plugins/context_snapshot.py
````python
"""ContextWindowSnapshotPlugin - Captures full context window decomposition.

Writes one JSONL line per LLM call, capturing the exact per-turn,
per-agent context decomposition (mirroring reasoning_before_model
logic) with full text for every chunk and token counts from
usage_metadata.

Opt-in: enabled when ``RLM_CONTEXT_SNAPSHOTS=1``.

Architecture note (ADK review correction):
    Plugins fire BEFORE agent callbacks.  The LlmRequest is not yet
    populated when before_model_callback runs.  We store a *reference*
    to the mutable LlmRequest in before_model_callback and decompose
    it in after_model_callback, by which point the agent callbacks
    (reasoning_before_model) have mutated the
    object in-place.

Thread safety (ADK review correction):
    ParallelAgent runs multiple workers concurrently.  We use a dict
    keyed by agent name (not a single ``_pending_request``) and an
    ``asyncio.Lock`` for JSONL writes.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class ContextWindowSnapshotPlugin(BasePlugin)
⋮----
"""Captures full context window decomposition at each LLM call.

    Stores a reference to the LlmRequest in before_model_callback,
    then decomposes the (now-mutated) request in after_model_callback
    along with token counts from usage_metadata.
    """
⋮----
# Dict keyed by agent name for concurrent worker safety
⋮----
# ------------------------------------------------------------------
# before_model_callback: stash reference (do NOT decompose yet)
⋮----
"""Store a mutable reference to the LlmRequest.

        Agent callbacks (reasoning_before_model) will mutate this object
        in-place after all plugin callbacks complete.
        We read the mutated state in after_model_callback.
        """
⋮----
agent_name = callback_context._invocation_context.agent.name
⋮----
# after_model_callback: decompose the mutated request + token counts
⋮----
"""Decompose the mutated LlmRequest and pair with token counts."""
⋮----
pending = self._pending.pop(agent_name, None)
⋮----
llm_request: LlmRequest = pending["request"]
agent_type = (
⋮----
# Decompose the mutated request into chunks
chunks = self._decompose_request(llm_request, agent_type, agent_name, pending["iteration"])
⋮----
# Extract usage_metadata
usage = llm_response.usage_metadata
input_tokens = 0
output_tokens = 0
thoughts_tokens = 0
⋮----
input_tokens = getattr(usage, "prompt_token_count", 0) or 0
output_tokens = getattr(usage, "candidates_token_count", 0) or 0
thoughts_tokens = getattr(usage, "thoughts_token_count", 0) or 0
⋮----
entry: dict[str, Any] = {
⋮----
# --- Model output capture ---
⋮----
output_entry: dict[str, Any] = {
⋮----
# on_model_error_callback: flush pending with error flag
⋮----
"""Flush pending entry with error flag when the model call fails."""
⋮----
# The request has been mutated by now (agent callbacks ran)
chunks = self._decompose_request(
⋮----
# --- Model output capture (error case) ---
error_msg = f"{type(error).__name__}: {error}"
⋮----
# after_run_callback: close file handle
⋮----
"""Close the JSONL file handles."""
⋮----
# Context decomposition
⋮----
"""Decompose the mutated LlmRequest into typed chunks."""
⋮----
"""Decompose a reasoning agent's LlmRequest into chunks.

        After reasoning_before_model has mutated the request:
        - system_instruction contains static + dynamic (concatenated with \\n\\n)
        - contents contains the message history
        """
chunks: list[dict[str, Any]] = []
⋮----
# 1. System instruction: split into static + dynamic
si_text = self._extract_system_instruction_text(llm_request)
⋮----
# ADK review correction: use "\\n\\nRepository URL:" as boundary
boundary = "\n\nRepository URL:"
boundary_idx = si_text.find(boundary)
⋮----
static_text = si_text[:boundary_idx]
dynamic_text = si_text[boundary_idx + 2:]  # skip the \n\n
⋮----
# No dynamic instruction -- emit as single static chunk
⋮----
# 2. Contents: classify by role and content patterns
contents = llm_request.contents or []
content_idx = 0
# Track iteration origin from message pattern:
# Each iteration adds: 1 user prompt, 1 model response, N code blocks
msg_iter = 0
last_role = None
⋮----
text = self._extract_content_text(content)
role = getattr(content, "role", "user")
⋮----
# Iteration 0 user prompt with safeguard
⋮----
# REPL code + output, possibly with context vars
⋮----
# ADK review correction: CONTEXT_VAR is within REPL output text
⋮----
# User prompt for iteration > 0
⋮----
# After a user prompt, we are starting a new iteration
⋮----
msg_iter_candidate = msg_iter
⋮----
# Generic user content
⋮----
# Filter out thought parts
visible_text = self._extract_content_text_no_thoughts(content)
⋮----
# After a model response, the next user message starts a new iteration
⋮----
last_role = role
⋮----
"""Decompose a worker agent's LlmRequest into chunks.

        Decompose a child agent's LlmRequest:
        - contents contains the pending prompt (string or message list)
        - No system_instruction for child agents
        """
⋮----
# ADK review correction: handle both string and list prompt formats
⋮----
# Single prompt (string format)
text = self._extract_content_text(contents[0])
⋮----
# Multi-turn message list format
⋮----
category = "worker_response"
title = f"Worker Context (model, msg {idx})"
⋮----
category = "worker_prompt"
title = f"Worker Prompt (msg {idx})"
⋮----
# Helpers
⋮----
@staticmethod
    def _extract_system_instruction_text(llm_request: LlmRequest) -> str
⋮----
"""Extract system_instruction text from the request config."""
⋮----
si = llm_request.config.system_instruction
⋮----
@staticmethod
    def _extract_content_text(content: types.Content) -> str
⋮----
"""Extract all text from a Content object's parts."""
⋮----
@staticmethod
    def _extract_content_text_no_thoughts(content: types.Content) -> str
⋮----
"""Extract text from Content, filtering out thought parts."""
⋮----
@staticmethod
    def _split_repl_message(text: str) -> tuple[str, str, str]
⋮----
"""Split a REPL user message into code, output, and context_var.

        The format (from format_iteration in parsing.py) is:
            Code executed:
            ```python
            <code>
            ```

            REPL output:
            <output>

        Context variables are embedded within the REPL output text
        as a line starting with "REPL variables:".
        """
code_text = ""
output_text = ""
context_var_text = ""
⋮----
# Split code from output
repl_boundary = "\n\nREPL output:\n"
boundary_idx = text.find(repl_boundary)
⋮----
code_section = text[:boundary_idx]
output_section = text[boundary_idx + len(repl_boundary):]
⋮----
# Extract code from within ```python ... ```
code_start = code_section.find("```python\n")
code_end = code_section.rfind("\n```")
⋮----
code_text = code_section[code_start + len("```python\n"):code_end]
⋮----
# Check for CONTEXT_VAR within output (ADK review correction)
repl_var_marker = "REPL variables:"
var_idx = output_section.find(repl_var_marker)
⋮----
# Split output from context vars
context_var_text = output_section[var_idx:].strip()
output_text = output_section[:var_idx].strip()
⋮----
output_text = output_section.strip()
⋮----
# No REPL output boundary -- treat entire text as code section
code_start = text.find("```python\n")
code_end = text.rfind("\n```")
⋮----
code_text = text[code_start + len("```python\n"):code_end]
⋮----
"""Create a chunk dict for serialization."""
⋮----
@staticmethod
    def _chunk_to_dict(chunk: dict[str, Any]) -> dict[str, Any]
⋮----
"""Pass-through since chunks are already dicts."""
⋮----
# Response text extraction
⋮----
@staticmethod
    def _extract_response_text(llm_response: LlmResponse) -> tuple[str, str]
⋮----
"""Extract visible output text and thought text from LlmResponse.

        Returns:
            (output_text, thought_text) tuple.
        """
output_parts: list[str] = []
thought_parts: list[str] = []
⋮----
# JSONL file I/O
⋮----
def _ensure_file_open(self) -> None
⋮----
"""Lazily open the JSONL file on first write."""
⋮----
def _ensure_output_file_open(self) -> None
⋮----
"""Lazily open the model outputs JSONL file on first write."""
⋮----
async def _flush_entry(self, entry: dict[str, Any]) -> None
⋮----
"""Write a single JSONL line atomically (asyncio.Lock for safety)."""
⋮----
line = json.dumps(entry, ensure_ascii=False)
⋮----
async def _flush_output_entry(self, entry: dict[str, Any]) -> None
⋮----
"""Write a model output JSONL line atomically."""
````

## File: rlm_adk/repl/ipython_executor.py
````python
"""IPython/debugpy-backed execution backend for LocalREPL.

Provides a lightweight execution engine that:
- Owns the actual code execution (sync)
- Optionally uses IPython's InteractiveShell for execution
- Optionally arms debugpy for remote debugging
- Never activates interactive features unless explicitly enabled
- Falls back to raw exec() if IPython is unavailable

No ADK-specific behavior lives here.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
@dataclass
class REPLDebugConfig
⋮----
"""Configuration for the IPython/debugpy execution backend.

    All interactive features default to OFF for safety in CI/tests.
    """
⋮----
backend: str = "ipython"  # "exec" | "ipython"
debug: bool = False
debugpy_enabled: bool = False
debugpy_host: str = "127.0.0.1"
debugpy_port: int = 5678
debugpy_wait: bool = False
ipython_embed: bool = False
xmode: str = "Context"  # "Verbose" | "Context" | "Minimal"
⋮----
@classmethod
    def from_env(cls) -> REPLDebugConfig
⋮----
"""Create config from environment variables."""
⋮----
def _try_import_ipython()
⋮----
"""Lazily import IPython's InteractiveShell. Returns None if unavailable."""
⋮----
def _try_import_debugpy()
⋮----
"""Lazily import debugpy. Returns None if unavailable."""
⋮----
class IPythonDebugExecutor
⋮----
"""Execution engine that delegates to IPython or raw exec().

    Responsibilities:
    - Execute sync code and capture stdout/stderr
    - Optionally arm debugpy (only when explicitly enabled)
    - Optionally open embedded IPython shell on exceptions (only when enabled)
    - Surface stdout, stderr, exception text, and namespace updates
    """
⋮----
def __init__(self, config: REPLDebugConfig | None = None)
⋮----
self._shell = None  # Lazy-initialized IPython shell
⋮----
# Attempt to get IPython if backend=ipython
⋮----
shell_cls = _try_import_ipython()
⋮----
# Apply traceback mode (Verbose/Context/Minimal)
⋮----
# IPython unavailable, fall back to exec
⋮----
# Arm debugpy if explicitly enabled
⋮----
def _arm_debugpy(self) -> None
⋮----
"""Arm debugpy for remote debugging if enabled and available."""
debugpy = _try_import_debugpy()
⋮----
"""Execute code synchronously, capturing stdout/stderr.

        Args:
            code: Python source code to execute.
            namespace: Combined globals+locals namespace. Modified in-place.
            capture_output: When True (default), replace sys.stdout/sys.stderr
                with StringIO buffers and return their contents.  When False,
                skip the sys.stdout/sys.stderr swap so that an external
                capture mechanism (e.g. the ``_TaskLocalStream`` ContextVar
                proxy used by ``_execute_code_threadsafe``) remains intact.
                In this mode stdout/stderr are returned as empty strings --
                the caller is responsible for reading from its own buffers.

        Returns:
            (stdout, stderr, success) where success=True means no exception.
        """
⋮----
stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
⋮----
stdout_buf = stderr_buf = None  # Not used in this path
⋮----
# Temporarily suppress IPython's own traceback printing;
# we will format it ourselves so normal stdout is preserved.
shell = self._shell
orig_showtraceback = shell.showtraceback
_captured_tb_args: list[tuple] = []
⋮----
def _capture_showtraceback(*args, **kwargs)
⋮----
"""Intercept IPython's showtraceback to capture the
                    formatted traceback text without polluting stdout."""
⋮----
stdout = stdout_buf.getvalue() if capture_output else ""
stderr = stderr_buf.getvalue() if capture_output else ""
⋮----
error = ipy_result.error_in_exec or ipy_result.error_before_exec
# Format the traceback using IPython's InteractiveTB
# which respects the configured xmode (Verbose/Context/Minimal)
tb_text = ""
⋮----
stb = shell.InteractiveTB.structured_traceback(
tb_text = "\n".join(stb)
⋮----
tb_text = f"\n{type(error).__name__}: {error}"
⋮----
stderr = stderr + tb_text
⋮----
stderr = stderr + f"\n{type(error).__name__}: {error}"
⋮----
stderr = (stderr_buf.getvalue() if capture_output else "") + f"\n{type(e).__name__}: {e}"
⋮----
# Optionally open embedded shell on exception
⋮----
"""Execute code using IPython's run_cell machinery.

        Uses IPython as an execution engine (NOT as an interactive shell).
        The shell's user_ns is temporarily set to our namespace.

        Returns:
            (success, result) where result is the IPython ExecutionResult.
            On error, IPython has already printed the formatted traceback
            to the captured stdout stream (including local vars in Verbose mode).
            The caller should move that output to stderr.
        """
⋮----
# Save and swap namespace
old_ns = shell.user_ns
# Ensure IPython internal keys exist in the namespace to prevent
# KeyError from output caching (e.g. _oh, _ih, _dh).
⋮----
result = shell.run_cell(code, silent=False, store_history=False)
error = result.error_in_exec or result.error_before_exec
# Capture the last expression value (Feature 3).
# result.result holds the value of the last expression in the cell
# (e.g. `42 + 1` yields 43). Store it in the namespace as _last_expr
# so it's available for data flow tracking without explicit print().
⋮----
"""Optionally open an embedded IPython shell for debugging.

        Only called when both debug and ipython_embed are enabled.
        """
⋮----
# ── Trace callbacks (Feature 2) ──────────────────────────────────────
⋮----
def register_trace_callbacks(self, trace: Any, trace_level: int) -> tuple[Any, Any]
⋮----
"""Register IPython pre_run_cell / post_run_cell callbacks for tracing.

        Replaces the old code-injection approach (TRACE_HEADER/FOOTER) with
        IPython event callbacks.  This preserves correct line numbers in error
        tracebacks because no code is prepended/appended to user code.

        Args:
            trace: REPLTrace instance to populate with timing/memory data.
            trace_level: 0=off, 1=timing, 2=timing+tracemalloc.

        Returns:
            (pre_cb, post_cb) — the registered callback callables, needed by
            ``unregister_trace_callbacks`` for cleanup.
        """
_mem_was_tracing = [False]
⋮----
def _pre_run_cell(info=None)
⋮----
def _post_run_cell(result=None)
⋮----
def unregister_trace_callbacks(self, pre_cb: Any, post_cb: Any) -> None
⋮----
"""Unregister previously registered trace callbacks."""
⋮----
def cleanup(self) -> None
⋮----
"""Release executor resources.

        Does NOT destroy the InteractiveShell singleton since other executors
        (e.g. parent REPL in recursive dispatch) may still reference it.
        We only drop our local reference.
        """
````

## File: rlm_adk/artifacts.py
````python
"""Artifact helper functions for the RLM ADK application.

Provides convenience wrappers around ADK's BaseArtifactService for common
artifact operations within the RLM orchestrator loop and callbacks.

Design principles:
- All functions accept InvocationContext (or CallbackContext via extraction)
- All functions return None/[]/False gracefully when no artifact service is configured
- All async functions wrap operations in try/except with warning-level logging (NFR-004)
- should_offload_to_artifact and get_invocation_context are synchronous
- Naming conventions: repl_code_d{D}_f{F}_iter_{N}_turn_{M}.py, final_answer_d{D}_f{F}.md
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
"""Extract InvocationContext from either InvocationContext or CallbackContext.

    Args:
        ctx: An InvocationContext or CallbackContext instance.

    Returns:
        The underlying InvocationContext.
    """
⋮----
def should_offload_to_artifact(data: Union[str, bytes], threshold: int = 10240) -> bool
⋮----
"""Determine if data should be stored as artifact vs. inline in state.

    Args:
        data: The data to check (string or bytes).
        threshold: Byte threshold (default 10KB). Data larger than this
            should be offloaded to an artifact.

    Returns:
        True if len(data) > threshold.
    """
⋮----
"""Save REPL output as a versioned artifact.

    The artifact is named ``repl_output_d{depth}_f{fanout_idx}_iter_{iteration}.txt``.

    Args:
        ctx: InvocationContext or CallbackContext.
        iteration: The current orchestrator iteration number.
        stdout: Standard output text from the REPL execution.
        stderr: Standard error text (optional).
        mime_type: MIME type for the artifact (default text/plain).
        depth: Orchestrator nesting depth (0 = root).
        fanout_idx: Fanout index within a batched dispatch (0 = single/first).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
inv_ctx = get_invocation_context(ctx)
⋮----
filename = f"repl_output_d{depth}_f{fanout_idx}_iter_{iteration}.txt"
content = stdout
⋮----
content = f"{stdout}\n--- STDERR ---\n{stderr}"
⋮----
artifact = types.Part.from_bytes(data=content.encode("utf-8"), mime_type=mime_type)
version = await inv_ctx.artifact_service.save_artifact(
⋮----
"""Build a YAML-style metadata docstring to prepend to REPL code artifacts.

    Args:
        session_id: The session identifier.
        model: The LLM model name.
        depth: Orchestrator nesting depth.
        fanout: Fanout index within a batched dispatch.
        iteration: The current orchestrator iteration number.
        turn: The code block index within this iteration.
        stdout: Standard output from REPL execution.
        stderr: Standard error from REPL execution.

    Returns:
        A triple-quoted docstring with metadata fields.
    """
def _format_block(value: str) -> str
⋮----
"""Format a multiline value as indented YAML block scalar."""
⋮----
indented = "\n".join(f"    {line}" for line in value.splitlines())
⋮----
lines = [
⋮----
"""Save REPL code block as a versioned artifact.

    The artifact is named ``repl_code_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.py``.

    When *model*, *session_id*, *stdout*, and *stderr* are provided, a YAML-style
    metadata docstring is prepended to the code before saving.

    Args:
        ctx: InvocationContext or CallbackContext.
        iteration: The current orchestrator iteration number.
        turn: The code block index within this iteration (0-based).
        code: The Python source code to save.
        depth: Orchestrator nesting depth (0 = root).
        fanout_idx: Fanout index within a batched dispatch (0 = single/first).
        model: LLM model name (keyword-only). When provided with other metadata
            kwargs, a metadata docstring is prepended.
        session_id: Session identifier (keyword-only).
        stdout: Standard output from REPL execution (keyword-only).
        stderr: Standard error from REPL execution (keyword-only).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
⋮----
filename = f"repl_code_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.py"
⋮----
# Prepend metadata docstring when metadata kwargs are provided
content = code
⋮----
docstring = _build_metadata_docstring(
content = docstring + code
⋮----
artifact = types.Part(text=content)
⋮----
"""Save detailed REPL trace as a JSON artifact.

    The artifact is named ``repl_trace_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.json``.

    Args:
        ctx: InvocationContext or CallbackContext.
        iteration: The current orchestrator iteration number.
        turn: The code block index within this iteration (0-based).
        trace_dict: The serialized REPLTrace dict.
        depth: Orchestrator nesting depth (0 = root).
        fanout_idx: Fanout index within a batched dispatch (0 = single/first).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
⋮----
filename = f"repl_trace_d{depth}_f{fanout_idx}_iter_{iteration}_turn_{turn}.json"
data = json.dumps(trace_dict, indent=2)
⋮----
artifact = types.Part.from_bytes(
⋮----
"""Save worker result as a versioned artifact.

    The artifact is named ``worker_{worker_name}_iter_{iteration}.txt``.

    Args:
        ctx: InvocationContext or CallbackContext.
        worker_name: Name of the worker agent.
        iteration: The current orchestrator iteration number.
        result_text: The worker's text response.
        mime_type: MIME type for the artifact (default text/plain).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
⋮----
filename = f"worker_{worker_name}_iter_{iteration}.txt"
⋮----
artifact = types.Part.from_bytes(data=result_text.encode("utf-8"), mime_type=mime_type)
⋮----
"""Save the final answer as an artifact.

    The artifact is named ``final_answer_d{depth}_f{fanout_idx}.md``.

    Args:
        ctx: InvocationContext or CallbackContext.
        answer: The final answer text.
        mime_type: MIME type for the artifact (default text/markdown).
        depth: Orchestrator nesting depth (0 = root).
        fanout_idx: Fanout index within a batched dispatch (0 = single/first).

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
⋮----
filename = f"final_answer_d{depth}_f{fanout_idx}.md"
⋮----
artifact = types.Part.from_bytes(data=answer.encode("utf-8"), mime_type=mime_type)
⋮----
"""Save arbitrary binary data as an artifact.

    Args:
        ctx: InvocationContext or CallbackContext.
        filename: The artifact filename.
        data: Raw binary data.
        mime_type: MIME type of the binary data.

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
⋮----
artifact = types.Part.from_bytes(data=data, mime_type=mime_type)
⋮----
"""Load an artifact by filename, optionally at a specific version.

    Args:
        ctx: InvocationContext or CallbackContext.
        filename: The artifact filename to load.
        version: Specific version to load. None loads the latest.

    Returns:
        The Part data, or None if not found, no service configured,
        or if the load operation fails.
    """
⋮----
result = await inv_ctx.artifact_service.load_artifact(
⋮----
state = ctx.state  # ADK State wrapper — tracks deltas properly
⋮----
state = inv_ctx.session.state  # fallback for raw InvocationContext
⋮----
"""List all artifact filenames in the current session scope.

    Args:
        ctx: InvocationContext or CallbackContext.

    Returns:
        List of artifact filenames, or empty list if no service configured
        or if the operation fails.
    """
⋮----
"""Delete an artifact and all its versions.

    Args:
        ctx: InvocationContext or CallbackContext.
        filename: The artifact filename to delete.

    Returns:
        True if deleted (or no-op for nonexistent), False if no service
        configured or if the operation fails.
    """
⋮----
"""Update session state with artifact save tracking metadata.

    When *ctx* is a ``CallbackContext`` (or subclass like ``ToolContext``),
    writes go through the ADK ``State`` wrapper which properly records deltas
    in ``_event_actions.state_delta`` (AR-CRIT-001 compliant).  When *ctx* is
    a raw ``InvocationContext``, falls back to ``ctx.session.state`` for
    backward compatibility.

    Args:
        ctx: A CallbackContext/ToolContext (preferred) or InvocationContext.
        filename: The saved artifact filename.
        version: The version number returned by the service.
        size_bytes: Size of the saved data in bytes.
    """
⋮----
state = ctx.session.state  # fallback for raw InvocationContext
````

## File: rlm_adk/dashboard/data_loader.py
````python
"""Dashboard data loader -- reads JSONL context snapshots.

Single source of truth: reads ``.adk/context_snapshots.jsonl`` and groups
entries into ``SessionSummary`` + ``list[IterationData]``.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class DashboardDataLoader
⋮----
"""Loads and structures context snapshot data from JSONL.

    Single source of truth: reads .adk/context_snapshots.jsonl
    and groups entries into SessionSummary + list[IterationData].
    """
⋮----
jsonl_path = str(_package_dir() / ".adk" / "context_snapshots.jsonl")
⋮----
outputs_path = str(_package_dir() / ".adk" / "model_outputs.jsonl")
⋮----
def list_sessions(self) -> list[str]
⋮----
"""Return distinct session_ids found in the JSONL file."""
⋮----
session_ids: list[str] = []
seen: set[str] = set()
⋮----
line = line.strip()
⋮----
entry = json.loads(line)
sid = entry.get("session_id", "")
⋮----
def load_session(self, session_id: str) -> tuple[SessionSummary, list[IterationData]]
⋮----
"""Load all entries for a session, build structured data."""
entries = self._read_entries(session_id)
output_entries = self._read_output_entries(session_id)
summary = self._build_summary(entries, session_id)
iterations = self._build_iterations(entries, output_entries)
⋮----
def _read_entries(self, session_id: str) -> list[dict]
⋮----
"""Read and filter JSONL lines by session_id."""
⋮----
entries: list[dict] = []
⋮----
def _read_output_entries(self, session_id: str) -> list[dict]
⋮----
"""Read and filter model output JSONL lines by session_id.

        Graceful degradation: returns empty list if file doesn't exist.
        """
⋮----
@staticmethod
    def _build_model_output(entry: dict) -> ModelOutput
⋮----
"""Convert a single model output JSONL entry to a ModelOutput."""
⋮----
def _build_summary(self, entries: list[dict], session_id: str) -> SessionSummary
⋮----
"""Compute session-level aggregates from entries."""
⋮----
total_input = sum(e.get("input_tokens", 0) or 0 for e in entries)
total_output = sum(e.get("output_tokens", 0) or 0 for e in entries)
reasoning_entries = [e for e in entries if e.get("agent_type") == "reasoning"]
worker_entries = [e for e in entries if e.get("agent_type") == "worker"]
timestamps = [e.get("timestamp", 0) for e in entries]
iterations = [e.get("iteration", 0) for e in entries if e.get("agent_type") == "reasoning"]
max_iteration = max(iterations) if iterations else 0
⋮----
# Get model from first reasoning entry
model = "unknown"
⋮----
m = e.get("model", "") or e.get("model_version", "")
⋮----
model = m
⋮----
"""Group entries by iteration, build ContextWindow objects."""
# Group entries by iteration
by_iteration: dict[int, list[dict]] = defaultdict(list)
⋮----
it_idx = entry.get("iteration", 0)
⋮----
# Group output entries by iteration
outputs_by_iteration: dict[int, list[dict]] = defaultdict(list)
⋮----
it_idx = oe.get("iteration", 0)
⋮----
max_iter = max(by_iteration.keys())
iterations: list[IterationData] = []
⋮----
iter_entries = by_iteration.get(idx, [])
reasoning_window = None
worker_windows: list[ContextWindow] = []
reasoning_in = 0
reasoning_out = 0
worker_in = 0
worker_out = 0
timestamps: list[float] = []
⋮----
window = self._build_context_window(entry)
⋮----
reasoning_window = window
⋮----
# Build model outputs for this iteration
reasoning_output: ModelOutput | None = None
worker_outputs: list[ModelOutput] = []
⋮----
mo = self._build_model_output(oe)
⋮----
reasoning_output = mo
⋮----
def _build_context_window(self, entry: dict) -> ContextWindow
⋮----
"""Convert a single JSONL entry to a ContextWindow."""
chunks: list[ContextChunk] = []
⋮----
text = chunk_data.get("text", "")
lines = text.split("\n")
head = "\n".join(lines[:5])
tail = "\n".join(lines[-5:]) if len(lines) > 5 else head
⋮----
category = ChunkCategory(chunk_data.get("category", "user_prompt"))
⋮----
category = ChunkCategory.USER_PROMPT
⋮----
chunk = ContextChunk(
⋮----
estimated_tokens=0,  # computed below
⋮----
total_tokens = entry.get("input_tokens", 0) or 0
````

## File: rlm_adk/repl/trace.py
````python
"""REPL execution tracing infrastructure.

Provides invisible instrumentation for REPL code block execution:
- REPLTrace: Per-code-block trace accumulator (timing, LLM calls, vars, memory)
- DataFlowTracker: Detects when one llm_query response feeds into a subsequent prompt
- Trace header/footer strings for optional code injection (trace_level >= 2)

Trace levels (RLM_REPL_TRACE env var):
- 0: Off (default) - no tracing overhead
- 1: LLM call timing + variable snapshots + data flow tracking
- 2: + tracemalloc memory tracking via injected header/footer
"""
⋮----
@dataclass
class REPLTrace
⋮----
"""Invisible trace accumulator for a single REPL code block execution."""
⋮----
start_time: float | None = None
end_time: float | None = None
llm_calls: list[dict[str, Any]] = field(default_factory=list)
var_snapshots: list[dict[str, Any]] = field(default_factory=list)
peak_memory_bytes: int = 0
exceptions: list[dict[str, Any]] = field(default_factory=list)
data_flow_edges: list[tuple[int, int]] = field(default_factory=list)
execution_mode: Literal["sync", "thread_bridge"] = "sync"
submitted_code_chars: int = 0
submitted_code_hash: str | None = None
submitted_code_preview: str = ""
_call_counter: int = field(default=0, repr=False)
⋮----
def record_llm_start(self, call_index: int, prompt: str, call_type: str = "single") -> None
⋮----
"""Record the start of an LLM call."""
⋮----
"""Record the end of an LLM call, updating the existing entry."""
⋮----
# If no matching start entry, create a new one
⋮----
def snapshot_vars(self, namespace: dict[str, Any], label: str = "") -> None
⋮----
"""Capture a snapshot of user-visible variables."""
snapshot: dict[str, Any] = {"label": label, "time": time.perf_counter()}
var_summary: dict[str, str] = {}
⋮----
type_name = type(v).__name__
⋮----
def to_dict(self) -> dict[str, Any]
⋮----
"""Serialize to a JSON-compatible dict."""
⋮----
def summary(self) -> dict[str, Any]
⋮----
"""Compact summary for LAST_REPL_RESULT enrichment."""
⋮----
class DataFlowTracker
⋮----
"""Detects when one llm_query() response feeds into a subsequent prompt.

    Uses substring fingerprinting: if a significant substring of a previous
    response appears in a later prompt, we record a data flow edge.
    """
⋮----
def __init__(self, min_fingerprint_len: int = 40)
⋮----
self._responses: dict[int, str] = {}  # call_index -> response text
⋮----
def register_response(self, call_index: int, response: str) -> None
⋮----
"""Register a completed LLM response for future fingerprint matching."""
⋮----
def check_prompt(self, call_index: int, prompt: str) -> None
⋮----
"""Check if this prompt contains substrings from previous responses."""
⋮----
# Check if a significant substring of the response appears in the prompt
fingerprint = prev_response[:self._min_len]
⋮----
edge = (prev_index, call_index)
⋮----
def get_edges(self) -> list[tuple[int, int]]
⋮----
"""Return detected data flow edges as (source_index, target_index) tuples."""
⋮----
# ---------------------------------------------------------------------------
# Trace header/footer strings for code injection (trace_level >= 2)
⋮----
TRACE_HEADER = '''\
⋮----
TRACE_HEADER_MEMORY = '''\
⋮----
TRACE_FOOTER = '''\
⋮----
TRACE_FOOTER_MEMORY = '''\
````

## File: rlm_adk/dashboard/components/live_invocation_tree.py
````python
"""Recursive invocation tree for the live dashboard."""
⋮----
_SCOPE_ORDER = [
⋮----
_SCOPE_LABELS = {
⋮----
def _display_agent_name(invocation: LiveInvocation) -> str
⋮----
"""Render the visible invocation tree."""
⋮----
def _header(node: LiveInvocationNode) -> None
⋮----
# Status chip
status = node.invocation.status
status_color = {
⋮----
# Depth / fanout chip
fanout = (
⋮----
def _loop_detection_warning(node: LiveInvocationNode) -> None
⋮----
"""Detect repeated code submissions across iterations and show a warning."""
⋮----
hashes: list[tuple[int, str]] = []
⋮----
# Find consecutive runs of identical hashes
run_start = 0
loops: list[tuple[int, int]] = []
⋮----
run_start = i
⋮----
def _child_summary_bar(node: LiveInvocationNode, *, on_open_repl_output) -> None
⋮----
"""Render compact child summary cards when children exist."""
summaries = node.invocation.child_summaries
⋮----
error_border = "var(--accent-child)" if child.error else "var(--border-1)"
error_bg = "rgba(255,107,159,0.10)" if child.error else "rgba(159,176,209,0.06)"
⋮----
# Header row
⋮----
status_text = "ERROR" if child.error else "OK"
status_color = "var(--accent-child)" if child.error else "var(--accent-active)"
⋮----
# Token row
⋮----
# Prompt preview
prompt_preview = child.prompt_preview[:100] if child.prompt_preview else ""
⋮----
# Error message
⋮----
def _model_call_detail(node: LiveInvocationNode) -> None
⋮----
"""Render compact model call summary when model events exist."""
events = node.invocation.model_events
⋮----
finish = me.finish_reason or "?"
dur = f"{me.duration_ms:.0f}ms" if me.duration_ms else "?"
error = me.status == "error"
border = "var(--accent-child)" if error else "var(--border-1)"
bg = "rgba(255,107,159,0.08)" if error else "rgba(87,199,255,0.06)"
⋮----
finish_color = (
⋮----
def _scope_groups(node: LiveInvocationNode, *, on_open_context) -> None
⋮----
grouped: dict[str, list[LiveContextBannerItem]] = {}
⋮----
scope_items = grouped.get(scope, [])
⋮----
scope_color = {
⋮----
def _repl_panel(node: LiveInvocationNode, *, on_open_repl_output) -> None
⋮----
# For obs/completion scopes, show value preview instead of token count
⋮----
chip_label = (
bg = {
border = {
text_color = {
⋮----
token_text = "n/a"
⋮----
token_text = f"{item.token_count} tok"
⋮----
token_text = f"~{item.token_count} tok"
chip_label = f"{item.label} ({token_text})"
bg = "rgba(126,240,160,0.16)" if item.present else "rgba(159,176,209,0.08)"
border = "var(--accent-active)" if item.present else "var(--border-1)"
text_color = "var(--accent-active)" if item.present else "var(--text-1)"
⋮----
chip = (
⋮----
def _action_chip(label: str, on_click) -> None
````

## File: rlm_adk/dashboard/app.py
````python
"""NiceGUI dashboard entry point.

Registers the ``/live`` page (via live_app import) and provides
the ``launch_dashboard()`` function that calls ``ui.run()``.
"""
⋮----
from rlm_adk.dashboard import flow_child_page as _flow_child_page  # noqa: F401
⋮----
# Register the live dashboard page before ui.run().
from rlm_adk.dashboard import live_app as _live_app  # noqa: F401
⋮----
@app.get("/")
async def _root_redirect() -> RedirectResponse
⋮----
"""Redirect ``/`` to ``/live`` so bare-URL visits don't 404."""
⋮----
"""Entry point for launching the dashboard.

    Usage:
        python -m rlm_adk.dashboard
        # or
        from rlm_adk.dashboard import launch_dashboard
        launch_dashboard()
    """
````

## File: rlm_adk/skills/__init__.py
````python
"""REPL helper skills for the RLM reasoning agent.

Skill modules (catalog, repomix, polya, etc.) have been moved to
rlm_adk/skills/obsolete/.  The source-expandable skill registry has been
removed.  The skill system is being rebuilt via thread bridge + module-import
delivery (Plan B).
"""
````

## File: rlm_adk/callbacks/worker_retry.py
````python
"""Worker retry plugin for structured output self-healing.

Provides:
- WorkerRetryPlugin: Extends ReflectAndRetryToolPlugin to detect empty
  responses from set_model_response and trigger retries.
- make_worker_tool_callbacks(): Factory returning (after_tool_cb, on_tool_error_cb)
  wrapper functions with positional-arg signatures compatible with LlmAgent
  tool callbacks. These capture validated structured results on the worker
  agent and delegate retry logic to the plugin.
- _patch_output_schema_postprocessor(): Module-level monkey-patch that
  suppresses ADK's premature worker termination when callbacks signal retry
  (BUG-13 workaround).

Wiring: dispatch.py sets these callbacks on workers when output_schema is provided.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
# Observability counter for BUG-13 patch invocations (process-global).
# Tests can read this to verify the patch was actually invoked at runtime,
# not just installed. Reset between test runs if needed.
_bug13_stats: dict[str, int] = {"suppress_count": 0}
⋮----
# Canonical tool name for ADK's synthesized set_model_response tool.
# Used as a guard so that retry/reflection logic only fires for structured
# output validation, not for other tools like execute_code (REPLTool).
_SET_MODEL_RESPONSE_TOOL_NAME = "set_model_response"
⋮----
def _structured_obs(agent: Any) -> dict[str, Any]
⋮----
"""Return the mutable structured-output telemetry dict for a child agent."""
obs = getattr(agent, "_structured_output_obs", None)
⋮----
obs = {"attempts": 0, "retry_count": 0, "events": []}
⋮----
"""Append a structured-output attempt event to the agent-local telemetry."""
obs = _structured_obs(agent)
⋮----
event: dict[str, Any] = {
⋮----
class WorkerRetryPlugin(ReflectAndRetryToolPlugin)
⋮----
"""Extends ReflectAndRetryToolPlugin for set_model_response validation.

    Detects empty values in set_model_response tool results and triggers
    retry via the parent class's reflection/retry mechanism.
    """
⋮----
def __init__(self, max_retries: int = 2)
⋮----
"""Detect empty responses in set_model_response tool output."""
⋮----
# Check if any value in the tool args is empty
⋮----
def _set_lineage_status(agent: Any, **updates: Any) -> None
⋮----
"""Update lineage status on agent.

    Uses object.__setattr__ since agent is a Pydantic LlmAgent.
    """
state = getattr(agent, "_rlm_lineage_status", {}) or {}
⋮----
"""Create agent-level tool callback wrappers backed by WorkerRetryPlugin.

    Returns (after_tool_cb, on_tool_error_cb) with positional-arg signatures
    matching LlmAgent's AfterToolCallback and OnToolErrorCallback types.

    The after_tool_cb captures validated structured results on the worker
    agent's _structured_result attribute when set_model_response succeeds.

    The on_tool_error_cb delegates to the plugin for retry counting and
    reflection guidance generation.

    Args:
        max_retries: Maximum retry attempts for validation errors.

    Returns:
        Tuple of (after_tool_callback, on_tool_error_callback) callables.
    """
plugin = WorkerRetryPlugin(max_retries=max_retries)
⋮----
"""After-tool callback: capture structured result, delegate to plugin.

        Note: ADK calls this with ``args=`` and ``tool_response=`` kwargs
        (see google.adk.flows.llm_flows.functions line 540-545).
        The plugin's ``after_tool_callback`` expects ``tool_args=`` and
        ``result=``, so we translate between the two conventions here.
        """
# Delegate to plugin for extract_error_from_result checks
result = await plugin.after_tool_callback(
⋮----
agent = tool_context._invocation_context.agent
is_reflect_retry_payload = (
⋮----
# result is None means the plugin accepted the response
# (validation passed). Capture for all response types:
# dict, list-of-dicts, and raw primitives.
⋮----
rs = (
⋮----
"""On-tool-error callback: delegate to plugin for retry/reflection.

        Only intercepts errors from set_model_response. Errors from other
        tools (e.g. execute_code / REPLTool) return None so that they
        propagate normally through ADK's error handling.

        Note: ADK calls this with ``args=`` (see
        google.adk.flows.llm_flows.functions line 443-447).
        """
⋮----
result = await plugin.on_tool_error_callback(
⋮----
# ---------------------------------------------------------------------------
# BUG-13 workaround: Patch ADK's output-schema postprocessor so that
# ToolFailureResponse dicts (retry guidance from ReflectAndRetryToolPlugin)
# are NOT treated as successful structured output.
#
# Without this patch, get_structured_model_response() matches any
# func_response with name=='set_model_response' and converts it to a
# text-only final event — terminating the worker loop before the model
# gets a second turn.  The patch inspects the response content for the
# REFLECT_AND_RETRY_RESPONSE_TYPE sentinel and returns None when found,
# allowing the agent loop to continue for retry.
⋮----
# Call site in ADK (module-attribute lookup, patchable):
#   base_llm_flow.py:849  _output_schema_processor.get_structured_model_response(...)
⋮----
def _patch_output_schema_postprocessor() -> None
⋮----
"""Install a retry-aware wrapper around get_structured_model_response.

    Idempotent — safe to call multiple times. Guarded with try/except
    ImportError so that a private ADK module restructure degrades gracefully
    (FM-21 fix: structured output retry disabled, all other functionality intact).
    """
⋮----
# Guard against double-patching
⋮----
_original = _osp.get_structured_model_response
⋮----
result = _original(function_response_event)
⋮----
parsed = _json.loads(result)
⋮----
_retry_aware_get_structured_model_response._rlm_patched = True  # type: ignore[attr-defined]
⋮----
# Apply the patch at import time so it is active before any worker dispatch.
````

## File: rlm_adk/dashboard/live_app.py
````python
"""NiceGUI page for the live recursive dashboard."""
⋮----
_LIVE_PAGE_CSS = """
⋮----
@ui.page("/live")
async def live_dashboard_page() -> None
⋮----
loader = LiveDashboardLoader()
controller = LiveDashboardController(loader)
live_ui = LiveDashboardUI(controller)
⋮----
@ui.refreshable
    def text_panel_body() -> None
⋮----
@ui.refreshable
    def header_section() -> None
⋮----
run_state = controller.state.run_state
session_summary = controller.session_summary()
⋮----
total_calls = run_state.total_live_model_calls if run_state else 0
active_depth = run_state.active_depth if run_state else 0
active_children = run_state.active_children if run_state else 0
⋮----
_query_chips = [
⋮----
_fixture_queries = _on_deck_fixture_queries(controller)
⋮----
_query_chips = [("No query captured", "No query captured.", "user-query")]
⋮----
@ui.refreshable
    def invocation_section() -> None
⋮----
# Nav rail
⋮----
# Main content area
⋮----
async def _poll() -> None
⋮----
changed = await controller.poll()
cancel_pending = (
⋮----
def _session_selector(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None
⋮----
async def on_session_change(e: Any) -> None
⋮----
sessions = controller.state.available_sessions
⋮----
session_options = {
⋮----
def _on_deck_fixture_queries(controller: LiveDashboardController) -> list[str]
⋮----
"""Read the ``queries`` list from the on-deck replay/provider-fake fixture."""
⋮----
path = resolve_fixture_file_path(kind, value)
⋮----
data = _json.load(fh)
⋮----
def _launch_panel(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None
⋮----
replay_options = controller.state.available_replay_fixtures
pf_options = controller.state.available_provider_fake_fixtures
⋮----
# ── Derive on-deck fixture state ──
⋮----
on_deck_label = controller.state.replay_path.split("/")[-1].replace(".json", "")
on_deck_kind = "replay"
header_label = "Launch Replay"
launch_label = "Launch Replay"
⋮----
on_deck_label = controller.state.selected_provider_fake_fixture
on_deck_kind = "provider-fake"
header_label = "Launch Fixture"
launch_label = "Launch Fixture"
⋮----
on_deck_label = ""
on_deck_kind = ""
header_label = "Launch"
launch_label = "Launch"
⋮----
async def on_launch() -> None
⋮----
async def on_cancel() -> None
⋮----
def on_replay_change(e) -> None
⋮----
def on_pf_change(e) -> None
⋮----
def on_open_on_deck() -> None
⋮----
# ── Launch / Cancel button ──
⋮----
cancel_button = ui.button("Cancel", on_click=on_cancel)
⋮----
launch_button = ui.button(launch_label, on_click=on_launch)
⋮----
# ── On-deck fixture chip ──
⋮----
# ── Spacer pushes dropdowns right ──
⋮----
# ── Fixture selection dropdowns (right-aligned) ──
replay_select = ui.select(
⋮----
def _toggle(label: str, value: bool, on_change) -> None
⋮----
def _status_badge(status: str) -> None
⋮----
color = {
⋮----
def _metric_chip(label: str, value: str) -> None
⋮----
def _truncate_chip_text(text: str, *, fallback: str, limit: int = 108) -> str
⋮----
cleaned = " ".join(text.split())
⋮----
def _step_mode_controls(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None
⋮----
"""Render the Next Step button and paused-agent label when step mode is active."""
⋮----
async def on_advance() -> None
⋮----
btn = ui.button("Next Step", on_click=on_advance)
⋮----
def _nav_rail(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None
⋮----
"""Render the left nav rail with view toggle icons."""
⋮----
# Flow view button
flow_active = "flow-nav-btn--active" if controller.state.view_mode == "flow" else ""
⋮----
# Tree view button
tree_active = "flow-nav-btn--active" if controller.state.view_mode == "tree" else ""
⋮----
"""Render the flow transcript with optional context inspector sidebar."""
transcript = controller.flow_transcript()
⋮----
# Main transcript column
⋮----
# Context inspector sidebar
⋮----
inspector = transcript.inspector
# Enrich with session skills
⋮----
enriched = FlowInspectorData(
⋮----
"""Open context viewer for a flow context chip, using the clicked card's invocation."""
pane = controller._pane_by_id(pane_id)
invocation = _find_invocation_by_id(pane, invocation_id) or controller.selected_invocation(pane)
lineage = controller.selected_invocation_lineage()
⋮----
def _find_invocation_by_id(pane, invocation_id: str)
⋮----
"""Find a specific invocation by ID within a pane."""
⋮----
"""Open context viewer for a state item from the inspector."""
value_text = item.value if isinstance(item.value, str) else repr(item.value)
⋮----
"""Open a child pane in a new browser window."""
⋮----
url = f"/live/session/{controller.state.selected_session_id}/pane/{child.pane_id}"
````

## File: rlm_adk/dashboard/live_controller.py
````python
"""Controller for the live recursive dashboard."""
⋮----
@dataclass(frozen=True)
class LiveBreadcrumb
⋮----
depth: int
fanout_idx: int | None
agent_name: str
status: str
⋮----
@property
    def label(self) -> str
⋮----
fanout = "root" if self.fanout_idx is None else str(self.fanout_idx)
⋮----
class LiveDashboardController
⋮----
"""Owns live dashboard state transitions and polling decisions."""
⋮----
def __init__(self, loader: LiveDashboardLoader)
⋮----
def _refresh_available_sessions(self) -> None
⋮----
session_labels = self.loader.list_session_labels()
⋮----
async def initialize(self) -> None
⋮----
# No default pre-selection — dropdowns start empty, user picks on-deck fixture.
⋮----
async def refresh_sessions(self) -> None
⋮----
sessions = self.state.available_sessions
⋮----
def set_replay_path(self, replay_path: str) -> None
⋮----
self.state.selected_provider_fake_fixture = ""  # mutual exclusion
⋮----
def set_provider_fake_fixture(self, fixture_stem: str) -> None
⋮----
self.state.replay_path = ""  # mutual exclusion
⋮----
def set_selected_skills(self, selected_skills: list[str]) -> None
⋮----
async def launch_replay(self) -> str | None
⋮----
handle = await prepare_provider_fake_launch(
⋮----
handle = await prepare_replay_launch(
⋮----
async def _run_launch(self, handle) -> None
⋮----
async def cancel_launch(self) -> None
⋮----
"""Cancel the running launch task and stamp the trace as cancelled."""
⋮----
# Don't await the task — ADK runner cleanup can block the event loop.
# Set state immediately; _run_launch's finally block is idempotent.
⋮----
async def select_session(self, session_id: str) -> None
⋮----
snapshot = self.loader.load_session(session_id)
⋮----
async def poll(self) -> bool
⋮----
previous = self.state.snapshot.watermark if self.state.snapshot else None
snapshot = self.loader.load_session(
changed = (
⋮----
# Sync step-gate state
⋮----
def set_auto_follow(self, enabled: bool) -> None
⋮----
def set_live_updates_paused(self, paused: bool) -> None
⋮----
def set_pause_live_updates(self, paused: bool) -> None
⋮----
def toggle_auto_follow(self) -> None
⋮----
def toggle_live_updates_paused(self) -> None
⋮----
def set_step_mode(self, enabled: bool) -> None
⋮----
def advance_step(self) -> None
⋮----
def activate_pane(self, pane_id: str, *, manual: bool = True) -> None
⋮----
pane = self._pane_by_id(pane_id)
⋮----
def set_active_pane(self, pane_id: str, *, manual: bool = True) -> None
⋮----
def select_sibling(self, parent_depth: int, fanout_idx: int) -> None
⋮----
child_depth = parent_depth + 1
pane = self._find_pane(child_depth, fanout_idx)
⋮----
def focus_child_fanout(self, parent_pane_id: str, fanout_idx: int) -> None
⋮----
parent = self._pane_by_id(parent_pane_id)
⋮----
def open_context_viewer(self, item: LiveContextBannerItem) -> None
⋮----
text = self.loader.resolve_banner_item_text(
⋮----
normalized = text.strip()
⋮----
def open_text_viewer(self, *, label: str, text: str, raw_key: str = "session") -> None
⋮----
def open_on_deck_fixture_viewer(self) -> None
⋮----
"""Load the on-deck fixture JSON and display it in the context viewer."""
⋮----
path = resolve_fixture_file_path(kind, value)
⋮----
text = f"Fixture file not found: {value}"
⋮----
text = _json.dumps(_json.load(fh), indent=2)
⋮----
display_label = value if kind == "replay" else f"provider_fake/{value}"
⋮----
def close_context_viewer(self) -> None
⋮----
def select_iteration(self, pane_id: str, invocation_id: str) -> None
⋮----
def active_lineage(self) -> list[LivePane]
⋮----
panes_by_depth = {pane.depth: pane for pane in self.state.snapshot.panes}
lineage: list[LivePane] = []
root = panes_by_depth.get(0)
⋮----
target_depth = (
⋮----
selected = self.state.selected_fanouts_by_parent_depth.get(parent_depth)
pane = self._find_pane(child_depth, selected)
⋮----
pane = self._first_pane_for_depth(child_depth)
⋮----
def breadcrumbs(self) -> list[LiveBreadcrumb]
⋮----
def banner_items(self) -> list[LiveContextBannerItem]
⋮----
def invocation_tree(self) -> list[LiveInvocationNode]
⋮----
roots = [pane for pane in self.state.snapshot.panes if pane.parent_pane_id is None]
nodes: list[LiveInvocationNode] = []
⋮----
node = self._build_invocation_node(root, lineages=[])
⋮----
def flow_transcript(self) -> FlowTranscript
⋮----
"""Build a linearized flow transcript from the invocation tree."""
⋮----
def session_summary(self) -> LiveSessionSummary
⋮----
def selected_invocation(self, pane: LivePane | None) -> LiveInvocation | None
⋮----
selected_id = self.state.selected_invocation_id_by_pane.get(pane.pane_id)
⋮----
def selected_invocation_lineage(self) -> list[LiveInvocation]
⋮----
def active_sibling_fanouts(self) -> list
⋮----
pane = self.state.active_pane
⋮----
parent = self._find_pane(pane.depth - 1, self._selected_fanout_for_depth(pane.depth - 1))
⋮----
parent = self._first_pane_for_depth(pane.depth - 1)
⋮----
def _resolve_active_pane_id(self, snapshot) -> str | None
⋮----
candidate = snapshot.pane_map.get(snapshot.active_candidate_pane_id)
⋮----
lineage = [pane for pane in snapshot.panes if pane.depth <= candidate.depth]
⋮----
def _sync_selected_fanouts_from_active(self) -> None
⋮----
def _sync_selected_fanouts_from_pane(self, pane: LivePane) -> None
⋮----
def _clamp_active_pane(self, pane_id: str | None) -> str | None
⋮----
def _pane_by_id(self, pane_id: str | None) -> LivePane | None
⋮----
def _find_pane(self, depth: int, fanout_idx: int | None) -> LivePane | None
⋮----
def _first_pane_for_depth(self, depth: int) -> LivePane | None
⋮----
def _selected_fanout_for_depth(self, parent_depth: int) -> int | None
⋮----
def _sync_selected_invocations(self, panes) -> None
⋮----
def _descendant_pane_ids(self, pane_id: str) -> set[str]
⋮----
descendants: set[str] = set()
frontier = [pane_id]
⋮----
current = frontier.pop()
children = [
⋮----
visible_invocations = [
visible_invocations = self._dedupe_invocations_by_iteration(visible_invocations)
⋮----
selected = self._selected_invocation_in_window(pane, visible_invocations)
next_upper_bound = self._next_invocation_timestamp(
lineage = [*lineages, selected]
context_items = self.loader.build_banner_items(selected, lineage=lineage)
# Build context items for ALL iterations so the notebook flow can
# show DYNAMIC CONTEXT / STATE KEYS / REQUEST CHUNKS per turn.
context_items_by_invocation: dict[str, list[LiveContextBannerItem]] = {
⋮----
inv_lineage = [*lineages, inv]
⋮----
child_nodes: list[LiveInvocationNode] = []
⋮----
child_panes = [
# Children are spawned during the selected iteration's REPL execution.
# Their timestamps fall AFTER the parent snapshot but BEFORE the next
# iteration snapshot.  When the latest iteration is selected, use the
# previous iteration's timestamp as lower_bound so children remain
# visible even when auto-following to the final iteration.
selected_ts = self._invocation_timestamp(selected)
prev_ts = self._previous_invocation_timestamp(visible_invocations, selected)
child_lower = prev_ts if prev_ts is not None else selected_ts
# parent_code_text: prefer the invocation that actually dispatched
# children (the one with REPL code), falling back to the selected.
code_source = selected
⋮----
code_source = inv
⋮----
child_node = self._build_invocation_node(
⋮----
@staticmethod
    def _invocation_timestamp(invocation: LiveInvocation) -> float
⋮----
"""Return the timestamp of the iteration before *selected*, or None."""
selected_ts = float(selected.raw_payload.get("timestamp") or 0.0)
prev_ts: float | None = None
⋮----
ts = float(invocation.raw_payload.get("timestamp") or 0.0)
⋮----
prev_ts = ts
⋮----
chosen = visible_invocations[-1]
⋮----
by_iteration: dict[int, LiveInvocation] = {}
⋮----
current = by_iteration.get(invocation.iteration)
⋮----
def _refresh_run_state(self) -> None
⋮----
snapshot = self.state.snapshot
⋮----
active_pane_id = self.state.active_pane_id
panes = [
breadcrumbs = self.breadcrumbs()
⋮----
class LiveDashboardUI
⋮----
"""Coordinate refreshable sections for the live dashboard page."""
⋮----
def __init__(self, controller: LiveDashboardController)
⋮----
def register(self, refreshable_fn) -> None
⋮----
def refresh_all(self) -> None
````

## File: rlm_adk/dashboard/live_models.py
````python
"""Data models for the live recursive dashboard."""
⋮----
SourceKind = Literal[
⋮----
PaneStatus = Literal["running", "idle", "completed", "error", "cancelled"]
⋮----
@dataclass(frozen=True)
class LiveWatermark
⋮----
"""Incremental read position across SQLite and JSONL sources."""
⋮----
trace_id: str | None = None
latest_telemetry_time: float = 0.0
latest_sse_seq: int = -1
snapshot_offset: int = 0
output_offset: int = 0
⋮----
@dataclass(frozen=True)
class LiveRequestChunk
⋮----
chunk_id: str
category: str
title: str
text: str
char_count: int
token_count: int
token_count_is_exact: bool = False
iteration_origin: int = -1
⋮----
@property
    def preview(self) -> str
⋮----
@property
    def label(self) -> str
⋮----
@dataclass(frozen=True)
class LiveStateItem
⋮----
raw_key: str
base_key: str
depth: int
fanout_idx: int | None
value: Any
value_type: str
event_time: float
seq: int
⋮----
@property
    def value_preview(self) -> str
⋮----
text = self.value if isinstance(self.value, str) else repr(self.value)
⋮----
@dataclass(frozen=True)
class LiveContextItem
⋮----
label: str
⋮----
scope: str
source_kind: SourceKind
⋮----
token_count_is_exact: bool
display_value_preview: str
⋮----
@dataclass(frozen=True)
class LiveContextBannerItem
⋮----
present: bool
⋮----
@dataclass(frozen=True)
class LiveContextSelection
⋮----
@dataclass(frozen=True)
class LiveSessionSummary
⋮----
user_query: str
registered_skills: list[tuple[str, str]] = field(default_factory=list)
registered_plugins: list[tuple[str, str]] = field(default_factory=list)
⋮----
@dataclass(frozen=True)
class LiveChildSummary
⋮----
parent_depth: int
⋮----
fanout_idx: int
model: str | None
status: PaneStatus
error: bool
elapsed_ms: float | None
prompt: str
prompt_preview: str
result_text: str
final_answer: str
visible_output_text: str
visible_output_preview: str
thought_text: str
thought_preview: str
raw_output: Any | None
raw_output_preview: str
input_tokens: int
output_tokens: int
thought_tokens: int
finish_reason: str | None
error_message: str | None
structured_output: dict[str, Any] | None
⋮----
@dataclass(frozen=True)
class LiveToolEvent
⋮----
telemetry_id: str
agent_name: str
⋮----
tool_name: str
start_time: float
end_time: float | None
duration_ms: float | None
result_preview: str
repl_has_errors: bool
repl_has_output: bool
repl_llm_calls: int
repl_stdout_len: int
repl_stderr_len: int
repl_trace_summary: dict[str, Any] | None = None
payload: dict[str, Any] | None = None
tool_args: dict[str, Any] | None = None
⋮----
@dataclass(frozen=True)
class LiveModelEvent
⋮----
iteration: int
call_number: int | None
⋮----
model: str
model_version: str | None
⋮----
prompt_chars: int
system_chars: int
num_contents: int
skill_instruction: str | None
⋮----
@dataclass(frozen=True)
class LiveInvocation
⋮----
invocation_id: str
pane_id: str
⋮----
elapsed_ms: float
request_chunks: list[LiveRequestChunk]
state_items: list[LiveStateItem]
child_summaries: list[LiveChildSummary]
repl_submission: str
repl_stdout: str
repl_stderr: str
reasoning_visible_text: str
reasoning_thought_text: str
⋮----
raw_payload: dict[str, Any]
model_events: list[LiveModelEvent] = field(default_factory=list)
tool_events: list[LiveToolEvent] = field(default_factory=list)
⋮----
@dataclass(frozen=True)
class LivePane
⋮----
is_active: bool
is_expanded: bool
⋮----
latest_tool_call_number: int | None
⋮----
latest_event_time: float
parent_pane_id: str | None
⋮----
sibling_fanouts: list[LiveChildSummary] = field(default_factory=list)
banner_items: list[LiveContextBannerItem] = field(default_factory=list)
invocations: list[LiveInvocation] = field(default_factory=list)
⋮----
@property
    def breadcrumb_label(self) -> str
⋮----
fanout = "root" if self.fanout_idx is None else str(self.fanout_idx)
⋮----
@property
    def request_summary_items(self) -> list[tuple[str, str]]
⋮----
chunk_count = len(self.request_chunks)
elapsed = f"{self.elapsed_ms:.0f} ms" if self.elapsed_ms else "0 ms"
⋮----
@dataclass(frozen=True)
class LiveRunStats
⋮----
total_live_model_calls: int = 0
active_depth: int = 0
active_children: int = 0
⋮----
@dataclass(frozen=True)
class LiveInvocationNode
⋮----
invocation: LiveInvocation
available_invocations: list[LiveInvocation] = field(default_factory=list)
context_items: list[LiveContextBannerItem] = field(default_factory=list)
child_nodes: list[LiveInvocationNode] = field(default_factory=list)
lineage: list[LiveInvocation] = field(default_factory=list)
parent_code_text: str = ""
parent_stdout_text: str = ""
parent_stderr_text: str = ""
invocation_context_tokens: int = 0
# Per-invocation context items keyed by invocation_id.
# Populated for all available_invocations so the notebook flow can
# show DYNAMIC CONTEXT / STATE KEYS / REQUEST CHUNKS per iteration.
context_items_by_invocation: dict[str, list[LiveContextBannerItem]] = field(
⋮----
@dataclass(frozen=True)
class LiveRunState
⋮----
panes: list[LivePane]
active_pane_id: str | None
invocation_nodes: list[LiveInvocationNode]
breadcrumb: str
run_status: PaneStatus
total_live_model_calls: int
active_depth: int
active_children: int
⋮----
@dataclass(frozen=True)
class LiveRunSnapshot
⋮----
session_id: str
trace_id: str | None
⋮----
started_at: float = 0.0
finished_at: float = 0.0
panes: list[LivePane] = field(default_factory=list)
pane_map: dict[str, LivePane] = field(default_factory=dict)
pane_order: list[str] = field(default_factory=list)
root_pane_id: str | None = None
active_candidate_pane_id: str | None = None
stats: LiveRunStats = field(default_factory=LiveRunStats)
watermark: LiveWatermark = field(default_factory=LiveWatermark)
⋮----
@property
    def is_empty(self) -> bool
⋮----
@dataclass
class LiveDashboardState
⋮----
available_sessions: list[str] = field(default_factory=list)
available_session_labels: dict[str, str] = field(default_factory=dict)
available_replay_fixtures: list[str] = field(default_factory=list)
selected_session_id: str | None = None
snapshot: LiveRunSnapshot | None = None
run_state: LiveRunState | None = None
replay_path: str = ""
selected_skills: list[str] = field(default_factory=list)
launch_in_progress: bool = False
launch_cancelled: bool = False
launch_error: str | None = None
launched_session_id: str | None = None
active_pane_id: str | None = None
selected_fanouts_by_parent_depth: dict[int, int] = field(default_factory=dict)
selected_invocation_id_by_pane: dict[str, str] = field(default_factory=dict)
auto_follow: bool = True
live_updates_paused: bool = False
available_provider_fake_fixtures: list[str] = field(default_factory=list)
selected_provider_fake_fixture: str = ""
last_error: str | None = None
context_selection: LiveContextSelection | None = None
context_viewer_open: bool = False
step_mode_enabled: bool = False
step_mode_waiting: bool = False
step_mode_paused_label: str = ""
view_mode: str = "flow"  # "flow" or "tree"
⋮----
@property
    def panes(self) -> list[LivePane]
⋮----
@property
    def run_status(self) -> PaneStatus
⋮----
@property
    def stats(self) -> LiveRunStats
⋮----
@property
    def active_pane(self) -> LivePane | None
⋮----
@property
    def pause_live_updates(self) -> bool
````

## File: rlm_adk/dashboard/live_loader.py
````python
"""Composite loader for the live recursive dashboard."""
⋮----
logger = logging.getLogger(__name__)
⋮----
_DEPTH_RE = re.compile(r"_d(\d+)")
_PROMPT_VAR_RE = re.compile(r"{([^}?]+)\??}")
⋮----
_BANNER_DYNAMIC_KEYS = [DYN_REPO_URL, DYN_ROOT_PROMPT, DYN_SKILL_INSTRUCTION]
_KNOWN_DYNAMIC_KEYS = list(
_KNOWN_STATE_KEYS = sorted(DEPTH_SCOPED_KEYS)
⋮----
# Observability state keys still written to session state by production code.
# Post-thread-bridge: ObservabilityPlugin uses instance-local counters only;
# most obs:* keys are no longer written to state. Only keys still written
# by orchestrator.py or plugins are listed here.
_KNOWN_OBS_KEYS = [
_KNOWN_OBS_PREFIXES = ["obs:model_usage:", "obs:per_iteration_token_breakdown"]
⋮----
# Skill system keys — written by orchestrator at init (thread bridge era).
_KNOWN_SKILL_KEYS = [
⋮----
# Completion plane keys — written when the agent finishes reasoning.
_KNOWN_COMPLETION_KEYS = [
⋮----
def _pane_id(depth: int, fanout_idx: int | None) -> str
⋮----
def _depth_from_agent(agent_name: str) -> int
⋮----
match = _DEPTH_RE.search(agent_name or "")
⋮----
def _safe_int(value: Any, default: int = 0) -> int
⋮----
raw = value_float if value_float is not None else value_text
⋮----
def _estimate_token_count(text: str, total_chars: int, total_tokens: int) -> int
⋮----
def _display_text(value: Any) -> str
⋮----
def _chunk_text(chunks: list[dict[str, Any]]) -> str
⋮----
def _parse_tool_preview(result_preview: str | None) -> dict[str, Any]
⋮----
value = ast.literal_eval(result_preview)
⋮----
@dataclass
class _SessionCache
⋮----
trace_row: dict[str, Any] | None = None
telemetry_rows: list[dict[str, Any]] = field(default_factory=list)
sse_rows: list[dict[str, Any]] = field(default_factory=list)
snapshot_rows: list[dict[str, Any]] = field(default_factory=list)
output_rows: list[dict[str, Any]] = field(default_factory=list)
watermark: LiveWatermark = field(default_factory=LiveWatermark)
⋮----
class LiveDashboardLoader
⋮----
"""Incremental loader over SQLite telemetry and JSONL snapshot streams."""
⋮----
package_dir = _package_dir()
resolved_db_path = traces_db_path or db_path
⋮----
def load_run(self, session_id: str)
⋮----
"""Compatibility wrapper returning a UI-ready run state."""
snapshot = self.load_session(session_id)
active_pane_id = snapshot.active_candidate_pane_id or snapshot.root_pane_id
panes = list(snapshot.panes)
pane_map = {pane.pane_id: pane for pane in panes}
active_pane = pane_map.get(active_pane_id) if active_pane_id else None
breadcrumb = active_pane.breadcrumb_label if active_pane is not None else ""
⋮----
def mark_trace_cancelled(self, session_id: str) -> None
⋮----
"""Stamp the running trace row as cancelled with an end_time."""
⋮----
def list_sessions(self) -> list[str]
⋮----
def list_session_labels(self) -> list[tuple[str, str]]
⋮----
rows = conn.execute(
⋮----
def session_summary(self, session_id: str | None) -> LiveSessionSummary
⋮----
cache = self._cache_by_session.get(session_id)
trace_row = cache.trace_row if cache and cache.trace_row else {}
sse_rows = cache.sse_rows if cache else []
user_query = self._latest_session_text(sse_rows, "root_prompt") or str(
⋮----
cache = self._cache_by_session.setdefault(session_id, _SessionCache())
⋮----
context_chunks = self._context_request_chunks(invocation, lineage=lineage)
total_request_chars = sum(chunk.char_count for chunk in context_chunks)
total_request_tokens = sum(chunk.token_count for chunk in context_chunks)
⋮----
request_items: dict[str, LiveContextBannerItem] = {}
⋮----
label = chunk.title or chunk.category
⋮----
state_lookup = {
banner_items: list[LiveContextBannerItem] = []
⋮----
value = self._extract_dynamic_value(key, context_chunks)
present = bool(value.strip())
token_count = _estimate_token_count(
⋮----
item = state_lookup.get(key)
preview = ""
display_text = ""
token_count = 0
⋮----
display_text = _display_text(item.value)
preview = display_text[:240]
⋮----
# State keys are never injected into the LLM request;
# green (present=True) is reserved for content in the request body.
present = False
⋮----
# ---- Observability scope: obs:* state keys ----
⋮----
continue  # skip absent obs keys to avoid clutter
⋮----
continue  # skip zero/empty obs values
⋮----
# obs:model_usage:* and obs:per_iteration_token_breakdown (prefix match)
⋮----
# ---- Skill plane: skill globals injected via thread bridge ----
⋮----
# ---- Completion plane: reasoning outputs, final answer, should_stop ----
⋮----
continue  # skip absent completion keys
⋮----
value = self._extract_dynamic_value(
⋮----
text = _display_text(state_item.value)
⋮----
@staticmethod
    def _latest_session_text(sse_rows: list[dict[str, Any]], key: str) -> str
⋮----
value = LiveDashboardLoader._latest_session_value(sse_rows, key)
text = _display_text(value).strip()
⋮----
@staticmethod
    def _latest_session_value(sse_rows: list[dict[str, Any]], key: str) -> Any
⋮----
value = _parse_jsonish(
⋮----
plugins = {
⋮----
def _refresh_trace_row(self, cache: _SessionCache, session_id: str) -> None
⋮----
row = conn.execute(
⋮----
@staticmethod
    def _format_session_label(session_id: str, created_at: float | None) -> str
⋮----
created_text = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
⋮----
def _refresh_telemetry(self, cache: _SessionCache) -> None
⋮----
preferred_columns = [
available_columns = self._table_columns("telemetry")
selected_columns = [column for column in preferred_columns if column in available_columns]
⋮----
def _refresh_sse(self, cache: _SessionCache) -> None
⋮----
offset = (
⋮----
offset = previous_offset
⋮----
payload = json.loads(line)
⋮----
target = cache.snapshot_rows if kind == "snapshot" else cache.output_rows
⋮----
end_offset = handle.tell()
⋮----
def _build_snapshot(self, session_id: str, cache: _SessionCache) -> LiveRunSnapshot
⋮----
trace_row = cache.trace_row or {}
snapshots = sorted(cache.snapshot_rows, key=lambda row: row.get("timestamp", 0.0))
outputs = sorted(cache.output_rows, key=lambda row: row.get("timestamp", 0.0))
telemetry = sorted(cache.telemetry_rows, key=lambda row: row.get("start_time", 0.0))
sse_rows = sorted(cache.sse_rows, key=lambda row: row.get("seq", -1))
⋮----
child_summaries = self._build_child_summaries(sse_rows)
fanout_by_snapshot = self._match_child_summaries(snapshots, child_summaries)
state_by_depth = self._latest_state_by_depth(sse_rows)
outputs_by_key = {self._event_key(row): row for row in outputs}
tool_events_by_depth = self._tool_events_by_depth(telemetry)
model_events_by_depth = defaultdict(list)
⋮----
depth = _depth_from_agent(row.get("agent_name") or "")
⋮----
pane_invocations: dict[tuple[int, int | None], list[LiveInvocation]] = defaultdict(list)
pane_last_activity: dict[tuple[int, int | None], float] = defaultdict(float)
⋮----
# Build temporal code lookup: per-depth sorted list of (event_time, code_text)
# from repl_submitted_code state events, so each invocation gets ITS iteration's code.
repl_code_timeline: dict[int, list[tuple[float, str]]] = defaultdict(list)
⋮----
d = _safe_int(row.get("key_depth"))
t = float(row.get("event_time") or 0.0)
val = _parse_jsonish(
⋮----
# Pre-compute per-depth snapshot timestamps for upper-bound scoping.
snapshots_by_depth: dict[int, list[float]] = defaultdict(list)
⋮----
d = _depth_from_agent(snapshot.get("agent_name", ""))
⋮----
depth = _depth_from_agent(snapshot.get("agent_name", ""))
fanout_idx = fanout_by_snapshot.get(id(snapshot))
⋮----
fanout_idx = 0
pane_key = (depth, fanout_idx)
⋮----
# Compute upper bound: timestamp of the next snapshot at same depth.
ts = float(snapshot.get("timestamp") or 0.0)
depth_ts_list = snapshots_by_depth.get(depth, [])
next_ts = float("inf")
⋮----
next_ts = candidate
⋮----
live_invocation = self._build_invocation(
⋮----
telemetry_model_count = sum(
status = self._normalize_status(
⋮----
panes: list[LivePane] = []
pane_map: dict[str, LivePane] = {}
active_candidate: str | None = None
ordered_keys = sorted(
⋮----
invocations = pane_invocations[(depth, fanout_idx)]
latest = invocations[-1]
child_options = child_summaries.get(depth + 1, [])
sibling_fanouts = [child for child in child_options if child.parent_depth == depth]
status = latest.status
⋮----
status = "idle"
pane = LivePane(
⋮----
active_candidate = pane.pane_id
⋮----
stats = LiveRunStats(
⋮----
grouped: dict[int, list[LiveChildSummary]] = defaultdict(list)
⋮----
payload = _parse_jsonish(
⋮----
depth = _safe_int(payload.get("depth"), row.get("key_depth", 0))
fanout_idx = _safe_int(payload.get("fanout_idx"), row.get("key_fanout", 0))
status = "error" if payload.get("error") else "completed"
⋮----
mapping: dict[int, int] = {}
unmatched: dict[int, list[dict[str, Any]]] = defaultdict(list)
⋮----
candidates = unmatched.get(depth, [])
used: set[int] = set()
⋮----
matched_idx: int | None = None
⋮----
prompt_text = _chunk_text(snapshot.get("chunks", []))
prompt_preview = summary.prompt_preview.strip()
⋮----
matched_idx = idx
⋮----
eligible = [
⋮----
matched_idx = max(
⋮----
latest: dict[tuple[int, str], LiveStateItem] = {}
⋮----
base_key = row.get("state_key", "")
depth = _safe_int(row.get("key_depth"))
⋮----
item = LiveStateItem(
⋮----
grouped: dict[int, list[LiveStateItem]] = defaultdict(list)
⋮----
grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
⋮----
depth = _safe_int(
⋮----
chunks = self._build_request_chunks(snapshot)
timestamp = float(snapshot.get("timestamp") or 0.0)
request_total_tokens = _safe_int(snapshot.get("input_tokens"))
request_total_chars = sum(chunk.char_count for chunk in chunks)
⋮----
relevant_models = [
# Scope tool events to THIS iteration's time window [timestamp, next_snapshot_ts).
relevant_tools = [
⋮----
# Resolve repl_submission from the temporal code timeline for this iteration,
# not from the global latest state (which only has the LAST iteration's code).
# No fallback: if no code event exists in the time window, this iteration
# didn't call execute_code (e.g. set_model_response only), so repl_submission
# should stay empty.
repl_submission = ""
⋮----
repl_submission = code_text
⋮----
matching_children = [child for child in child_summaries if child.parent_depth == depth]
tool_payload = (relevant_tools[-1].payload or {}) if relevant_tools else {}
repl_stdout = str(tool_payload.get("stdout") or "")
repl_stderr = str(tool_payload.get("stderr") or "")
⋮----
repl_stdout = relevant_tools[-1].result_preview
⋮----
structured_output = None
pane_summary: LiveChildSummary | None = None
⋮----
pane_summary = child
structured_output = child.structured_output
⋮----
status: str = "completed"
⋮----
status = "error"
⋮----
status=status,  # type: ignore[arg-type]
⋮----
def _build_request_chunks(self, snapshot: dict[str, Any]) -> list[LiveRequestChunk]
⋮----
chunks: list[LiveRequestChunk] = []
total_tokens = _safe_int(snapshot.get("input_tokens"))
total_chars = sum(
⋮----
text = chunk.get("text", "")
char_count = _safe_int(chunk.get("char_count"), len(text))
category = str(chunk.get("category") or "unknown")
⋮----
token_count = char_count // 4
⋮----
token_count = _estimate_token_count(text, total_chars, total_tokens)
⋮----
status = "error" if row.get("status") == "error" else "completed"
model_version = (output_row or {}).get("model_version")
⋮----
payload = _parse_tool_preview(row.get("result_preview"))
result_payload = row.get("result_payload")
⋮----
payload = json.loads(result_payload)
⋮----
payload = {"raw": result_payload}
⋮----
@staticmethod
    def _parse_tool_args(row: dict[str, Any]) -> dict[str, Any] | None
⋮----
raw = row.get("tool_args_json")
⋮----
@staticmethod
    def _event_key(row: dict[str, Any]) -> tuple[str, int, int]
⋮----
effective_calls = _safe_int(total_calls) or telemetry_model_count
⋮----
@staticmethod
    def _format_token_suffix(token_count: int, exact: bool) -> str
⋮----
prefix = "" if exact else "~"
⋮----
seen_ids: set[str] = set()
⋮----
@staticmethod
    def _depth_scoped_label(base_key: str, depth: int) -> str
⋮----
@staticmethod
    def _extract_dynamic_value(key: str, chunks: list[LiveRequestChunk]) -> str
⋮----
labels = {
⋮----
text = chunk.text
label = labels.get(key)
⋮----
def _table_columns(self, table_name: str) -> set[str]
⋮----
cached = self._table_columns_cache.get(table_name)
⋮----
rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
columns = {row[1] for row in rows}
````

## File: rlm_adk/plugins/observability.py
````python
"""ObservabilityPlugin - Usage tracking, timings, and audit trail.

Trigger points: ALL (before/after agent, model, tool; on_event, after_run)
Observe only - never returns a value, never blocks execution.

All counters are tracked on plugin instance attributes. Session state is
NOT used as an observability bus — SQLite telemetry is the sole lineage sink.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
class ObservabilityPlugin(BasePlugin)
⋮----
"""Tracks usage metrics, timings, and provides structured audit trail.

    All counters live on the plugin instance — no obs keys are written to
    session state. SQLite telemetry is the authoritative lineage sink.

    Observe-only: never returns a value, never blocks execution.
    Logging errors are caught and suppressed.
    """
⋮----
def __init__(self, *, name: str = "observability", verbose: bool = False)
⋮----
# Instance-local counters (not written to session state)
⋮----
# Consumed from agent._rlm_pending_request_meta
⋮----
"""Record agent entry."""
⋮----
state = callback_context.state
⋮----
agent_name = getattr(agent, "name", "unknown")
request_id = state.get(REQUEST_ID, "unknown")
⋮----
"""Record agent exit."""
⋮----
"""Record pre-model call metrics."""
⋮----
model = llm_request.model or "unknown"
⋮----
"""Record post-model call metrics on instance (not session state).

        Consumes ``_rlm_pending_request_meta`` from the agent
        (set by ``reasoning_before_model``) for prompt/system
        char counts alongside response-side token accounting.
        """
⋮----
# Increment total calls on instance
⋮----
# Extract token usage from response
usage = llm_response.usage_metadata
⋮----
input_tokens = (
output_tokens = (
⋮----
model = "unknown"
⋮----
model = llm_response.model_version
mu = self._model_usage.setdefault(
⋮----
# --- Consume request-side metadata from agent ---
inv_ctx = getattr(
agent = getattr(inv_ctx, "agent", None) if inv_ctx else None
request_meta = (
⋮----
prompt_chars = request_meta.get("prompt_chars")
system_chars = request_meta.get("system_chars")
⋮----
# --- Record finish_reason on instance ---
finish_reason = (
⋮----
key = finish_reason.lower()
⋮----
"""Record tool invocation on instance (not session state)."""
⋮----
tool_name = getattr(tool, "name", str(tool))
⋮----
"""Enrich events with request ID for correlation and track artifact deltas."""
⋮----
state = invocation_context.session.state
request_id = state.get(REQUEST_ID)
⋮----
# Log event for audit trail
⋮----
# Track artifact operations from event artifact_delta.
⋮----
artifact_count = len(event.actions.artifact_delta)
⋮----
"""Record final execution summary from instance counters."""
⋮----
# AR-CRIT-001: after_run_callback only has invocation_context
# (no callback_context).  Reads are fine; writes must NOT go
# to invocation_context.session.state (bypasses delta tracking).
state = invocation_context.session.state  # read-only usage below
start_time = state.get(INVOCATION_START_TIME, 0)
total_time = 0.0
⋮----
total_time = time.time() - start_time
⋮----
# Store last successful call ID on instance (not session state)
⋮----
artifact_saves = self._artifact_saves_acc
final_answer = state.get(FINAL_RESPONSE_TEXT, "")
answer_len = len(final_answer) if final_answer else 0
⋮----
log_msg = (
log_args: list = [
⋮----
# Verbose mode: also print to stdout (replaces DebugLoggingPlugin)
````

## File: rlm_adk/repl/local_repl.py
````python
"""Local REPL environment adapted for ADK.

Provides sandboxed Python code execution with:
- Safe builtins (blocks eval/exec/input)
- Context loading (context_0, context_1, ...)
- FINAL_VAR and SHOW_VARS helpers
- stdout/stderr capture
- Slots for llm_query/llm_query_batched closures (injected by orchestrator)
"""
⋮----
# Task-local stdout/stderr capture (CRIT-3.4)
_capture_stdout: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
_capture_stderr: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
⋮----
class _TaskLocalStream
⋮----
"""Proxy stream that routes writes to a task-local ContextVar buffer when set,
    otherwise falls through to the original stream."""
⋮----
def __init__(self, original: io.TextIOBase, ctx_var: contextvars.ContextVar)
⋮----
@property
    def encoding(self)
⋮----
def isatty(self)
⋮----
def write(self, s)
⋮----
buf = self._ctx_var.get(None)
⋮----
def flush(self)
⋮----
def fileno(self)
⋮----
# Module-level lock protecting process-global state (os.chdir, sys.stdout/stderr)
# during synchronous execute_code. Ensures concurrent REPLs running in threads
# do not race on CWD or output capture.
_EXEC_LOCK = threading.Lock()
⋮----
# Safe builtins - blocks dangerous operations like eval/exec/input
_SAFE_BUILTINS = {
⋮----
# Core types and functions
⋮----
# Exceptions
⋮----
# Blocked
⋮----
class LocalREPL
⋮----
"""Local REPL environment for ADK-based execution.

    Unlike the original LocalREPL which used socket-based llm_query,
    this version accepts callable closures for LM dispatch that are
    injected by the orchestrator.
    """
⋮----
# Cancellation token for GAP-EL-004: set by execute_code_threaded
# on timeout so orphaned worker threads cannot submit new child
# dispatches via llm_query().
⋮----
# Execution backend
⋮----
# Setup globals and locals
⋮----
# Register helper functions
⋮----
def set_llm_query_fns(self, llm_query_fn: Callable, llm_query_batched_fn: Callable) -> None
⋮----
"""Set/update the sync LM query functions (called by orchestrator)."""
⋮----
def _final_var(self, variable_name: str) -> str
⋮----
"""Return the value of a variable as a final answer."""
variable_name = variable_name.strip().strip("\"'")
⋮----
available = [k for k in self.locals.keys() if not k.startswith("_")]
error_hint = ""
⋮----
error_hint = f" Last execution error: {self._last_exec_error}"
⋮----
def _show_vars(self) -> str
⋮----
"""Show all available variables in the REPL environment."""
available = {k: type(v).__name__ for k, v in self.locals.items() if not k.startswith("_")}
⋮----
@contextmanager
    def _capture_output(self)
⋮----
"""Context manager to capture stdout/stderr."""
⋮----
@contextmanager
    def _temp_cwd(self)
⋮----
"""Temporarily change to temp directory for execution."""
old_cwd = os.getcwd()
⋮----
"""Inner exec logic, runs under _EXEC_LOCK.

        Returns (stdout, stderr, success) where success=True means no exception.
        Side-effects: updates self.locals on success, self._last_exec_error on failure.
        Delegates actual execution to the IPythonDebugExecutor.

        Trace timing and optional tracemalloc are handled via IPython event
        callbacks (pre_run_cell / post_run_cell) instead of code injection,
        so user code line numbers are never shifted in error tracebacks.
        """
trace_level = int(os.environ.get("RLM_REPL_TRACE", "0"))
⋮----
combined = {**self.globals, **self.locals}
⋮----
# Register trace callbacks instead of injecting header/footer code
pre_cb = post_cb = None
⋮----
# Update locals with new variables (underscore filter hides _rlm_*)
⋮----
# Capture the last expression result (Feature 3) from IPython.
# _last_expr is set by _execute_via_ipython when run_cell returns
# a non-None result.result (the value of the last expression).
last_expr = combined.get("_last_expr")
⋮----
"""Lock-free execution for thread-bridge mode.

        Unlike ``_execute_code_inner`` this method does NOT acquire
        ``_EXEC_LOCK`` and does NOT call ``os.chdir()``.  Instead it
        uses ContextVar-based stdout/stderr capture and ``_make_cwd_open``
        for CWD-safe file access.  This prevents deadlocks when the REPL
        runs in a worker thread while the event loop holds the lock.

        Returns ``(stdout, stderr, success)`` -- same contract as
        ``_execute_code_inner``.
        """
⋮----
# Inject CWD-safe open() directly into the namespace so that
# user code calling open("file.txt", ...) resolves against
# temp_dir rather than the process CWD.  We also patch __builtins__
# so that code using builtins.open() is redirected as well.
cwd_open = self._make_cwd_open()
⋮----
builtins = combined.get("__builtins__")
⋮----
# ContextVar-based stdout/stderr capture
stdout_buf = io.StringIO()
stderr_buf = io.StringIO()
stdout_token = _capture_stdout.set(stdout_buf)
stderr_token = _capture_stderr.set(stderr_buf)
⋮----
# Register trace callbacks if needed
⋮----
# Merge any ContextVar-captured output with executor output
cv_stdout = stdout_buf.getvalue()
cv_stderr = stderr_buf.getvalue()
⋮----
stdout = cv_stdout + stdout
⋮----
stderr = cv_stderr + stderr
⋮----
def execute_code(self, code: str, trace: REPLTrace | None = None) -> REPLResult
⋮----
"""Execute code synchronously in the sandboxed namespace.

        Uses _EXEC_LOCK to serialize access to process-global state
        (os.chdir, sys.stdout/stderr) so that concurrent REPLs in
        threads do not race.

        Enforces self.sync_timeout seconds via ThreadPoolExecutor.
        """
start_time = time.perf_counter()
⋮----
timed_out = False
⋮----
pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
future = pool.submit(self._execute_code_inner, code, trace)
⋮----
timed_out = True
stdout = ""
stderr = (
⋮----
# Shut down without waiting for the timed-out thread to finish,
# so it doesn't overwrite _last_exec_error.
⋮----
"""Execute code in a worker thread via the thread bridge.

        Creates a one-shot ``ThreadPoolExecutor`` and runs
        ``_execute_code_threadsafe`` in it via ``loop.run_in_executor``.
        This is the execution path used when the thread bridge is active
        (REPL code may call sync ``llm_query()`` which dispatches back
        to the event loop via ``run_coroutine_threadsafe``).

        Returns a ``REPLResult`` matching the contract of ``execute_code``.
        """
⋮----
# Clear cancellation token for this code block (GAP-EL-004).
# Each execute_code_threaded invocation starts with a fresh state
# so a previous timeout does not poison the next code block.
⋮----
loop = asyncio.get_running_loop()
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
⋮----
# Signal orphaned worker thread to abort any future
# llm_query() calls instead of submitting new child
# dispatches to the event loop (GAP-EL-004).
⋮----
def _make_cwd_open(self)
⋮----
"""Return an open() wrapper that resolves relative paths against self.temp_dir.

        This avoids the need for os.chdir() which modifies process-global state
        and is unsafe when multiple async REPL instances run concurrently.
        """
temp_dir = self.temp_dir
builtin_open = open
⋮----
def _cwd_open(file, *args, **kwargs)
⋮----
file = os.path.join(temp_dir, file)
⋮----
def cleanup(self) -> None
⋮----
"""Clean up temp directory, executor, and reset state."""
⋮----
def __enter__(self)
⋮----
def __exit__(self, exc_type, exc_val, exc_tb)
⋮----
def __del__(self)
````

## File: rlm_adk/types.py
````python
########################################################
########   Structured Output Schema for Reasoning  #####
⋮----
class ReasoningOutput(BaseModel)
⋮----
"""Structured output schema for the reasoning agent's final answer.

    Used as ``output_schema`` on the reasoning ``LlmAgent`` so ADK
    emits a ``set_model_response`` tool call that the model fills with
    validated JSON matching this schema.
    """
⋮----
final_answer: str = Field(description="Complete final answer to the query.")
reasoning_summary: str = Field(default="", description="Brief reasoning summary.")
⋮----
class ReasoningObservability(BaseModel)
⋮----
"""Persistable reasoning-output observability payload."""
⋮----
visible_output_text: str = ""
thought_text: str = ""
thoughts_tokens: int = 0
raw_output: Any = None
parsed_output: dict[str, Any] | None = None
final_answer: str = ""
reasoning_summary: str = ""
⋮----
def parse_reasoning_output(raw: Any) -> ReasoningObservability
⋮----
"""Normalize a reasoning output_key payload for observability storage."""
payload = ReasoningObservability(raw_output=raw)
⋮----
parsed: dict[str, Any] | None = None
⋮----
parsed = dict(raw)
⋮----
decoded = json.loads(raw)
⋮----
decoded = None
⋮----
parsed = decoded
⋮----
def _serialize_value(value: Any) -> Any
⋮----
"""Convert a value to a JSON-serializable representation."""
⋮----
# Try to convert to string for other types
⋮----
########    Types for Worker LLM Results       #########
⋮----
class LLMResult(str)
⋮----
"""String subclass carrying worker call metadata.

    Backward-compatible: passes isinstance(x, str), works in f-strings,
    concatenation, etc. But REPL code can inspect error state:

        result = llm_query("prompt")
        if result.error:
            if result.error_category == "TIMEOUT":
                raise RuntimeError(f"Worker timed out: {result}")
            elif result.error_category == "RATE_LIMIT":
                await asyncio.sleep(5)
                result = llm_query("prompt")  # retry
    """
⋮----
error: bool = False
error_category: str | None = (
⋮----
None  # TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, FORMAT, UNKNOWN
⋮----
http_status: int | None = None
finish_reason: str | None = None  # STOP, SAFETY, RECITATION, MAX_TOKENS
input_tokens: int = 0
output_tokens: int = 0
⋮----
model: str | None = None
wall_time_ms: float = 0.0
visible_text: str | None = None
thought_text: str | None = None
raw_output: Any | None = None
parsed: Any = None  # Validated structured output (any type when output_schema used)
⋮----
def __new__(cls, text: str, **kwargs: Any) -> "LLMResult"
⋮----
instance = super().__new__(cls, text)
⋮----
@property
    def thought_tokens(self) -> int
⋮----
"""Backward-compatible alias for older telemetry code."""
⋮----
########    Types for LM Cost Tracking         #########
⋮----
class ModelUsageSummary(BaseModel)
⋮----
total_calls: int
total_input_tokens: int
total_output_tokens: int
⋮----
def to_dict(self)
⋮----
@classmethod
    def from_dict(cls, data: dict) -> "ModelUsageSummary"
⋮----
class UsageSummary(BaseModel)
⋮----
model_usage_summaries: dict[str, ModelUsageSummary]
⋮----
@classmethod
    def from_dict(cls, data: dict) -> "UsageSummary"
⋮----
########   Types for REPL and RLM Iterations   #########
⋮----
class RLMChatCompletion(BaseModel)
⋮----
"""Record of a single LLM call made from within the environment."""
⋮----
root_model: str
prompt: str | dict[str, Any]
response: str
usage_summary: UsageSummary
execution_time: float
finish_reason: str | None = None
⋮----
visible_response: str | None = None
thought_response: str | None = None
raw_response: Any | None = None
parsed_response: dict[str, Any] | None = None
⋮----
@classmethod
    def from_dict(cls, data: dict) -> "RLMChatCompletion"
⋮----
class REPLResult(BaseModel)
⋮----
stdout: str
stderr: str
locals: dict
execution_time: float | None = None
llm_calls: list[RLMChatCompletion] = Field(default_factory=list)
trace: dict[str, Any] | None = None
⋮----
def __str__(self)
⋮----
result = {
⋮----
########   Completion & Lineage Envelopes      #########
⋮----
class CompletionEnvelope(BaseModel)
⋮----
"""Canonical in-memory result object per reasoning run."""
⋮----
terminal: bool
mode: Literal["structured", "text", "error"]
output_schema_name: str | None = None
validated_output: Any = None
⋮----
display_text: str = ""
⋮----
error_category: str | None = None
⋮----
class LineageEdge(BaseModel)
⋮----
"""Tree-structure edge: where in the execution graph this decision sits."""
⋮----
depth: int
fanout_idx: int | None = None
parent_depth: int | None = None
parent_fanout_idx: int | None = None
branch: str | None = None
terminal: bool = False
decision_mode: Literal[
structured_outcome: Literal[
⋮----
class ProvenanceRecord(BaseModel)
⋮----
"""Identity/context: who produced this decision and under what config."""
⋮----
version: Literal["v1"] = "v1"
agent_name: str
invocation_id: str | None = None
session_id: str | None = None
⋮----
class LineageEnvelope(BaseModel)
⋮----
"""Backward-compat composite. Prefer LineageEdge + ProvenanceRecord."""
⋮----
@property
    def lineage(self) -> LineageEdge
⋮----
"""Extract the tree-structure edge from this envelope."""
⋮----
@property
    def provenance(self) -> ProvenanceRecord
⋮----
"""Extract the identity/context record from this envelope."""
⋮----
def render_completion_text(validated_output: Any, fallback_text: str = "") -> str
⋮----
"""Deterministic renderer for final user-visible text.

    Priority:
    1. dict with final_answer str -> use it
    2. validated string -> use it
    3. other non-None -> compact JSON
    4. None -> fallback_text
    """
⋮----
fa = validated_output.get("final_answer")
````

## File: rlm_adk/utils/prompts.py
````python
# ---------------------------------------------------------------------------
# STATIC INSTRUCTION (for LlmAgent static_instruction= parameter)
⋮----
# The complete RLM system prompt.
# Passed as LlmAgent static_instruction= which ADK places into
# system_instruction WITHOUT template processing, so raw curly braces
# in Python f-string code examples are safe and correct.
#
# Usage:
#   static_instruction = RLM_STATIC_INSTRUCTION  (raw, not template-processed)
#   instruction        = RLM_DYNAMIC_INSTRUCTION  (template with {var?})
⋮----
RLM_STATIC_INSTRUCTION = textwrap.dedent("""\
⋮----
# DYNAMIC INSTRUCTION (uses ADK state variable injection)
⋮----
# This string is set as the LlmAgent instruction= parameter.
# ADK replaces {var} with session state values at runtime.
# The ? suffix makes vars optional (no error if missing).
⋮----
RLM_DYNAMIC_INSTRUCTION = textwrap.dedent("""\
⋮----
# CHILD STATIC INSTRUCTION (condensed)
⋮----
# Used by child orchestrators spawned at depth > 0.  Keeps tool descriptions,
# REPL helpers, and general strategy guidance.
# ~1/3 the size of RLM_STATIC_INSTRUCTION.
⋮----
RLM_CHILD_STATIC_INSTRUCTION = textwrap.dedent("""\
````

## File: rlm_adk/callbacks/reasoning.py
````python
"""Reasoning Agent callbacks.

before_model_callback: Records per-invocation token accounting (observe-only).
    ADK manages system_instruction and contents natively via its request
    processors.  This callback does NOT modify the LLM request.

after_model_callback: Records per-invocation token accounting from
    usage_metadata.  The collapsed orchestrator reads the final answer
    from the output_key ("reasoning_output").

reasoning_test_state_hook: Test-only before_model_callback that writes a
    guillemet-marked dict to callback_context.state under the key
    ``cb_reasoning_context``.  ADK resolves ``{cb_reasoning_context?}``
    from state on subsequent iterations.
"""
⋮----
def _extract_system_instruction_text(llm_request: LlmRequest) -> str
⋮----
"""Extract system_instruction text that ADK set from static_instruction."""
⋮----
si = llm_request.config.system_instruction
⋮----
# system_instruction may be a Content object with parts
⋮----
def _extract_response_text(llm_response: LlmResponse) -> tuple[str, str]
⋮----
"""Split visible output text from hidden thought text."""
output_parts: list[str] = []
thought_parts: list[str] = []
⋮----
def _usage_int(usage: Any, attr: str) -> int
⋮----
"""Return an integer usage field, guarding against MagicMock values in tests."""
value = getattr(usage, attr, 0)
⋮----
def _agent_runtime(callback_context)
⋮----
"""Extract invocation context and agent.

    Note: inv.branch and inv.invocation_id are private ADK attributes.
    """
inv = callback_context._invocation_context
agent = inv.agent
⋮----
def _build_lineage(callback_context) -> LineageEnvelope
⋮----
"""Build a LineageEnvelope from agent runtime attrs."""
⋮----
"""Observe-only: record per-invocation token accounting.

    ADK has already set:
      - system_instruction from static_instruction (the stable system prompt)
      - SkillToolset XML appended to system_instruction (if skills are enabled)
      - resolved instruction template in contents (dynamic context metadata)
      - full conversation history in contents (via contents.request_processor)

    This callback:
      1. Ensures config exists for accounting reads
      2. Records per-invocation token accounting (system_chars, prompt_chars,
         content_count) and stores request metadata on the agent
      3. Returns None without modifying the LLM request

    ADK 1.27 handles dynamic instruction placement natively via its request
    processors.  No relocation of content into system_instruction is needed.
    """
# Ensure config exists for accounting reads
⋮----
# --- Per-invocation token accounting (observe-only) ---
system_instruction_text = _extract_system_instruction_text(llm_request)
contents = llm_request.contents or []
total_prompt_chars = sum(
system_chars = len(system_instruction_text)
content_count = len(contents)
⋮----
# Store request metadata on the agent instead of session state.
# ObservabilityPlugin reads _rlm_pending_request_meta from the agent.
⋮----
request_meta = {
⋮----
"""Record per-invocation token accounting from usage_metadata.

    Stores response metadata on the agent as ``_rlm_last_response_meta``
    and injects lineage into ``llm_response.custom_metadata``.  The
    collapsed orchestrator reads the final answer from the output_key
    ("reasoning_output") and token data from the agent attr.
    """
# --- Per-invocation token accounting from usage_metadata ---
usage = llm_response.usage_metadata
⋮----
finish_reason = getattr(getattr(llm_response, "finish_reason", None), "name", None)
⋮----
input_tokens = _usage_int(usage, "prompt_token_count")
output_tokens = _usage_int(usage, "candidates_token_count")
thought_tokens = _usage_int(usage, "thoughts_token_count")
⋮----
input_tokens = 0
output_tokens = 0
thought_tokens = 0
⋮----
# Parse reasoning_summary from JSON-shaped visible text
reasoning_summary = ""
⋮----
parsed = json.loads(visible_text)
⋮----
parsed = None
⋮----
reasoning_summary = parsed.get("reasoning_summary", "") or ""
⋮----
# --- Store on agent-local metadata (not session state) ---
⋮----
lineage = _build_lineage(callback_context)
⋮----
# Inject lineage into llm_response.custom_metadata
meta = dict(llm_response.custom_metadata or {})
⋮----
response_meta = {
⋮----
# Return None -- observe only, don't alter the response
⋮----
# ---------------------------------------------------------------------------
# Test-only hook: state dict → systemInstruction verification
⋮----
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
⋮----
# Patch the already-resolved template text in contents so the dict
# appears on the FIRST iteration too (ADK resolves {cb_reasoning_context?}
# before before_model_callback fires, so iter 0 would otherwise be empty).
# The patched text stays in contents where the model sees it directly.
dict_str = str(context_dict)
placeholder = "Callback state: \n"
⋮----
# Test-only hook: tool state dict → systemInstruction verification
⋮----
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
⋮----
return None  # Proceed with normal tool execution
````

## File: rlm_adk/plugins/sqlite_tracing.py
````python
"""SqliteTracingPlugin - Local SQLite-based telemetry.

Captures structured telemetry from ADK callbacks into a local traces.db file
using a 3-table schema: traces (enriched), telemetry, session_state_events.

No external dependencies beyond the Python standard library (sqlite3).
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
# Thin aliases so the rest of the file needs minimal changes.
_parse_key = parse_depth_key
_should_capture = should_capture_state_key
⋮----
# ---- Key categorization (plugin-specific, not shared) ----
⋮----
def _categorize_key(key: str) -> str
⋮----
"""Categorize a state key for the session_state_events table.

    Only categorizes keys that actually flow through state_delta.
    Per-model-call lineage is captured directly in the telemetry table,
    not via session_state_events.
    """
⋮----
# ---- Value typing helper ----
⋮----
def _typed_value(value: Any) -> tuple[str, int | None, float | None, str | None, str | None]
⋮----
"""Return (value_type, value_int, value_float, value_text, value_json)."""
⋮----
"""Return a typed row payload."""
⋮----
def _serialize_payload(value: Any) -> str | None
⋮----
"""Serialize arbitrary telemetry payloads without truncation."""
⋮----
# ---- Schema SQL ----
⋮----
_SCHEMA_SQL = """
⋮----
class SqliteTracingPlugin(BasePlugin)
⋮----
"""ADK Plugin that writes structured telemetry to a local SQLite database.

    Uses a 3-table schema:
    - traces: One row per invocation, enriched with OBS keys at run end.
    - telemetry: One row per model call or tool invocation (structured columns).
    - session_state_events: One row per curated state key change from events.

    Provides 4 SQL views for query convenience:
    - session_state_events_unified: COALESCE across typed value columns.
    - execution_observations: Timing, tokens, REPL outcomes, errors.
    - telemetry_completions: ``set_model_response`` outcomes only.
    - lineage_records: Tree-structure edges and provenance.

    The legacy ``spans`` table is no longer created on fresh DBs but is
    retained on pre-existing databases for backward compatibility.

    The plugin is observe-only: all callbacks return None and never block
    execution. Database write errors are caught and logged as warnings.

    Args:
        name: Plugin name (default "sqlite_tracing").
        db_path: Path to the SQLite database file (default ".adk/traces.db").
            Created if it does not exist. Parent directories are created.
    """
⋮----
# Pending telemetry: callback/tool context id -> (telemetry_id, start_time)
⋮----
# Instance-local counters (no longer read from obs: session state)
⋮----
# Deferred tool lineage entries (flushed when agent callbacks complete)
⋮----
# Monotonic counter for session_state_events per trace
⋮----
# Legacy: kept for backward compat in agent span tracking
⋮----
def _init_db(self) -> None
⋮----
"""Initialize the database connection and create tables."""
⋮----
# Try full schema creation (works for fresh DBs).
# On existing DBs, CREATE TABLE IF NOT EXISTS is a no-op for
# tables that already exist, but CREATE INDEX may fail if
# referenced columns are missing. We catch and continue.
⋮----
# Always run migration to add missing columns to existing tables.
⋮----
# Re-run CREATE INDEX statements after migration has added columns.
⋮----
def _migrate_schema(self) -> None
⋮----
"""Add missing columns to existing tables.

        CREATE TABLE IF NOT EXISTS is a no-op for tables that already exist
        but have fewer columns than the current schema. This method inspects
        existing columns via PRAGMA table_info and adds any missing ones.
        """
⋮----
# Expected columns per table: (column_name, column_def)
_EXPECTED_COLUMNS: dict[str, list[tuple[str, str]]] = {
⋮----
existing = {
⋮----
def _new_id(self) -> str
⋮----
"""Generate a new unique ID."""
⋮----
@staticmethod
    def _pending_key(obj: Any) -> int
⋮----
"""Return a stable in-process key for pairing before/after callbacks."""
⋮----
def make_telemetry_finalizer(self) -> "Callable[[int, dict], None]"
⋮----
"""Create a closure that finalizes pending tool telemetry rows.

        The returned callable uses the same ``id(tool_context)`` key as
        ``_pending_key()`` to look up the pending telemetry row inserted by
        ``before_tool_callback``.  REPLTool calls this at every return path
        so that tool rows are finalized even when ADK's ``after_tool_callback``
        does not fire (GAP-06).

        The finalizer is idempotent: if ``after_tool_callback`` already
        consumed the pending entry, the finalizer is a no-op.
        """
pending = self._pending_tool_telemetry
update = self._update_telemetry
coerce_int = self._coerce_int
⋮----
def _finalize(tool_context_id: int, result: dict) -> None
⋮----
entry = pending.pop(tool_context_id, None)
⋮----
return  # Already finalized by after_tool_callback
⋮----
end_time = time.time()
duration_ms = (end_time - start_time) * 1000
update_kwargs: dict[str, Any] = {
⋮----
# REPL enrichment from result dict
⋮----
stdout = result.get("stdout")
stderr = result.get("stderr")
⋮----
@staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int
⋮----
"""Best-effort integer coercion for callback payloads and mocks."""
⋮----
"""Select the best-matching last_repl_result payload from tool state."""
⋮----
exact_match: dict[str, Any] | None = None
fallback: dict[str, Any] | None = None
⋮----
exact_match = value
⋮----
fallback = value
⋮----
# ---- Telemetry write helpers ----
⋮----
"""Insert a telemetry row."""
⋮----
cols = ["telemetry_id", "trace_id", "event_type", "start_time"]
vals: list[Any] = [telemetry_id, self._trace_id, event_type, start_time]
⋮----
placeholders = ", ".join("?" for _ in cols)
col_str = ", ".join(cols)
⋮----
def _update_telemetry(self, telemetry_id: str, **kwargs: Any) -> None
⋮----
"""Update a telemetry row with additional fields."""
⋮----
set_clauses = ", ".join(f"{col} = ?" for col in kwargs)
vals = list(kwargs.values()) + [telemetry_id]
⋮----
# ---- Session state events write helper ----
⋮----
"""Insert a session_state_events row for a curated key."""
⋮----
category = _categorize_key(base_key)
⋮----
# ---- Completion record write helper ----
⋮----
envelope: Any,  # CompletionEnvelope
⋮----
"""Persist a CompletionEnvelope as a first-class completion_records row."""
⋮----
# ---- Lifecycle callbacks ----
⋮----
"""Create a new trace row for this invocation."""
⋮----
# Build config snapshot from state and env vars
state = invocation_context.session.state
config: dict[str, Any] = {}
⋮----
val = os.environ.get(env_key)
⋮----
"""Build trace summary stats by querying the telemetry table.

        Returns a dict of column values for the traces UPDATE.
        This replaces the old approach of reading obs:* session-state
        keys, making the telemetry table the authoritative source.
        """
summary: dict[str, Any] = {}
⋮----
tid = self._trace_id
⋮----
# Aggregate model-call telemetry
row = self._conn.execute(
⋮----
# Per-model usage breakdown
model_rows = self._conn.execute(
⋮----
mu: dict[str, Any] = {}
⋮----
# Finish-reason counts (non-STOP)
fr_rows = self._conn.execute(
fr_map = {r.lower(): c for r, c in fr_rows}
⋮----
# Tool invocation summary
tool_rows = self._conn.execute(
⋮----
tool_summary = {name: cnt for name, cnt in tool_rows}
⋮----
# Max depth reached from telemetry depth column
depth_row = self._conn.execute(
⋮----
# Child dispatch counts from tool_call rows at depth > 0
child_row = self._conn.execute(
⋮----
# Structured output failures (set_model_response with
# structured_outcome = 'retry_exhausted')
sf_row = self._conn.execute(
⋮----
async def after_run_callback(self, *, invocation_context: InvocationContext) -> None
⋮----
"""Finalize the trace row with summary stats from telemetry."""
⋮----
final_answer = state.get(FINAL_RESPONSE_TEXT, "")
root_prompt = state.get("root_prompt", "")
prompt_hash = None
⋮----
prompt_hash = hashlib.sha256(root_prompt.encode()).hexdigest()
⋮----
# Build summary from telemetry table rows
summary = self._build_trace_summary_from_telemetry()
⋮----
None,  # child_total_batch_dispatches
None,  # child_error_counts
⋮----
None,  # artifact_bytes_saved: no longer tracked via state
None,  # per_iteration_breakdown
⋮----
# Write path 2: orchestrator-level CompletionEnvelope
inv_agent = getattr(invocation_context, "agent", None)
orch_completion = getattr(inv_agent, "_rlm_terminal_completion", None)
⋮----
producer = (
anchor_row = self._conn.execute(
⋮----
# ---- Agent callbacks ----
⋮----
"""Track agent name for parent context (no span write)."""
⋮----
agent_name = getattr(agent, "name", "unknown")
⋮----
"""Pop agent from context stack, flush deferred lineage, write child completion."""
⋮----
# Write path 3: child orchestrator completion records.
# Only write for RLMOrchestratorAgent at depth > 0.
# LlmAgent (reasoning agent) completions are captured via
# the deferred tool lineage flush above (write path 1).
⋮----
agent_completion = getattr(agent, "_rlm_terminal_completion", None)
⋮----
agent_depth = getattr(agent, "depth", 0)
# Only capture for child orchestrators (depth > 0), not root
⋮----
# ---- Model callbacks ----
⋮----
"""Insert a telemetry row for model_call and store ID for pairing."""
⋮----
model = llm_request.model or "unknown"
num_contents = len(llm_request.contents) if llm_request.contents else 0
iteration = callback_context.state.get(ITERATION_COUNT, 0)
agent_name = self._agent_span_stack[-1] if self._agent_span_stack else None
⋮----
# Resolve agent from invocation context
inv_ctx = getattr(
agent = getattr(inv_ctx, "agent", None)
⋮----
# Compute depth/fanout/parent from agent attrs
depth = self._coerce_int(getattr(agent, "_rlm_depth", 0))
fanout_idx = getattr(agent, "_rlm_fanout_idx", None)
parent_depth = getattr(agent, "_rlm_parent_depth", None)
parent_fanout_idx = getattr(agent, "_rlm_parent_fanout_idx", None)
output_schema_name = getattr(agent, "_rlm_output_schema_name", None)
⋮----
# Compute prompt/system chars directly from
# llm_request instead of CONTEXT_WINDOW_SNAPSHOT
prompt_chars = 0
system_chars = 0
⋮----
parts = getattr(content, "parts", None)
⋮----
t = getattr(part, "text", None)
⋮----
config = getattr(llm_request, "config", None)
sys_inst = getattr(config, "system_instruction", None)
⋮----
si_parts = getattr(sys_inst, "parts", None)
⋮----
# Branch / invocation / session identifiers
branch = getattr(inv_ctx, "branch", None)
invocation_id = getattr(inv_ctx, "invocation_id", None)
session = getattr(inv_ctx, "session", None)
session_id = getattr(session, "id", None)
⋮----
call_number = self._model_call_count
skill_instruction = callback_context.state.get(DYN_SKILL_INSTRUCTION)
⋮----
telemetry_id = self._new_id()
start_time = time.time()
⋮----
"""Update telemetry row with tokens, finish_reason, duration,
        and custom_metadata['rlm'] lineage."""
⋮----
pending = self._pending_model_telemetry.pop(
⋮----
tokens_in = 0
tokens_out = 0
thought_tokens = 0
⋮----
tokens_in = self._coerce_int(
tokens_out = self._coerce_int(
thought_tokens = self._coerce_int(
⋮----
finish_reason = None
⋮----
finish_reason = (
⋮----
# Build lineage from agent attrs (plugin fires before agent's
# after_model_callback, so custom_metadata isn't populated yet).
inv_ctx = getattr(callback_context, "_invocation_context", None)
agent = getattr(inv_ctx, "agent", None) if inv_ctx else None
rlm_meta = None
⋮----
rlm_meta = {
custom_metadata_json = None
⋮----
custom_metadata_json = json.dumps(rlm_meta, default=str)
⋮----
# Standalone telemetry row
standalone_id = self._new_id()
insert_kw: dict[str, Any] = {
⋮----
"""Mark the pending model telemetry row as an error."""
⋮----
# ---- Deferred lineage flush ----
⋮----
def _flush_deferred_tool_lineage(self) -> None
⋮----
"""Flush deferred tool lineage entries.

        Called at points where agent callbacks have completed
        (before_model, after_agent, after_run), so _rlm_lineage_status
        is now populated by worker_retry.after_tool_cb.
        """
⋮----
agent = entry["agent"]
status = getattr(agent, "_rlm_lineage_status", None) or {}
kw: dict[str, Any] = {}
so = status.get("structured_outcome")
⋮----
is_terminal = bool(status.get("terminal"))
⋮----
# Write path 1: completion_records from deferred flush
completion = getattr(agent, "_rlm_terminal_completion", None)
⋮----
# ---- Tool callbacks ----
⋮----
"""Insert a telemetry row for tool_call with full scope."""
⋮----
tool_name = getattr(tool, "name", str(tool))
⋮----
# Resolve agent first (moved above depth resolution for BUG-014)
inv_ctx = getattr(tool_context, "_invocation_context", None)
⋮----
# BUG-014 fix: resolve depth from agent._rlm_depth (set by
# orchestrator at construction), falling back to tool._depth
# for REPLTool backward compat.  Matches before_model_callback.
agent_depth = getattr(agent, "_rlm_depth", None)
⋮----
tool_depth = self._coerce_int(agent_depth)
⋮----
tool_depth = self._coerce_int(getattr(tool, "_depth", 0))
iteration = None
state = getattr(tool_context, "state", None)
⋮----
depth_key_name = (
iteration = state.get(depth_key_name)
⋮----
# Serialize tool args for non-execute_code tools (code args are
# large and already captured via repl_submitted_code state key).
tool_args_json = None
⋮----
tool_args_json = json.dumps(tool_args, default=str)
⋮----
"""Update the tool telemetry row with result preview,
        duration, and lineage status."""
⋮----
pending = self._pending_tool_telemetry.pop(
⋮----
# Persist decision_mode / lineage
⋮----
# Defer structured fields — _rlm_lineage_status is set by
# worker_retry.after_tool_cb which fires AFTER plugin callbacks.
⋮----
# Extract skill name from tool response if available
⋮----
# NOTE: _adk_activated_skill_* keys are intentionally NOT
# added to CURATED_STATE_PREFIXES. Skill activation tracking
# flows through the telemetry table's skill_name_loaded
# column (reviewer refinement #4).
⋮----
# REPL enrichment
⋮----
repl_state = self._resolve_repl_state(
⋮----
trace_summary = repl_state.get("trace_summary")
⋮----
# ---- Event callback ----
⋮----
"""Capture curated state_delta keys as session_state_events rows."""
⋮----
now = time.time()
author = event.author
⋮----
# Capture curated state_delta keys
⋮----
# Keep artifact_delta tracking (backward compat via SSE)
⋮----
# ---- Cleanup ----
⋮----
async def close(self) -> None
⋮----
"""Close the database connection."""
````

## File: rlm_adk/tools/repl_tool.py
````python
"""REPLTool -- ADK BaseTool wrapping LocalREPL for function-calling execution.

Replaces regex-parsed ```repl code blocks with a proper ADK tool that the
model calls via function calling. The tool:

- Executes Python code in a persistent LocalREPL environment
- Enforces a configurable call limit
- Records execution traces when a trace_holder list is provided
- Applies minimal working-state patches via post_dispatch_state_patch_fn
"""
⋮----
_CALL_LIMIT_MSG = "REPL call limit reached. Submit your final answer now."
⋮----
class REPLTool(BaseTool)
⋮----
"""ADK tool that executes Python code in a persistent REPL environment.

    Variables persist between calls. Returns stdout, stderr, and current
    variable values.
    """
⋮----
def _get_declaration(self) -> FunctionDeclaration
⋮----
def _finalize_telemetry(self, tool_context: ToolContext, result: dict) -> None
⋮----
"""Invoke the telemetry_finalizer if wired, using id(tool_context) as key."""
⋮----
pass  # Observe-only — never block execution
⋮----
async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> dict
⋮----
code = args["code"]
⋮----
# OG-03 fix: persist submitted code for observability
code_hash = hashlib.sha256(code.encode()).hexdigest()
⋮----
# Persist submitted code as a versioned artifact file
⋮----
# Track iteration count in session state for observability
⋮----
result = {
⋮----
llm_calls_made = False
⋮----
# Create a REPLTrace when trace_holder is provided so dispatch
# closures and LocalREPL can record timing/LLM-call data.
trace: REPLTrace | None = None
⋮----
trace = REPLTrace(
# Orchestrator passes [None]; set [0] so dispatch closures see
# the live trace.  Empty lists (e.g. from tests) get an append.
⋮----
exec_code = code
⋮----
# Build read-only state snapshot for REPL introspection.
_state_snapshot: dict[str, Any] = {}
⋮----
scoped = depth_key(key, self._depth, self._fanout_idx) if key in DEPTH_SCOPED_KEYS else key
val = tool_context.state.get(scoped)
⋮----
_state_snapshot[key] = val  # Use unscoped key name for clean API
⋮----
# Inject runtime lineage metadata from the tool/agent for
# non-circular test verification. After the CURRENT_DEPTH fix,
# _rlm_depth and current_depth show the same value, but they
# have independent provenance paths: _rlm_depth comes from the
# REPLTool constructor (set by orchestrator), while current_depth
# flows through the session state event pipeline. Keeping both
# enables cross-check diagnostics when one path fails.
⋮----
_inv = getattr(tool_context, "_invocation_context", None)
_agent = getattr(_inv, "agent", None) if _inv is not None else None
_agent_name = getattr(_agent, "name", None) if _agent is not None else None
⋮----
# Unified result variable for the finally-based telemetry finalizer
_final_result: dict | None = None
⋮----
result = await self.repl.execute_code_threaded(exec_code, trace=trace)
⋮----
# OG-04 fix: ensure end_time is set so trace summary is non-negative
⋮----
# Apply working-state patch (e.g. skill instruction restore)
⋮----
# Write LAST_REPL_RESULT even on cancellation for observability
⋮----
_final_result = {
⋮----
# Write LAST_REPL_RESULT even on exception for observability
⋮----
# Apply minimal working-state patch after dispatch
⋮----
# Determine execution mode from trace or default
exec_mode = trace.execution_mode if trace else "thread_bridge"
⋮----
# Write LAST_REPL_RESULT summary for observability plugins
last_repl: dict[str, Any] = {
⋮----
# Skip ADK's post-tool summarization call for large outputs to save tokens
output_len = len(result.stdout) + len(result.stderr)
⋮----
# Extract JSON-serializable variables from REPL locals.
# We attempt json.dumps to catch nested non-serializable objects
# (e.g., a dict containing module references) that would cause ADK's
# deepcopy to fail with TypeError.
variables: dict[str, Any] = {}
⋮----
pass  # Skip non-serializable values (incl. circular refs)
````

## File: rlm_adk/agent.py
````python
"""RLM ADK Application - Wires all components into a runnable ADK App.

This module provides:
- create_rlm_runner(): Factory to create the configured Runner (App + plugins + services)
- create_rlm_app(): Factory to create the configured App with plugins
- create_rlm_orchestrator(): Factory to create the configured orchestrator
- create_reasoning_agent(): Factory to create the reasoning LlmAgent

Architecture (per ADK runtime event-loop):

    Agent -> App (plugins) -> Runner (services + event loop)

The ``Runner`` is the central orchestrator.  It drives the event loop,
receives Events yielded by agent logic, commits state/artifact changes
via Services, and forwards processed events upstream.

The ADK CLI (``adk run``, ``adk web``) discovers the module-level ``app``
symbol and creates its own ``Runner`` internally.  Programmatic callers
should use ``create_rlm_runner()`` which returns a ``Runner``
with plugins, session service, and artifact service already wired.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
def _is_litellm_active() -> bool
⋮----
"""Check if LiteLLM Router mode is enabled via RLM_ADK_LITELLM env var."""
⋮----
def _resolve_model(model_str, tier=None)
⋮----
"""Resolve model string to either plain str (Gemini) or LiteLlm (Router).

    When ``RLM_ADK_LITELLM`` is not active, returns *model_str* unchanged.
    When active, creates a ``LiteLlm`` object backed by the singleton Router.

    CRIT-1: If *model_str* is already a non-string (e.g. a ``LiteLlm`` object),
    it is returned as-is to prevent double-wrapping on recursive dispatch.
    """
⋮----
return model_str  # Already a LiteLlm object (CRIT-1)
⋮----
logical_name = tier or os.getenv("RLM_LITELLM_TIER", "reasoning")
⋮----
# Load project-root .env so model and API key env vars are available.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
⋮----
def _project_root() -> Path
⋮----
"""Resolve the project root directory (contains pyproject.toml).

    Uses __file__ to anchor resolution, matching the .env pattern at line 54.
    Used only for repo-level paths (e.g. .env loading).
    """
⋮----
def _package_dir() -> Path
⋮----
"""Resolve the rlm_adk package directory (contains agent.py).

    This is the directory where ``adk run`` roots its ``.adk`` storage.
    Use this (not ``_project_root()``) as the anchor for all plugin and
    service file paths so that custom plugins write to the same ``.adk/``
    directory as ADK's built-in session and artifact services.
    """
⋮----
_DEFAULT_RETRY_OPTIONS = HttpRetryOptions(
⋮----
_DEFAULT_DB_PATH = str(_package_dir() / ".adk" / "session.db")
_DEFAULT_ARTIFACT_ROOT = str(_package_dir() / ".adk" / "artifacts")
⋮----
_SQLITE_STARTUP_PRAGMAS = """
⋮----
"""Create the default SqliteSessionService with performance pragmas.

    Ensures the parent directory exists, applies WAL mode and performance
    pragmas via a one-time synchronous connection, then returns the ADK
    SqliteSessionService instance.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``RLM_SESSION_DB`` env var, falling back to ``.adk/session.db``.

    Returns:
        A configured SqliteSessionService instance.
    """
⋮----
resolved_path = db_path or os.getenv("RLM_SESSION_DB", _DEFAULT_DB_PATH)
⋮----
# Ensure parent directory exists
db_dir = Path(resolved_path).parent
⋮----
# Apply persistent pragmas via synchronous sqlite3 connection.
# WAL mode persists on disk once set; other pragmas are per-connection
# but WAL is the critical one for concurrent reads.
conn = sqlite3.connect(resolved_path)
⋮----
"""Build a GenerateContentConfig with HTTP retry options.

    Args:
        retry_config: Optional dict with keys matching ``HttpRetryOptions``
            fields (``attempts``, ``initial_delay``, ``max_delay``,
            ``exp_base``, ``jitter``, ``http_status_codes``).  When ``None``,
            sensible defaults (3 attempts, exponential backoff) are used.
            Pass an empty dict ``{}`` to use the SDK's built-in defaults.
    """
⋮----
retry_opts = HttpRetryOptions(**retry_config) if retry_config else None
⋮----
retry_opts = _DEFAULT_RETRY_OPTIONS
⋮----
"""Create the ReasoningAgent (main LLM for depth=0 reasoning).

    Args:
        model: The LLM model identifier.
        static_instruction: Stable system prompt content (code examples, REPL
            guidance).  Passed as LlmAgent ``static_instruction=``
            which ADK places into ``system_instruction`` *without* template
            processing, so raw curly braces in code examples are safe.
        dynamic_instruction: Template string with ``{var?}`` state-variable
            placeholders (repo_url, root_prompt, etc.).
            Passed as LlmAgent ``instruction=``; when ``static_instruction``
            is also set, ADK resolves the template and appends the result to
            ``contents`` as user content.  ADK 1.27 handles positioning
            natively via its request processors.
        thinking_budget: Token budget for the model's built-in thinking/planning.
            Passed to ``BuiltInPlanner`` via ``ThinkingConfig``.  Set to ``0``
            to disable the planner.
        retry_config: Optional dict of retry options passed to the Gemini model's
            ``HttpRetryOptions``.  Keys: ``attempts``, ``initial_delay``,
            ``max_delay``, ``exp_base``, ``jitter``, ``http_status_codes``.
            When ``None`` (default), uses sensible defaults (3 attempts,
            exponential backoff).  Pass an empty dict ``{}`` to use the SDK's
            built-in defaults only.
        tools: Optional list of tools (BaseTool, callables, or BaseToolset)
            to attach to the agent.  When provided, the agent operates in
            tool-calling mode (ADK manages tool call/response history).

    Note:
        ``output_schema`` is intentionally NOT accepted here.  The orchestrator
        wires ``SetModelResponseTool(schema)`` at runtime alongside ``REPLTool``
        so the model chooses between ``execute_code`` and ``set_model_response``.
        Passing ``output_schema`` to ``LlmAgent`` would cause ADK to inject a
        duplicate ``set_model_response`` tool.
    """
litellm_active = _is_litellm_active()
⋮----
planner = None
⋮----
planner = BuiltInPlanner(
⋮----
gcc = _build_generate_content_config(retry_config) if not litellm_active else None
⋮----
resolved_model = _resolve_model(model) if litellm_active else model
⋮----
# ADK manages tool call/response history. Tools are wired at
# runtime by the orchestrator.
⋮----
"""Create the RLMOrchestratorAgent with the reasoning sub-agent."""
resolved_enabled_skills = tuple(enabled_skills) if enabled_skills else ()
reasoning = create_reasoning_agent(
⋮----
# Default WorkerPool if none provided
⋮----
worker_tier = os.getenv("RLM_LITELLM_WORKER_TIER", "worker")
worker_pool = WorkerPool(
⋮----
worker_pool = WorkerPool(default_model=model)
⋮----
kwargs: dict[str, Any] = {
⋮----
"""Create a child orchestrator for recursive dispatch at *depth* > 0.

    The child uses a condensed static instruction (no repomix/repo docs)
    and depth-suffixed output keys to prevent state collisions.

    Args:
        model: The LLM model identifier.
        depth: Nesting depth (must be > 0).
        prompt: The sub-query for this child to solve.
        worker_pool: Optional shared WorkerPool (created if None).
        thinking_budget: Token budget for built-in planner.
        output_schema: Optional Pydantic schema for structured output.
        fanout_idx: Fanout index within a batched dispatch (0 = single/first).
        enabled_skills: Skill names to propagate to child (default empty).
        repo_url: Optional repository URL for dynamic instruction template resolution.
    """
⋮----
# output_schema intentionally NOT set on LlmAgent — the orchestrator
# injects SetModelResponseTool manually at runtime (orchestrator.py:303-305).
# Setting it here too causes ADK's _OutputSchemaRequestProcessor to inject
# a duplicate SetModelResponseTool on every LLM step (same root-agent
# reasoning documented at orchestrator.py:297-302).
⋮----
"""Build the default plugin list.

    ObservabilityPlugin is always included (observe-only, zero overhead on the
    happy path).  When ``RLM_ADK_DEBUG=1`` is set, verbose mode is enabled
    on ObservabilityPlugin (prints summary to stdout).

    LangfuseTracingPlugin is opt-in (default ``False``).  Enable via
    ``langfuse=True`` or ``RLM_ADK_LANGFUSE=1`` env var.

    SqliteTracingPlugin is opt-in by default (``sqlite_tracing=True``).
    Disable via ``sqlite_tracing=False``.  If the plugin module is not yet
    available (Track B), it is silently skipped.
    """
_debug_env = os.getenv("RLM_ADK_DEBUG", "").lower() in ("1", "true", "yes")
plugins: list[BasePlugin] = [
_sqlite_env = os.getenv("RLM_ADK_SQLITE_TRACING", "").lower() in ("1", "true", "yes")
⋮----
_langfuse_env = os.getenv("RLM_ADK_LANGFUSE", "").lower() in ("1", "true", "yes")
⋮----
_repl_trace_env = int(os.getenv("RLM_REPL_TRACE", "0"))
⋮----
_cloud_env = os.getenv("RLM_ADK_CLOUD_OBS", "").lower() in ("1", "true", "yes")
⋮----
_snapshot_env = os.getenv("RLM_CONTEXT_SNAPSHOTS", "").lower() in ("1", "true", "yes")
⋮----
_adk_dir = str(_package_dir() / ".adk")
⋮----
"""Create the full RLM ADK App with plugins wired in.

    This is the recommended entry point for programmatic usage.  The returned
    ``App`` carries the ``ObservabilityPlugin`` (always).  Pass *plugins* to
    override the default plugin list entirely.

    Args:
        model: The LLM model identifier.
        root_prompt: Initial user prompt for the RLM loop.
        persistent: Whether to persist REPL state across invocations.
        worker_pool: Optional WorkerPool for sub-agent dispatch.
        repl: Optional pre-configured REPL environment.
        static_instruction: Stable system prompt content.
        dynamic_instruction: Template string with state-variable placeholders.
        repo_url: Optional repository URL for context.
        plugins: Explicit plugin list.  When ``None`` (default), uses
            :func:`_default_plugins`.
        thinking_budget: Token budget for the reasoning agent's built-in
            planner.  Set to ``0`` to disable.
        langfuse: Enable LangfuseTracingPlugin (default ``False``; also
            enabled via ``RLM_ADK_LANGFUSE=1`` env-var).
        sqlite_tracing: Enable SqliteTracingPlugin (default ``True``; also
            enabled via ``RLM_ADK_SQLITE_TRACING=1`` env-var).
    """
orchestrator = create_rlm_orchestrator(
resolved_plugins = (
⋮----
"""Create the full RLM ADK Runner: App + plugins + services.

    This is the recommended entry point for programmatic usage.  The returned
    ``Runner`` has:

    - The ``App`` with ``ObservabilityPlugin`` (always).
    - A ``SqliteSessionService`` for persistent state (default), or the
      caller-provided session service.
    - A ``FileArtifactService`` for persistent artifact storage (default),
      or the caller-provided artifact service.

    The ``Runner`` drives the ADK event loop: it calls
    ``agent.run_async(ctx)``, receives yielded ``Event`` objects, commits
    ``state_delta`` / ``artifact_delta`` via services, and forwards
    processed events upstream.

    Usage::

        runner = create_rlm_runner(model="gemini-2.5-flash")
        session = await runner.session_service.create_session(
            app_name="rlm_adk", user_id="user",
        )
        async for event in runner.run_async(
            user_id="user", session_id=session.id, new_message=content,
        ):
            print(event)

    Args:
        model: The LLM model identifier.
        root_prompt: Initial user prompt for the RLM loop.
        persistent: Whether to persist REPL state across invocations.
        worker_pool: Optional WorkerPool for sub-agent dispatch.
        repl: Optional pre-configured REPL environment.
        static_instruction: Stable system prompt content.
        dynamic_instruction: Template string with state-variable placeholders.
        repo_url: Optional repository URL for context.
        plugins: Explicit plugin list.  When ``None`` (default), uses
            :func:`_default_plugins`.
        thinking_budget: Token budget for the reasoning agent's built-in
            planner.  Set to ``0`` to disable.
        artifact_service: Optional artifact service to use.  When ``None``
            (default), creates a ``FileArtifactService`` rooted at
            ``.adk/artifacts/`` for persistent storage with rewind support.
            Pass ``InMemoryArtifactService()`` for volatile in-memory storage,
            or any other ``BaseArtifactService`` implementation.
        session_service: Optional session service to use.  When ``None``
            (default), creates a ``SqliteSessionService`` backed by
            ``.adk/session.db`` with WAL mode enabled.  Pass any
            ``BaseSessionService`` implementation to override.
    """
rlm_app = create_rlm_app(
⋮----
# Resolve session service: explicit > default factory
resolved_session_service = session_service or _default_session_service()
⋮----
# Resolve artifact service: explicit > default FileArtifactService
⋮----
artifact_service = FileArtifactService(root_dir=_DEFAULT_ARTIFACT_ROOT)
⋮----
runner = Runner(
⋮----
def _root_agent_model() -> str
⋮----
"""Resolve model used by ADK CLI-discoverable root_agent."""
⋮----
)  # AGENT: DO NOT CHANGE WITHOUT ASKING USER
⋮----
# ADK CLI entrypoint (`adk run rlm_adk`, `adk web`) discovers the ``app``
# symbol first (preferred) with plugins wired in.  The CLI creates its own
# ``Runner`` wrapping the ``App``.  ``root_agent`` is kept for backward
# compatibility with callers that import it directly.
app = create_rlm_app(model=_root_agent_model())
root_agent = app.root_agent
````

## File: rlm_adk/state.py
````python
"""State key constants for the RLM ADK application.

ADK state key prefix scoping:
- (none): Session scope - persists within session
- user: : User scope - persists across sessions for same user
- app: : Application scope - persists across all users/sessions

Note: cache: and obs: prefixes are naming conventions only (session-scoped).
"""
⋮----
# Flow Control Keys
APP_MAX_DEPTH = "app:max_depth"
APP_MAX_ITERATIONS = "app:max_iterations"
CURRENT_DEPTH = "current_depth"
ITERATION_COUNT = "iteration_count"
SHOULD_STOP = "should_stop"
POLICY_VIOLATION = "policy_violation"
⋮----
# REPL Execution Keys
MESSAGE_HISTORY = "message_history"
LAST_REPL_RESULT = "last_repl_result"
FINAL_RESPONSE_TEXT = "final_response_text"
⋮----
# Context Metadata Keys (used by callbacks/observability)
REPO_URL = "repo_url"
ROOT_PROMPT = "root_prompt"
# ENABLED_SKILLS removed — skill catalog system reset
⋮----
# Dynamic Instruction State Keys (session-scoped for ADK instruction template resolution)
# These match the {var?} placeholders in RLM_DYNAMIC_INSTRUCTION so ADK can
# resolve them at runtime via its built-in state variable injection.
DYN_REPO_URL = "repo_url"
DYN_ROOT_PROMPT = "root_prompt"
DYN_SKILL_INSTRUCTION = "skill_instruction"
⋮----
# User-Provided Context Keys (session-scoped)
USER_PROVIDED_CTX = "user_provided_ctx"
USER_PROVIDED_CTX_EXCEEDED = "user_provided_ctx_exceeded"
USR_PROVIDED_FILES_SERIALIZED = "usr_provided_files_serialized"
USR_PROVIDED_FILES_UNSERIALIZED = "usr_provided_files_unserialized"
⋮----
# Dynamic Instruction State Key (for {user_ctx_manifest?} template injection)
DYN_USER_CTX_MANIFEST = "user_ctx_manifest"
⋮----
# Caching Keys (session-scoped despite : separator)
CACHE_STORE = "cache:store"
CACHE_HIT_COUNT = "cache:hit_count"
CACHE_MISS_COUNT = "cache:miss_count"
CACHE_LAST_HIT_KEY = "cache:last_hit_key"
⋮----
# Invocation Timing (session-scoped, control-plane)
INVOCATION_START_TIME = "invocation_start_time"
⋮----
# Observability Keys (session-scoped)
# Post-thread-bridge: ObservabilityPlugin uses instance-local counters only.
# Only keys still written to session state are listed here.
⋮----
# Reasoning Retry Observability (written by orchestrator)
OBS_REASONING_RETRY_COUNT = "obs:reasoning_retry_count"
OBS_REASONING_RETRY_DELAY_MS = "obs:reasoning_retry_delay_ms"
⋮----
# REPL Submitted-Code Observability Keys
REPL_SUBMITTED_CODE = "repl_submitted_code"
REPL_SUBMITTED_CODE_PREVIEW = "repl_submitted_code_preview"
REPL_SUBMITTED_CODE_HASH = "repl_submitted_code_hash"
REPL_SUBMITTED_CODE_CHARS = "repl_submitted_code_chars"
⋮----
# Skill Loading Keys
REPL_SKILL_GLOBALS_INJECTED = "repl_skill_globals_injected"
⋮----
# API/Messaging Keys
REQUEST_ID = "request_id"
IDEMPOTENCY_KEY = "idempotency_key"
USER_LAST_SUCCESSFUL_CALL_ID = "user:last_successful_call_id"
⋮----
# Test Hook State Keys (session-scoped, written by test-only callbacks)
CB_REASONING_CONTEXT = "cb_reasoning_context"
CB_ORCHESTRATOR_CONTEXT = "cb_orchestrator_context"
CB_TOOL_CONTEXT = "cb_tool_context"
⋮----
# Artifact Tracking Keys (session-scoped)
ARTIFACT_SAVE_COUNT = "artifact_save_count"
ARTIFACT_LOAD_COUNT = "artifact_load_count"
ARTIFACT_TOTAL_BYTES_SAVED = "artifact_total_bytes_saved"
ARTIFACT_LAST_SAVED_FILENAME = "artifact_last_saved_filename"
ARTIFACT_LAST_SAVED_VERSION = "artifact_last_saved_version"
⋮----
# LiteLLM Cost Tracking (session-scoped aggregate)
OBS_LITELLM_TOTAL_COST = "obs:litellm_total_cost"
⋮----
# Artifact Configuration Keys (app-scoped)
APP_ARTIFACT_OFFLOAD_THRESHOLD = "app:artifact_offload_threshold"
⋮----
# Migration Status Keys (session-scoped, naming convention only)
MIGRATION_STATUS = "migration:status"
MIGRATION_TIMESTAMP = "migration:timestamp"
MIGRATION_ERROR = "migration:error"
⋮----
# Step-Mode Keys (session-scoped)
STEP_MODE_ENABLED = "step:mode_enabled"  # bool — is step mode active?
STEP_MODE_PAUSED_AGENT = "step:paused_agent"  # str — name of agent currently paused
STEP_MODE_PAUSED_DEPTH = "step:paused_depth"  # int — depth of paused agent
STEP_MODE_ADVANCE_COUNT = "step:advance_count"  # int — number of advances taken
⋮----
# REPL State Introspection
REPL_STATE_SNAPSHOT = "_rlm_state"
⋮----
EXPOSED_STATE_KEYS: frozenset[str] = frozenset(
⋮----
# Extensions for dynamic instruction verification
⋮----
DEPTH_SCOPED_KEYS: set[str] = {
# NOTE: Only iteration-local keys that need independent state per depth
# level are included. CURRENT_DEPTH is included because child
# orchestrators write depth_key(CURRENT_DEPTH, depth) and REPLTool
# must read the depth-scoped value. Global observability keys are excluded.
⋮----
def depth_key(key: str, depth: int = 0, fanout_idx: int = 0) -> str
⋮----
"""Return a depth-and-fanout-scoped state key.

    At depth 0 the original key is returned unchanged (fanout_idx ignored).
    At depth N > 0 the key is suffixed with ``@dNfM`` so nested
    reasoning agents operate on independent state.  The fanout index
    ``M`` distinguishes sibling children dispatched via
    ``llm_query_batched()`` at the same depth.

    Examples::

        depth_key("iteration_count", 0)     -> "iteration_count"
        depth_key("iteration_count", 1)     -> "iteration_count@d1f0"
        depth_key("iteration_count", 2, 3)  -> "iteration_count@d2f3"
    """
⋮----
# ---- Depth/fanout key parser (shared with sqlite_tracing.py) ----
⋮----
_DEPTH_FANOUT_RE = re.compile(r"^(.+)@d(\d+)(?:f(\d+))?$")
⋮----
def parse_depth_key(raw_key: str) -> tuple[str, int, int]
⋮----
"""Parse depth/fanout suffix from a state key.  Inverse of depth_key().

    Returns ``(base_key, depth, fanout_idx)``.  Unscoped keys return
    ``(raw_key, 0, 0)``; legacy ``@dN`` keys (without ``fM``) return
    fanout ``0`` for backward compatibility with existing trace data.
    """
m = _DEPTH_FANOUT_RE.match(raw_key)
⋮----
# ---- Curated state key capture set (shared with dispatch.py, sqlite_tracing.py) ----
⋮----
CURATED_STATE_KEYS: frozenset[str] = frozenset(
⋮----
CURATED_STATE_PREFIXES: tuple[str, ...] = (
⋮----
def should_capture_state_key(base_key: str) -> bool
⋮----
"""Return True if this state key should be captured for observability."""
````

## File: rlm_adk/dispatch.py
````python
"""Child orchestrator dispatch mechanism for sub-LM calls.

Replaces the leaf LlmAgent worker pool with recursive child
RLMOrchestratorAgent instances.  Each sub-query spawns a child
orchestrator (with its own REPL + SetModelResponseTool) at depth+1.

Architecture:
- DispatchConfig: Holds model configuration (replaces WorkerPool)
- llm_query_async: Spawn 1 child orchestrator, return LLMResult
- llm_query_batched_async: Spawn K children concurrently (semaphore-limited)
- Depth limit: max_depth prevents infinite recursion

State mutation discipline (AR-CRIT-001):
- Local accumulators in the closure replace ctx.session.state reads.
- post_dispatch_state_patch_fn() returns minimal working-state patch
  (DYN_SKILL_INSTRUCTION restoration only).
- Child completion is read from _rlm_terminal_completion attrs, not state.
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
def _classify_error(error: Exception) -> str
⋮----
"""Classify an exception into an error category for observability."""
⋮----
code = getattr(error, "code", None)
# LiteLLM exceptions use status_code (int) instead of code (str).
# Fall back to status_code when code is missing or non-integer.
status_code = getattr(error, "status_code", None)
⋮----
code = status_code
⋮----
# Also detect litellm.Timeout which is not an asyncio.TimeoutError
⋮----
# Detect JSON parse / malformed response errors
⋮----
err_msg = str(error).lower()
⋮----
# Check error message for JSON-related patterns (e.g., wrapped exceptions)
err_str = str(error).lower()
⋮----
class DispatchConfig
⋮----
"""Holds model configuration for child dispatch (replaces WorkerPool)."""
⋮----
def ensure_initialized(self)
⋮----
"""No-op for backward compatibility."""
⋮----
# Backward-compatible alias so existing imports continue to work.
WorkerPool = DispatchConfig
⋮----
"""Create dispatch closures for child orchestrator sub-LM calls.

    These closures capture the dispatch config and invocation context,
    and are injected into the REPL namespace so that LM-generated code
    can call sub-LM queries via child orchestrators.

    Args:
        dispatch_config: Model configuration (DispatchConfig / WorkerPool alias)
        ctx: Current invocation context
        call_log_sink: Optional list to accumulate RLMChatCompletion records.
        trace_sink: Optional mutable list[REPLTrace | None] holder.
        depth: Current nesting depth (0 = root orchestrator).
        max_depth: Maximum allowed depth.  Overridden by RLM_MAX_DEPTH env var.

    Returns:
        (llm_query_async, llm_query_batched_async,
         post_dispatch_state_patch_fn) 3-tuple.
        post_dispatch_state_patch_fn() returns a minimal working-state
        patch dict (DYN_SKILL_INSTRUCTION restoration only).
    """
max_depth = int(os.getenv("RLM_MAX_DEPTH", str(max_depth)))
max_concurrent = int(os.getenv("RLM_MAX_CONCURRENT_CHILDREN", "3"))
_child_semaphore = asyncio.Semaphore(max_concurrent)
⋮----
_parent_fanout_idx = fanout_idx
⋮----
# Pre-compute parent's skill instruction for state patch restoration
_parent_skill_instruction: str | None = None
⋮----
_parent_skill_instruction = instruction_router(depth, _parent_fanout_idx)
⋮----
"""Append a structured child-call record for REPL observability."""
⋮----
model_name = str(result.model or dispatch_config.other_model)
⋮----
"""Collect the child's normalized completion payload.

        Priority order:
        1. child._rlm_terminal_completion (on orchestrator)
        2. child.reasoning_agent._rlm_terminal_completion
        3. fallback to _structured_result (any type)
        4. fallback to output_key
        5. error

        Does NOT mine child_state for OBS_REASONING_RETRY_*,
        OBS_CHILD_*, or other nested observability keys.
        """
agent = getattr(child, "reasoning_agent", None)
⋮----
# Priority 1 & 2: CompletionEnvelope
envelope = getattr(child, "_rlm_terminal_completion", None)
⋮----
envelope = getattr(agent, "_rlm_terminal_completion", None)
⋮----
# Priority 3: _structured_result (any validated type)
structured = getattr(agent, "_structured_result", None)
⋮----
text = render_completion_text(structured)
⋮----
# Priority 4: output_key fallback
output_key = getattr(agent, "output_key", None) or f"reasoning_output@d{child_depth}f{fanout_idx}"
raw = child_state.get(output_key)
⋮----
text = render_completion_text(raw)
parsed_payload = None
⋮----
parsed_payload = dict(raw)
⋮----
decoded = json.loads(raw)
⋮----
decoded = None
⋮----
parsed_payload = decoded
⋮----
# Priority 5: error
⋮----
"""Spawn a child orchestrator for a single sub-query."""
# Preserve the raw model object for create_child_orchestrator
# so _resolve_model()'s CRIT-1 check can pass LiteLlm objects
# through unchanged.  str() only for logging / LLMResult.model.
raw_model = model if model is not None else dispatch_config.other_model
target_model = str(raw_model)
⋮----
result = LLMResult(
⋮----
child_start = time.perf_counter()
elapsed_ms = 0.0
_child_result: LLMResult | None = None
_call_logged = False
_child_state: dict[str, Any] = {}
⋮----
child = create_child_orchestrator(
⋮----
# Branch isolation: give the child its own event-history
# branch so it doesn't see (or pollute) the parent's
# conversation history.  Same pattern as ParallelAgent.
child_ctx = ctx.model_copy()
branch_suffix = f"{ctx.agent.name}.{child.name}"
⋮----
actions = getattr(_event, "actions", None)
state_delta = getattr(actions, "state_delta", None) if actions else None
⋮----
# Push curated state-delta events onto queue for parent re-emission
⋮----
curated = {
⋮----
child_depth = depth + 1
completion = _read_child_completion(
answer = completion["text"]
⋮----
elapsed_ms = (time.perf_counter() - child_start) * 1000
⋮----
parsed_payload = completion.get("parsed_output")
raw_payload = completion.get("raw_output")
is_error = bool(completion.get("error"))
error_category = completion.get("error_category")
finish_reason = completion.get("finish_reason")
_child_result = LLMResult(
⋮----
error_text = (
⋮----
cat = (
⋮----
_call_logged = True
# Clean up child's REPL
⋮----
"""Dispatch a single sub-LM query via child orchestrator.

        Delegates to llm_query_batched_async for consistency.
        """
current_trace = trace_sink[0] if trace_sink else None
call_index = -1
call_start = 0.0
⋮----
call_index = current_trace._call_counter
⋮----
call_start = time.perf_counter()
⋮----
results = await llm_query_batched_async(
⋮----
elapsed_ms = (time.perf_counter() - call_start) * 1000
⋮----
"""Dispatch K sub-LM queries via child orchestrators, concurrently.

        Concurrency is limited by _child_semaphore (max_concurrent).
        """
⋮----
k = len(prompts)
dispatch_start = time.perf_counter()
⋮----
# Trace support
⋮----
_data_flow = DataFlowTracker() if current_trace is not None else None
⋮----
batch_start_index = current_trace._call_counter
⋮----
batch_start_index = 0
⋮----
# Run all children concurrently (semaphore limits actual concurrency)
tasks = [_run_child(p, model, output_schema, idx) for idx, p in enumerate(prompts)]
results = await asyncio.gather(*tasks)
all_results = list(results)
⋮----
dispatch_elapsed_ms = (time.perf_counter() - dispatch_start) * 1000
⋮----
# Record trace entries
⋮----
batch_elapsed = dispatch_elapsed_ms
⋮----
ci = batch_start_index + idx
⋮----
def post_dispatch_state_patch_fn() -> dict[str, Any]
⋮----
"""Return minimal working-state patch after dispatch.

        Only restores DYN_SKILL_INSTRUCTION if an instruction
        router was configured.  No lineage or observability keys.
        """
delta: dict[str, Any] = {}
````

## File: rlm_adk/orchestrator.py
````python
"""RLM Orchestrator Agent - Custom BaseAgent delegating to reasoning_agent with REPLTool.

Phase 5B: The orchestrator no longer manually iterates, parses code blocks,
or executes them.  Instead it:
1. Creates a REPLTool wrapping LocalREPL
2. Wires the reasoning_agent with tools=[REPLTool] (output_key="reasoning_output")
3. Yields an initial user Content event with the root_prompt
4. Delegates to self.reasoning_agent.run_async(ctx) -- ADK's native tool-calling
   loop handles all iteration, code execution, and structured output
5. Extracts the final_answer from the output_key ("reasoning_output")

CRIT-1: All state writes inside _run_async_impl use yield Event(actions=EventActions(state_delta={})).
"""
⋮----
logger = logging.getLogger(__name__)
⋮----
# Transient HTTP status codes that warrant a retry.
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_COMPLIANCE_FINISH_REASONS = frozenset({"SAFETY", "RECITATION"})
⋮----
def is_transient_error(exc: Exception) -> bool
⋮----
"""Classify an exception as transient (retryable) using type-based checks.

    Recognizes google.genai errors, asyncio timeouts, and network-level
    exceptions as transient.  Generic exceptions are never retried.
    """
⋮----
"""Classify a missing/errored reasoning completion."""
⋮----
schema_name = getattr(output_schema, "__name__", "structured output schema")
⋮----
"""Build a CompletionEnvelope from reasoning agent results.

    Priority order:
    1. ``_rlm_terminal_completion`` (set by worker_retry after_tool_cb)
    2. ``output_key`` fallback — derive finish_reason from
       ``_rlm_last_response_meta``, NOT from session state
    3. Plain-text response candidate from visible output text
    4. Synthesize terminal error envelope
    """
# Priority 1: already-built envelope from after_tool_cb
existing = getattr(reasoning_agent, "_rlm_terminal_completion", None)
⋮----
# Read agent-local metadata (never fall back to session state)
response_meta = getattr(reasoning_agent, "_rlm_last_response_meta", None) or {}
finish_reason = response_meta.get("finish_reason")
visible_text = response_meta.get("visible_text") or ""
⋮----
# Priority 2: output_key
output_key = reasoning_agent.output_key or "reasoning_output"
raw = session_state.get(output_key)
structured = getattr(reasoning_agent, "_structured_result", None)
⋮----
payload = parse_reasoning_output(raw)
mode: str = "text"
⋮----
payload = parse_reasoning_output(structured)
mode = "structured"
⋮----
# Priority 3: plain-text from visible output
payload = parse_reasoning_output(visible_text)
⋮----
# Accept any non-None validated output (dict, list, BaseModel,
# str, primitive) -- not just dicts.
validated = payload.parsed_output
⋮----
validated = structured
⋮----
display = render_completion_text(
⋮----
display = payload.final_answer
⋮----
display = visible_text
⋮----
schema_name = getattr(output_schema, "__name__", None) if output_schema else None
⋮----
# Check for error conditions
error = False
error_category = None
⋮----
error = True
⋮----
mode = "error"
⋮----
class RLMOrchestratorAgent(BaseAgent)
⋮----
"""Custom BaseAgent that delegates to reasoning_agent with REPLTool.

    The orchestrator wires a REPLTool and ReasoningOutput schema onto the
    reasoning_agent at runtime, then delegates via run_async.  ADK's native
    tool-calling loop handles iteration, code execution, and structured output.

    Configuration (set via session state at invocation start):
    - app:max_iterations: Maximum tool calls (default 30)

    Sub-agents:
    - reasoning_agent: LlmAgent for main reasoning (depth=0)
    """
⋮----
model_config = {"arbitrary_types_allowed": True}
⋮----
# Sub-agents declared as Pydantic fields so ADK recognizes them
reasoning_agent: LlmAgent
⋮----
# Configuration fields
root_prompt: str | None = None
repo_url: str | None = None
persistent: bool = False
worker_pool: Any = None
repl: Any = None
depth: int = 0
fanout_idx: int = 0
output_schema: Any = None  # type[BaseModel] | None — caller's schema for children
instruction_router: Any = None  # Callable[[int, int], str] | None
enabled_skills: tuple[str, ...] = ()
parent_depth: int | None = None
parent_fanout_idx: int | None = None
⋮----
async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]
⋮----
"""Collapsed orchestrator -- delegates to reasoning_agent with REPLTool.

        CRIT-1: All state writes MUST yield Event with EventActions(state_delta).
        """
_default_max_iter = int(os.getenv("RLM_MAX_ITERATIONS", "30"))
max_iterations = ctx.session.state.get(APP_MAX_ITERATIONS, _default_max_iter)
trace_level = int(os.getenv("RLM_REPL_TRACE", "0"))
⋮----
# Initialize REPL environment (reuse persistent REPL if provided)
⋮----
repl = self.repl
⋮----
repl = LocalREPL(depth=1)
⋮----
# Inject LLMResult and depth_key into REPL namespace
⋮----
# Inject skill globals into REPL namespace unconditionally.
# All orchestrators (root and children) get skill functions in REPL
# so child code can call them via the thread bridge.  Only the root
# orchestrator (with enabled_skills) gets the SkillToolset discovery
# tools — see the tools wiring below.
_skill_globals = collect_skill_repl_globals(
⋮----
# Mutable trace holder: trace_holder[0] is the current REPLTrace per code block.
# Dispatch closures read this to record per-call timing.
trace_holder: list[REPLTrace | None] = [None]
⋮----
# Wire up WorkerPool dispatch closures -- collapsed mode omits
# the queue parameter.  post_dispatch_state_patch_fn is passed
# to REPLTool which applies minimal working-state patches after
# each code execution.
post_dispatch_state_patch_fn = None
_child_event_queue: asyncio.Queue[Event] | None = None
⋮----
_child_event_queue = asyncio.Queue()
⋮----
# Wire sync bridge: create sync callables that dispatch to the
# event loop from the REPL worker thread via run_coroutine_threadsafe.
# Pass the REPL's cancellation token so that orphaned worker
# threads abort at the llm_query() boundary after a timeout
# (GAP-EL-004).
_loop = asyncio.get_running_loop()
⋮----
# Create telemetry finalizer from SqliteTracingPlugin (GAP-06 fix).
# The finalizer ensures tool telemetry rows are completed even when
# ADK's after_tool_callback doesn't fire for deeply nested async tools.
telemetry_finalizer = None
plugin_manager = getattr(ctx, "plugin_manager", None)
⋮----
sqlite_plugin = plugin_manager.get_plugin("sqlite_tracing")
⋮----
telemetry_finalizer = sqlite_plugin.make_telemetry_finalizer()
⋮----
# Create REPLTool with post_dispatch_state_patch_fn
repl_tool = REPLTool(
⋮----
# Wire reasoning_agent at runtime with tools.
# Uses object.__setattr__ because LlmAgent is a Pydantic model.
# Note: output_schema=ReasoningOutput is NOT set on LlmAgent because
# ADK's __maybe_save_output_to_state validates raw text responses
# against the schema (fails for plain text).  Instead we add
# SetModelResponseTool as a tool so the model can choose either
# execute_code or set_model_response.  BUG-13 patch (process-global
# in worker_retry.py) handles retry suppression.
schema = self.output_schema or ReasoningOutput
set_model_response_tool = SetModelResponseTool(schema)
⋮----
tools = [repl_tool, set_model_response_tool]
# Add SkillToolset when skills are enabled
⋮----
_adk_skills = load_adk_skills(self.enabled_skills)
⋮----
# Tag lineage attrs for telemetry (read by reasoning callbacks)
_ra = self.reasoning_agent
⋮----
_schema_name = getattr(schema, "__name__", None)
⋮----
# Ensure ADK manages tool call/response history at depth 0.
# Children (depth > 0) keep include_contents='none' set by
# create_child_orchestrator so they don't inherit parent session
# history through the shared InvocationContext.
⋮----
# Wire structured output retry callbacks for set_model_response
⋮----
# Build initial state delta.
initial_state: dict[str, Any] = {
⋮----
# Only root (depth=0) sets the global REQUEST_ID.
# Children must not overwrite the root correlation ID.
⋮----
# repo_url is propagated to children; user_ctx_manifest is intentionally
# NOT propagated (children scope their own context via their prompt).
⋮----
_skill_text = self.instruction_router(self.depth, self.fanout_idx)
⋮----
# Seed skill instruction via before_agent_callback so it's
# visible to before_model_callback on the first model call.
# callback_context.state writes are tracked by ADK and applied
# to session state immediately (unlike EventActions state_delta
# which requires Runner processing to apply).
⋮----
# --- User-provided context directory (Path A: env var) ---
_ctx_dir = os.getenv("RLM_USER_CTX_DIR")
⋮----
_max_chars = int(os.getenv("RLM_USER_CTX_MAX_CHARS", "500000"))
uctx = load_user_context(_ctx_dir, _max_chars)
⋮----
# Pre-load context dict into REPL globals
⋮----
# --- Path B: pre-seeded user_provided_ctx in session state ---
⋮----
_pre_seeded = ctx.session.state[USER_PROVIDED_CTX]
⋮----
# Build manifest from the pre-seeded dict
_filenames = sorted(k for k in _pre_seeded if not k.startswith("_"))
_manifest_lines = [
⋮----
_content = _pre_seeded[_fn]
⋮----
_chars = len(_content)
⋮----
_chars = len(_json.dumps(_content, default=str))
⋮----
_manifest_str = "\n".join(_manifest_lines)
⋮----
# Yield initial state
⋮----
# Yield initial prompt as a user Content event so the reasoning agent
# receives the user's query in its conversation history.
initial_prompt = self.root_prompt or "Analyze and answer the query."
⋮----
# --- Delegate to reasoning_agent (with retry for transient errors) ---
max_retries = int(os.getenv("RLM_LLM_MAX_RETRIES", "3"))
base_delay = float(os.getenv("RLM_LLM_RETRY_DELAY", "5.0"))
total_retry_delay_ms = 0
⋮----
# Drain child events accumulated during tool execution
⋮----
transient = is_transient_error(exc)
⋮----
# Yield a structured error event before propagating.
http_code = getattr(exc, "code", None)
⋮----
err_detail = (
⋮----
err_detail = f"non-retryable error (code={http_code})"
error_msg = f"[RLM ERROR] {type(exc).__name__}: {err_detail}"
⋮----
delay = base_delay * (2**attempt)
⋮----
# Persist reasoning retry count if any retries occurred
⋮----
retry_state_delta: dict[str, Any] = {
⋮----
# Final drain of any remaining child events after reasoning loop
⋮----
# --- Finalize from CompletionEnvelope ---
completion = _collect_completion(
⋮----
final_text = completion.display_text
⋮----
# Auto-save final answer as artifact
⋮----
# Yield final content event
⋮----
exhausted_msg = final_text or (
⋮----
# Clean up reasoning_agent wiring
````
