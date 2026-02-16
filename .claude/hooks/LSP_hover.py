#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = ["python-dotenv"]
# ///
"""
PreToolUse hook for Read: detect imports from libraries listed in LSP_LIBRARIES
and run lsp_cli.py callsite-hover to extract constructor signatures.

Behavior:
  - Non-.py file -> silent exit 0
  - .py file without matching imports -> silent exit 0
  - .py file with matching imports:
      - No .venv in project dir -> stderr + exit 1 (BLOCKS Read)
      - No pyrightconfig.json -> auto-create one
      - Run lsp_cli.py callsite-hover for each matching library -> exit 0

Environment:
  LSP_LIBRARIES  Comma-separated library names (e.g., google-adk,google-genai,databricks-sdk)
                 Library names use hyphens; mapped to dots for import matching:
                   google-adk   -> google.adk
                   google-genai -> google.genai
                   databricks-sdk -> databricks.sdk
"""

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def get_file_path():
    """Get the target file path from env var or stdin JSON."""
    fp = os.environ.get("TOOL_INPUT_FILE_PATH")
    if fp:
        return fp

    try:
        data = json.load(sys.stdin)
        return data.get("tool_input", {}).get("file_path", "")
    except (json.JSONDecodeError, ValueError):
        return ""


def get_library_prefixes():
    """Read LSP_LIBRARIES env var and return list of (library_name, import_prefix) tuples.

    e.g. [("google-adk", "google.adk"), ("databricks-sdk", "databricks.sdk")]
    """
    raw = os.environ.get("LSP_LIBRARIES", "")
    libraries = [lib.strip() for lib in raw.split(",") if lib.strip()]
    return [(lib, lib.replace("-", ".")) for lib in libraries]


def extract_library_imports(file_path, prefixes):
    """Parse the file for imports matching any of the given prefixes.

    Args:
        file_path: Path to the Python file.
        prefixes: List of (library_name, import_prefix) tuples.

    Returns:
        Dict mapping library_name -> list of (module_path, [symbols]) tuples.
        Only libraries with at least one matching import are included.
    """
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    results = {}
    for lib_name, prefix in prefixes:
        escaped = re.escape(prefix)
        pattern = re.compile(
            r"^\s*from\s+(" + escaped + r"\S*)\s+import\s+(.+)$",
            re.MULTILINE,
        )
        matches = []
        for m in pattern.finditer(text):
            module = m.group(1)
            names_str = m.group(2)
            names_str = names_str.strip().rstrip("\\").strip("()")
            symbols = [
                s.strip().split(" as ")[0].strip()
                for s in names_str.split(",")
                if s.strip()
            ]
            if symbols:
                matches.append((module, symbols))
        if matches:
            results[lib_name] = matches

    return results


def ensure_pyrightconfig(project_dir):
    """Create pyrightconfig.json if it doesn't exist."""
    config_path = project_dir / "pyrightconfig.json"
    if config_path.exists():
        return
    config = {
        "venvPath": str(project_dir),
        "venv": ".venv",
        "pythonVersion": "3.13",
        "typeCheckingMode": "basic",
        "reportMissingImports": True,
        "reportMissingTypeStubs": False,
        "include": ["**/*.py"],
        "exclude": ["**/__pycache__", ".venv/**"],
    }
    try:
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def find_lsp_cli(project_dir):
    """Locate lsp_cli.py and the Python interpreter to run it with."""
    venv_python = str(project_dir / ".venv" / "bin" / "python")

    # Check env override first
    lsp_cli_env = os.environ.get("LSP_CLI")
    if lsp_cli_env:
        return lsp_cli_env.split()

    # Default: use the project .venv python + known lsp_cli.py location
    lsp_cli_path = project_dir / ".claude" / "hooks" / "lsp_cli.py"
    if lsp_cli_path.exists():
        return [venv_python, str(lsp_cli_path)]

    # Fallback to adk-python scripts location
    fallback = Path("/home/rawleysm/dev/adk-python/scripts/lsp_cli.py")
    if fallback.exists():
        return [venv_python, str(fallback)]

    return None


def emit_context(lines):
    """Emit collected output as JSON additionalContext for the agent."""
    context = "\n".join(lines)
    if context.strip():
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": context,
            }
        }))


def run_callsite_hover(lsp_cmd, file_path, libraries, project_dir):
    """Run lsp_cli.py callsite-hover as a subprocess, return hover output lines.

    Uses start_new_session=True so the entire process tree (lsp_cli.py +
    pyright-langserver) can be killed via os.killpg on timeout.

    Args:
        lsp_cmd: List of command parts [python, lsp_cli.py].
        file_path: Absolute path to the Python file.
        libraries: List of library names to pass as args.
        project_dir: Path to the project root directory.

    Returns:
        List of output lines describing hover signatures.
    """
    lines = []
    out_dir = project_dir / "callsite_hover"
    cmd = lsp_cmd + ["callsite-hover", file_path] + libraries + ["--out-dir", str(out_dir)]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            # Kill entire process group (lsp_cli.py + pyright-langserver)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except OSError:
                proc.kill()
            proc.wait(timeout=5)
            print(
                "WARNING: lsp_cli.py callsite-hover timed out after 120s",
                file=sys.stderr,
            )
            return lines
        if proc.returncode != 0 and stderr.strip():
            print(stderr.strip(), file=sys.stderr)
    except FileNotFoundError:
        print(
            f"WARNING: Could not run lsp_cli.py: {' '.join(cmd)}",
            file=sys.stderr,
        )
        return lines

    # Read back each generated JSON file and collect hover signatures
    file_stem = Path(file_path).stem
    for lib in libraries:
        output_path = out_dir / f"{file_stem}_{lib}_callsite_hover.json"
        if not output_path.exists():
            continue
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        call_sites = data.get("call_sites", [])
        type_anns = data.get("type_annotations", [])
        total = len(call_sites) + len(type_anns)
        lines.append(f"=== {lib} ({total} classes) ===\n")

        for entry in call_sites:
            symbol = entry.get("symbol", "?")
            instances = entry.get("instances", [])
            hover_md = entry.get("hover", {}).get("markdown")

            instance_names = [
                f"{inst['name']} (line {inst['line']})"
                for inst in instances
                if inst.get("name")
            ]
            if instance_names:
                lines.append(f"  {symbol} — used as: {', '.join(instance_names)}")
            else:
                lines.append(f"  {symbol}")

            if hover_md:
                lines.append(f"\n{hover_md}\n")
            else:
                lines.append("  (no hover data)\n")

        for entry in type_anns:
            symbol = entry.get("symbol", "?")
            usages = entry.get("usages", [])
            hover_md = entry.get("hover", {}).get("markdown")

            usage_descs = [
                f"{u['context']} (line {u['line']})"
                for u in usages
            ]
            lines.append(f"  {symbol} — type annotation: {', '.join(usage_descs)}")

            if hover_md:
                lines.append(f"\n{hover_md}\n")
            else:
                lines.append("  (no hover data)\n")

    return lines


def main():
    file_path = get_file_path()
    if not file_path or not file_path.endswith(".py"):
        sys.exit(0)

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd()))

    # Load .env from project dir or subdirectories
    env_candidates = [project_dir / ".env", project_dir / "rlm_agent" / ".env"]
    for env_file in env_candidates:
        if env_file.exists():
            load_dotenv(env_file)
            break

    prefixes = get_library_prefixes()
    if not prefixes:
        sys.exit(0)

    matched = extract_library_imports(file_path, prefixes)
    if not matched:
        sys.exit(0)

    # --- Library imports detected ---

    # Block if no .venv
    if not (project_dir / ".venv").is_dir():
        print(
            "BLOCKED: No .venv found in project directory.\n"
            "Run the following to set up the environment, then restart Claude Code:\n"
            "  uv venv && uv pip install -e .\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Auto-create pyrightconfig.json if missing
    ensure_pyrightconfig(project_dir)

    # Collect all context output into a buffer for JSON emission
    out = []

    # Report detected imports
    matched_libs = list(matched.keys())
    out.append(f"Library imports detected from: {', '.join(matched_libs)}\n")
    for imports in matched.values():
        for module, syms in imports:
            out.append(f"  from {module} import {', '.join(syms)}")
    out.append("")

    # Find and run lsp_cli.py
    lsp_cmd = find_lsp_cli(project_dir)
    if lsp_cmd is None:
        print(
            "WARNING: Could not locate lsp_cli.py. Skipping callsite-hover.\n"
            "Set LSP_CLI env var or place lsp_cli.py in .claude/hooks/.",
            file=sys.stderr,
        )
        out.append(
            "Read ai_docs/adk_api_reference.md for verified signatures.\n"
            "Do NOT rely on training data for library APIs."
        )
        emit_context(out)
        sys.exit(0)

    out.append(f"Running callsite-hover for: {', '.join(matched_libs)}\n")
    hover_lines = run_callsite_hover(lsp_cmd, os.path.abspath(file_path), matched_libs, project_dir)
    out.extend(hover_lines)

    out.append(
        "\nAfter tracing, read ai_docs/adk_api_reference.md for verified signatures.\n"
        "Do NOT rely on training data for library APIs."
    )

    emit_context(out)
    sys.exit(0)


if __name__ == "__main__":
    main()
