#!/usr/bin/env python3
"""Lightweight LSP query CLI for on-demand type information.

Launches pyright-langserver over stdio, opens a target file, and runs LSP
queries. Auto-detects repo root (.git), .venv, and src/ extra paths.

Positions are 1-indexed on the CLI and converted to 0-indexed internally.

Commands
--------

Position queries (require file + line + char, all 1-indexed):

    hover <file> <line> <char>
        Return the type signature at a position as a markdown string.
        At a class call-site, returns the full MRO-resolved constructor
        with every parameter, type, and default. At an import line,
        returns only the class name and docstring summary.
        Output: {"command":"hover", "file":..., "line":N, "char":N,
                 "success":true, "result":{"markdown":"..."}}

    definition <file> <line> <char>
        Jump to the source location where a symbol is defined.
        Output: {"command":"definition", ..., "result":{"locations":[
                 {"file":"path","line":N,"char":N}]}}

    references <file> <line> <char>
        Find all usage sites of a symbol (your code + library internals).
        Output: {"command":"references", ..., "result":{"locations":[...]}}

    signature <file> <line> <char>
        Return signature help at a position. NOTE: Returns empty
        {"signatures":[]} for Pydantic model constructors (synthesized
        __init__). Use hover instead for ADK/Pydantic classes.
        Output: {"command":"signature", ..., "result":{"signatures":[...]}}

File queries (require file only):

    symbols <file>
        List all top-level symbols (classes, functions, variables) in a file.
        Output: {"command":"symbols", ..., "result":{"symbols":[
                 {"name":"...","kind":"Class","line":N}, ...]}}

    diagnostics <file>
        Return Pyright type errors and warnings for a file.
        Output: {"command":"diagnostics", ..., "result":{"diagnostics":[
                 {"line":N,"char":N,"severity":"error","message":"..."}],
                 "count":N}}

Compound queries:

    callsite-hover <file> [<library> ...]
        Automatically find all call-sites of classes imported from one or
        more libraries and hover each one to extract the full constructor
        signature.

        Libraries can be provided as positional args after the file path,
        or read from the LSP_LIBRARIES environment variable (loaded via
        python-dotenv). CLI args take precedence over the env var.

        Environment variable format (comma-separated):
          LSP_LIBRARIES=google-adk,google-genai

        Uses Python's ast module to:
          1. Parse <file> for `from <library>... import <Class>` statements
          2. Find every `Class(...)` call-site in the file
          3. Run a hover query at each call-site position

        The library names use hyphens, mapped to dots for import matching:
          google-adk   ->  matches `from google.adk.* import ...`
          google-genai  ->  matches `from google.genai.* import ...`

        Writes one JSON file per library to the same directory as <file>:
          <dir>/<stem>_<library>_callsite_hover.json

        Deduplicates by symbol: each unique class appears once with its
        full hover signature. All instances (assignment targets) are listed.

        The output JSON contains:
          {
            "file": "/abs/path/to/file.py",
            "library": "google-adk",
            "import_prefix": "google.adk",
            "imported_classes": ["App", "LlmAgent", "LoopAgent", ...],
            "call_sites": [
              {
                "symbol": "LlmAgent",
                "instances": [
                  {"name": "fetcher", "line": 17},
                  {"name": "thinker", "line": 62}
                ],
                "hover": {"markdown": "class LlmAgent(*, name: str, ...)"}
              },
              ...
            ]
          }

        Instance "name" is the assignment target (e.g., "fetcher" from
        `fetcher = LlmAgent(...)`). It is null when the call is not a
        simple assignment (e.g., inside a list literal).

        Stdout prints a per-library summary:
          {"success":true, "output_file":"...", "unique_symbols":5,
           "total_instances":11, "imported_classes":["App","LlmAgent",...]}

    batch
        Read JSONL queries from stdin (one JSON object per line).
        Each line has the same fields as a single-query command:
          {"command":"hover","file":"agent.py","line":20,"char":4}
        Reuses a single pyright-langserver process for all queries.
        Each result is printed as one JSON line to stdout.

Examples
--------
    # Hover at a call-site to get the full constructor signature
    python lsp_cli.py hover rlm_agent/agent.py 16 11

    # Jump to where LlmAgent is defined in the installed package
    python lsp_cli.py definition rlm_agent/agent.py 3 35

    # Extract all ADK constructor signatures from a file at once
    python lsp_cli.py callsite-hover rlm_agent/agent.py google-adk

    # Multiple libraries at once (CLI args)
    python lsp_cli.py callsite-hover rlm_agent/agent.py google-adk google-genai

    # Multiple libraries from env var (set LSP_LIBRARIES in .env)
    python lsp_cli.py callsite-hover rlm_agent/agent.py

    # Batch multiple queries in one server session
    python lsp_cli.py batch < queries.jsonl

Options
-------
    --wait SECONDS   Seconds to wait for Pyright analysis after opening
                     a file (default: 6). Increase for large codebases.
"""

import argparse
import ast
import ctypes
import ctypes.util
import json
import os
import select
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv


def _set_pdeathsig() -> None:
    """Set PR_SET_PDEATHSIG so pyright-langserver dies when lsp_cli.py is killed.

    Runs as preexec_fn in the child process after fork() but before exec().
    Linux-only (including WSL2). No-op if prctl is unavailable.
    """
    PR_SET_PDEATHSIG = 1
    try:
        libc_name = ctypes.util.find_library("c")
        if libc_name:
            libc = ctypes.CDLL(libc_name, use_errno=True)
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except (OSError, AttributeError):
        pass  # Non-Linux or libc unavailable — skip silently


# ---------------------------------------------------------------------------
# Config - auto-detect repo root, venv, langserver
# ---------------------------------------------------------------------------

@dataclass
class Config:
    repo_root: Path
    venv_path: Path
    python_path: Path
    langserver: str
    extra_paths: list[str] = field(default_factory=list)

    @classmethod
    def auto_detect(cls) -> "Config":
        """Walk up from cwd to find .git, then locate .venv and langserver."""
        cwd = Path.cwd().resolve()
        repo_root = _find_repo_root(cwd)
        if repo_root is None:
            repo_root = cwd

        venv_path = repo_root / ".venv"
        venv_bin = venv_path / "bin"
        python_path = venv_bin / "python"

        langserver = "pyright-langserver"

        extra_paths = []
        src_dir = repo_root / "src"
        if src_dir.is_dir():
            extra_paths.append(str(src_dir))

        return cls(
            repo_root=repo_root,
            venv_path=venv_path,
            python_path=python_path,
            langserver=langserver,
            extra_paths=extra_paths,
        )


def _find_repo_root(start: Path) -> Optional[Path]:
    current = start
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


# ---------------------------------------------------------------------------
# LSP Client - JSON-RPC over stdio
# ---------------------------------------------------------------------------

class LSPClient:
    """Minimal LSP JSON-RPC client over stdio."""

    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self.buffer = b""
        self._next_id = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown()

    def _make_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    def send(self, msg: dict) -> None:
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        self.proc.stdin.write(header + body)
        self.proc.stdin.flush()

    def request(self, method: str, params: Any) -> int:
        rid = self._make_id()
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        return rid

    def notify(self, method: str, params: Any) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def read_message(self, timeout: float = 5) -> Optional[dict]:
        start = time.time()
        while time.time() - start < timeout:
            msg = self._try_parse()
            if msg is not None:
                return msg
            ready, _, _ = select.select([self.proc.stdout], [], [], 0.5)
            if ready:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    return None
                self.buffer += chunk
        return None

    def _try_parse(self) -> Optional[dict]:
        header_end = self.buffer.find(b"\r\n\r\n")
        if header_end == -1:
            return None
        header_block = self.buffer[:header_end].decode("utf-8")
        content_length = 0
        for line in header_block.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break
        msg_end = header_end + 4 + content_length
        if len(self.buffer) < msg_end:
            return None
        content = self.buffer[header_end + 4 : msg_end]
        self.buffer = self.buffer[msg_end:]
        return json.loads(content.decode("utf-8"))

    def wait_for_response(self, target_id: int, timeout: float = 30) -> Optional[dict]:
        start = time.time()
        while time.time() - start < timeout:
            msg = self.read_message(timeout=2)
            if msg is None:
                continue
            if msg.get("id") == target_id:
                return msg
        return None

    def drain(self, timeout: float = 2) -> list[dict]:
        msgs = []
        while True:
            msg = self.read_message(timeout=timeout)
            if msg is None:
                break
            msgs.append(msg)
        return msgs

    def shutdown(self) -> None:
        try:
            rid = self.request("shutdown", None)
            self.wait_for_response(rid, timeout=5)
            self.notify("exit", None)
            time.sleep(0.3)
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# LSP Session - handles lifecycle and queries
# ---------------------------------------------------------------------------

class LSPSession:
    """Manages the LSP server lifecycle and provides query methods."""

    def __init__(self, config: Config, wait_seconds: float = 6):
        self.config = config
        self.wait_seconds = wait_seconds
        self.client: Optional[LSPClient] = None
        self._opened_files: set[str] = set()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def start(self) -> None:
        proc = subprocess.Popen(
            [self.config.langserver, "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            preexec_fn=_set_pdeathsig,
        )
        self.client = LSPClient(proc)
        self._initialize()

    def stop(self) -> None:
        if self.client:
            self.client.shutdown()
            self.client = None

    def _initialize(self) -> None:
        rid = self.client.request("initialize", {
            "processId": os.getpid(),
            "rootUri": _file_uri(self.config.repo_root),
            "capabilities": {
                "textDocument": {
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "definition": {"linkSupport": True},
                    "references": {},
                    "documentSymbol": {
                        "hierarchicalDocumentSymbolSupport": True,
                    },
                    "signatureHelp": {
                        "signatureInformation": {
                            "parameterInformation": {"labelOffsetSupport": True},
                        },
                    },
                },
                "workspace": {
                    "symbol": {"symbolKind": {"valueSet": list(range(1, 27))}},
                },
            },
        })
        resp = self.client.wait_for_response(rid, timeout=30)
        if not resp or "result" not in resp:
            raise RuntimeError("LSP server failed to initialize")

        self.client.notify("initialized", {})

        python_path = str(self.config.python_path)
        self.client.notify("workspace/didChangeConfiguration", {
            "settings": {
                "python": {
                    "pythonPath": python_path,
                    "venvPath": str(self.config.venv_path),
                },
                "basedpyright": {
                    "analysis": {
                        "pythonPath": python_path,
                        "extraPaths": self.config.extra_paths,
                        "typeCheckingMode": "standard",
                    },
                },
                "pyright": {
                    "pythonPath": python_path,
                },
            },
        })
        time.sleep(1)
        self.client.drain(timeout=1)

    def _ensure_file_open(self, file_path: Path) -> str:
        """Open the file in the LSP server if not already open. Returns the URI."""
        uri = _file_uri(file_path)
        if uri not in self._opened_files:
            text = file_path.read_text()
            self.client.notify("textDocument/didOpen", {
                "textDocument": {
                    "uri": uri,
                    "languageId": "python",
                    "version": 1,
                    "text": text,
                },
            })
            self._opened_files.add(uri)
            # Wait for analysis on first file open
            time.sleep(self.wait_seconds)
            self.client.drain(timeout=2)
        return uri

    def resolve_path(self, file_arg: str) -> Path:
        """Resolve a file argument to an absolute path."""
        p = Path(file_arg)
        if p.is_absolute():
            return p.resolve()
        # Try relative to cwd first
        candidate = (Path.cwd() / p).resolve()
        if candidate.exists():
            return candidate
        # Try relative to repo root
        candidate = (self.config.repo_root / p).resolve()
        if candidate.exists():
            return candidate
        # Fall back to cwd-relative (will error later if missing)
        return (Path.cwd() / p).resolve()

    # -- Query methods -----------------------------------------------------

    def query_hover(self, file_path: Path, line: int, char: int) -> dict:
        uri = self._ensure_file_open(file_path)
        rid = self.client.request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
        })
        resp = self.client.wait_for_response(rid, timeout=15)
        return _extract_hover(resp)

    def query_signature(self, file_path: Path, line: int, char: int) -> dict:
        uri = self._ensure_file_open(file_path)
        rid = self.client.request("textDocument/signatureHelp", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
        })
        resp = self.client.wait_for_response(rid, timeout=15)
        return _extract_signature(resp)

    def query_definition(self, file_path: Path, line: int, char: int) -> dict:
        uri = self._ensure_file_open(file_path)
        rid = self.client.request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
        })
        resp = self.client.wait_for_response(rid, timeout=15)
        return _extract_locations(resp, self.config.repo_root)

    def query_references(self, file_path: Path, line: int, char: int) -> dict:
        uri = self._ensure_file_open(file_path)
        rid = self.client.request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": char},
            "context": {"includeDeclaration": True},
        })
        resp = self.client.wait_for_response(rid, timeout=15)
        return _extract_locations(resp, self.config.repo_root)

    def query_symbols(self, file_path: Path) -> dict:
        uri = self._ensure_file_open(file_path)
        rid = self.client.request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        resp = self.client.wait_for_response(rid, timeout=15)
        return _extract_symbols(resp)

    def query_diagnostics(self, file_path: Path) -> dict:
        """Return diagnostics collected during file open."""
        uri = self._ensure_file_open(file_path)
        # Diagnostics are pushed as notifications; drain and filter
        msgs = self.client.drain(timeout=3)
        diags = []
        for m in msgs:
            if (m.get("method") == "textDocument/publishDiagnostics"
                    and m.get("params", {}).get("uri") == uri):
                for d in m["params"].get("diagnostics", []):
                    start = d.get("range", {}).get("start", {})
                    diags.append({
                        "line": start.get("line", 0) + 1,
                        "char": start.get("character", 0) + 1,
                        "severity": _severity_str(d.get("severity", 1)),
                        "message": d.get("message", ""),
                        "source": d.get("source", ""),
                    })
        return {"diagnostics": diags, "count": len(diags)}


# ---------------------------------------------------------------------------
# Result extractors
# ---------------------------------------------------------------------------

SYMBOL_KINDS = {
    1: "File", 2: "Module", 3: "Namespace", 4: "Package",
    5: "Class", 6: "Method", 7: "Property", 8: "Field",
    9: "Constructor", 10: "Enum", 11: "Interface", 12: "Function",
    13: "Variable", 14: "Constant", 15: "String", 16: "Number",
    17: "Boolean", 18: "Array", 19: "Object", 20: "Key",
    21: "Null", 22: "EnumMember", 23: "Struct", 24: "Event",
    25: "Operator", 26: "TypeParameter",
}

SEVERITY_MAP = {1: "error", 2: "warning", 3: "information", 4: "hint"}


def _severity_str(sev: int) -> str:
    return SEVERITY_MAP.get(sev, f"unknown({sev})")


def _file_uri(path: Path) -> str:
    return f"file://{path}"


def _extract_hover(resp: Optional[dict]) -> dict:
    if not resp or not resp.get("result"):
        return {"markdown": None}
    contents = resp["result"].get("contents", {})
    if isinstance(contents, dict):
        return {"markdown": contents.get("value", str(contents))}
    if isinstance(contents, str):
        return {"markdown": contents}
    if isinstance(contents, list):
        parts = []
        for c in contents:
            if isinstance(c, dict):
                parts.append(c.get("value", str(c)))
            else:
                parts.append(str(c))
        return {"markdown": "\n".join(parts)}
    return {"markdown": str(contents)}


def _extract_signature(resp: Optional[dict]) -> dict:
    if not resp or not resp.get("result"):
        return {"signatures": []}
    result = resp["result"]
    sigs = []
    for sig in result.get("signatures", []):
        params = []
        for p in sig.get("parameters", []):
            params.append({
                "label": p.get("label", "?"),
                "documentation": _extract_doc(p.get("documentation")),
            })
        sigs.append({
            "label": sig.get("label", ""),
            "documentation": _extract_doc(sig.get("documentation")),
            "parameters": params,
        })
    return {
        "signatures": sigs,
        "activeSignature": result.get("activeSignature", 0),
        "activeParameter": result.get("activeParameter", 0),
    }


def _extract_doc(doc: Any) -> Optional[str]:
    if doc is None:
        return None
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        return doc.get("value", str(doc))
    return str(doc)


def _extract_locations(resp: Optional[dict], repo_root: Path) -> dict:
    if not resp or not resp.get("result"):
        return {"locations": []}
    result = resp["result"]
    if isinstance(result, dict):
        result = [result]
    locs = []
    for loc in result:
        uri = loc.get("uri", loc.get("targetUri", ""))
        rng = loc.get("range", loc.get("targetRange", {}))
        start = rng.get("start", {})
        path = uri.replace("file://", "")
        try:
            path = str(Path(path).relative_to(repo_root))
        except ValueError:
            pass
        locs.append({
            "file": path,
            "line": start.get("line", 0) + 1,
            "char": start.get("character", 0) + 1,
        })
    return {"locations": locs}


def _extract_symbols(resp: Optional[dict]) -> dict:
    if not resp or not resp.get("result"):
        return {"symbols": []}
    symbols = []
    for sym in resp["result"]:
        entry = _format_symbol(sym)
        children = []
        for child in sym.get("children", []):
            children.append(_format_symbol(child))
        if children:
            entry["children"] = children
        symbols.append(entry)
    return {"symbols": symbols}


def _format_symbol(sym: dict) -> dict:
    kind = SYMBOL_KINDS.get(sym.get("kind", 0), "Unknown")
    start = sym.get("range", sym.get("location", {}).get("range", {})).get("start", {})
    return {
        "name": sym.get("name", "?"),
        "kind": kind,
        "line": start.get("line", 0) + 1,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lightweight LSP query CLI for basedpyright.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--wait", type=float, default=6,
                        help="Seconds to wait for analysis after opening a file (default: 6)")

    sub = parser.add_subparsers(dest="command", required=True)

    # Position-based commands
    for cmd in ("hover", "signature", "definition", "references"):
        p = sub.add_parser(cmd, help=f"Run {cmd} query at a position")
        p.add_argument("file", help="Path to the Python file")
        p.add_argument("line", type=int, help="Line number (1-indexed)")
        p.add_argument("char", type=int, help="Character position (1-indexed)")

    # File-only commands
    for cmd in ("symbols", "diagnostics"):
        p = sub.add_parser(cmd, help=f"Run {cmd} query on a file")
        p.add_argument("file", help="Path to the Python file")

    # Callsite hover
    p = sub.add_parser("callsite-hover",
                       help="Find call-sites of library classes and hover each")
    p.add_argument("file", help="Path to the Python file")
    p.add_argument("libraries", nargs="*", default=None,
                   help="Library names (e.g., google-adk google-genai). "
                        "Defaults to LSP_LIBRARIES env var (comma-separated).")
    p.add_argument("--out-dir", help="Directory to write output JSON files to")

    # Batch mode
    sub.add_parser("batch", help="Read JSONL queries from stdin")

    return parser


def _run_single(session: LSPSession, command: str, file_arg: str,
                line: int = 0, char: int = 0) -> dict:
    """Execute a single query and return the result dict."""
    file_path = session.resolve_path(file_arg)
    if not file_path.exists():
        return {"error": f"File not found: {file_arg}"}

    # Convert 1-indexed CLI positions to 0-indexed LSP positions
    lsp_line = line - 1
    lsp_char = char - 1

    try:
        if command == "hover":
            result = session.query_hover(file_path, lsp_line, lsp_char)
        elif command == "signature":
            result = session.query_signature(file_path, lsp_line, lsp_char)
        elif command == "definition":
            result = session.query_definition(file_path, lsp_line, lsp_char)
        elif command == "references":
            result = session.query_references(file_path, lsp_line, lsp_char)
        elif command == "symbols":
            result = session.query_symbols(file_path)
        elif command == "diagnostics":
            result = session.query_diagnostics(file_path)
        else:
            return {"error": f"Unknown command: {command}"}
    except Exception as e:
        return {"error": str(e)}

    return result


def _format_output(command: str, file_arg: str, line: int, char: int,
                   result: dict) -> dict:
    """Wrap a result in the standard output envelope."""
    success = "error" not in result
    out = {
        "command": command,
        "file": file_arg,
        "success": success,
    }
    if command not in ("symbols", "diagnostics"):
        out["line"] = line
        out["char"] = char
    if success:
        out["result"] = result
    else:
        out["error"] = result["error"]
    return out


def _get_libraries_from_env() -> list[str]:
    """Read comma-separated library names from LSP_LIBRARIES env var."""
    raw = os.environ.get("LSP_LIBRARIES", "")
    return [lib.strip() for lib in raw.split(",") if lib.strip()]


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    load_dotenv()

    config = Config.auto_detect()

    with LSPSession(config, wait_seconds=args.wait) as session:
        if args.command == "batch":
            _run_batch(session)
        elif args.command == "callsite-hover":
            libraries = args.libraries or _get_libraries_from_env()
            if not libraries:
                print(json.dumps({
                    "error": "No libraries specified. Pass as args or set "
                             "LSP_LIBRARIES env var (comma-separated).",
                }))
                sys.exit(1)
            for lib in libraries:
                _run_callsite_hover(session, lib, args.file, out_dir=args.out_dir)
        else:
            file_arg = args.file
            line = getattr(args, "line", 0)
            char = getattr(args, "char", 0)

            result = _run_single(session, args.command, file_arg, line, char)
            output = _format_output(args.command, file_arg, line, char, result)
            print(json.dumps(output))


def _find_library_callsites(file_path: Path, import_prefix: str) -> dict:
    """Use ast to find classes imported from `import_prefix`, their call-sites, and type annotations.

    Returns {
        "imported_classes": [...],
        "call_sites": [{"symbol", "line", "char", "instance"}, ...],
        "type_annotations": [{"symbol", "line", "char", "context"}, ...],
    }.
    The "instance" field is the variable name the call is assigned to (or None).
    The "context" field describes where the annotation appears (e.g., "param", "return", "variable").
    """
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    # Step 1: Collect class names imported from the library
    imported_classes: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith(import_prefix)):
            for alias in node.names:
                imported_classes.add(alias.asname or alias.name)

    if not imported_classes:
        return {"imported_classes": [], "call_sites": [], "type_annotations": []}

    # Build parent map for assignment target extraction
    parent_map: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node

    # Step 2: Find call-sites where those classes are instantiated
    call_sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name) and node.func.id in imported_classes:
                name = node.func.id
                line = node.func.lineno
                col = node.func.col_offset
            elif isinstance(node.func, ast.Attribute) and node.func.attr in imported_classes:
                name = node.func.attr
                line = node.func.lineno
                col = node.func.col_offset
            if name is not None:
                # Extract assignment target name (e.g., "fetcher" from "fetcher = LlmAgent(...)")
                instance = None
                parent = parent_map.get(id(node))
                if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
                    target = parent.targets[0]
                    if isinstance(target, ast.Name):
                        instance = target.id
                elif isinstance(parent, ast.AnnAssign) and isinstance(parent.target, ast.Name):
                    instance = parent.target.id
                call_sites.append({
                    "symbol": name,
                    "line": line,          # ast is 1-indexed for lineno
                    "char": col + 1,       # ast col_offset is 0-indexed → 1-indexed
                    "instance": instance,
                })

    # Step 3: Find type annotations referencing imported classes
    type_annotations = _find_type_annotations(tree, imported_classes, parent_map)

    return {
        "imported_classes": sorted(imported_classes),
        "call_sites": call_sites,
        "type_annotations": type_annotations,
    }


def _extract_annotation_names(node: ast.AST, imported_classes: set[str]) -> list[ast.Name]:
    """Recursively extract ast.Name nodes matching imported_classes from an annotation.

    Handles plain names (ToolContext), subscripts (Optional[ToolContext],
    list[ToolContext]), and unions (ToolContext | None).
    """
    matches = []
    if isinstance(node, ast.Name) and node.id in imported_classes:
        matches.append(node)
    elif isinstance(node, ast.Subscript):
        # e.g., Optional[ToolContext], list[ToolContext]
        matches.extend(_extract_annotation_names(node.slice, imported_classes))
    elif isinstance(node, ast.Tuple):
        # e.g., dict[str, ToolContext] — the slice is a Tuple
        for elt in node.elts:
            matches.extend(_extract_annotation_names(elt, imported_classes))
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # e.g., ToolContext | None (PEP 604 union)
        matches.extend(_extract_annotation_names(node.left, imported_classes))
        matches.extend(_extract_annotation_names(node.right, imported_classes))
    return matches


def _find_type_annotations(
    tree: ast.AST,
    imported_classes: set[str],
    parent_map: dict[int, ast.AST],
) -> list[dict]:
    """Walk the AST to find type annotations referencing imported_classes.

    Returns list of {"symbol", "line", "char", "context"} dicts.
    """
    annotations: list[dict] = []
    # Track symbols already found at call-sites — we still report annotations
    # for them but the caller can decide whether to skip the hover.
    seen: set[tuple[str, int]] = set()  # (symbol, line) dedup

    for node in ast.walk(tree):
        targets: list[tuple[ast.AST, str]] = []

        # Function/method parameter annotations and return type
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                if arg.annotation:
                    targets.append((arg.annotation, f"param:{arg.arg}"))
            if node.args.vararg and node.args.vararg.annotation:
                targets.append((node.args.vararg.annotation, f"param:*{node.args.vararg.arg}"))
            if node.args.kwarg and node.args.kwarg.annotation:
                targets.append((node.args.kwarg.annotation, f"param:**{node.args.kwarg.arg}"))
            if node.returns:
                targets.append((node.returns, "return"))

        # Variable annotations: x: ToolContext = ...
        elif isinstance(node, ast.AnnAssign) and node.annotation:
            var_name = None
            if isinstance(node.target, ast.Name):
                var_name = node.target.id
            targets.append((node.annotation, f"variable:{var_name or '?'}"))

        # Class base classes: class Foo(ToolContext)
        elif isinstance(node, ast.ClassDef):
            for base in node.bases:
                targets.append((base, f"base:{node.name}"))

        # Extract matching names from each annotation target
        for ann_node, context in targets:
            for name_node in _extract_annotation_names(ann_node, imported_classes):
                key = (name_node.id, name_node.lineno)
                if key not in seen:
                    seen.add(key)
                    annotations.append({
                        "symbol": name_node.id,
                        "line": name_node.lineno,
                        "char": name_node.col_offset + 1,
                        "context": context,
                    })

    return annotations


def _run_callsite_hover(session: LSPSession, library: str, file_arg: str, out_dir: Optional[str] = None) -> None:
    """Find call-sites and type annotations of classes from `library` in `file_arg`, hover each, write JSON.

    Deduplicates by symbol: only one hover per unique class, with all instance
    names (assignment targets) listed under "instances".

    Type annotations that don't appear at any call-site get their own hover
    in the "type_annotations" section of the output.
    """
    # Map library arg to import prefix: "google-adk" -> "google.adk"
    import_prefix = library.replace("-", ".")

    file_path = session.resolve_path(file_arg)
    if not file_path.exists():
        print(json.dumps({"error": f"File not found: {file_arg}"}))
        return

    discovery = _find_library_callsites(file_path, import_prefix)
    has_call_sites = bool(discovery["call_sites"])
    has_annotations = bool(discovery["type_annotations"])

    if not has_call_sites and not has_annotations:
        msg = (f"No call-sites or type annotations for '{import_prefix}' classes found in {file_arg}"
               if discovery["imported_classes"]
               else f"No imports from '{import_prefix}' found in {file_arg}")
        print(json.dumps({"error": msg}))
        return

    # Group call-sites by symbol, hover only the first occurrence of each
    grouped: dict[str, dict] = {}
    for site in discovery["call_sites"]:
        sym = site["symbol"]
        if sym not in grouped:
            hover_result = _run_single(session, "hover", str(file_path),
                                       site["line"], site["char"])
            grouped[sym] = {
                "symbol": sym,
                "instances": [],
                "hover": hover_result,
            }
        grouped[sym]["instances"].append({
            "name": site["instance"],
            "line": site["line"],
        })

    call_site_results = list(grouped.values())
    call_site_symbols = set(grouped.keys())

    # Group type annotations by symbol, hover only symbols not already covered by call-sites
    ann_grouped: dict[str, dict] = {}
    for ann in discovery["type_annotations"]:
        sym = ann["symbol"]
        if sym in call_site_symbols:
            continue  # Already have constructor hover from call-site
        if sym not in ann_grouped:
            hover_result = _run_single(session, "hover", str(file_path),
                                       ann["line"], ann["char"])
            ann_grouped[sym] = {
                "symbol": sym,
                "usages": [],
                "hover": hover_result,
            }
        ann_grouped[sym]["usages"].append({
            "context": ann["context"],
            "line": ann["line"],
        })

    annotation_results = list(ann_grouped.values())

    # Write output
    lib_slug = library  # keep as-is for filename (already hyphenated)
    if out_dir:
        out_path_dir = Path(out_dir)
        out_path_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_path_dir / f"{file_path.stem}_{lib_slug}_callsite_hover.json"
    else:
        output_path = file_path.parent / f"{file_path.stem}_{lib_slug}_callsite_hover.json"

    output_data = {
        "file": str(file_path),
        "library": library,
        "import_prefix": import_prefix,
        "imported_classes": discovery["imported_classes"],
        "call_sites": call_site_results,
        "type_annotations": annotation_results,
    }
    output_path.write_text(json.dumps(output_data, indent=2) + "\n", encoding="utf-8")

    # Print summary to stdout
    total_call_instances = sum(len(r["instances"]) for r in call_site_results)
    total_ann_symbols = len(annotation_results)
    print(json.dumps({
        "success": True,
        "output_file": str(output_path),
        "unique_symbols": len(call_site_results) + total_ann_symbols,
        "total_instances": total_call_instances,
        "type_annotation_symbols": total_ann_symbols,
        "imported_classes": discovery["imported_classes"],
    }))


def _run_batch(session: LSPSession) -> None:
    """Read JSONL from stdin and execute each query."""
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            query = json.loads(raw_line)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}", "input": raw_line}))
            continue

        command = query.get("command", "")
        file_arg = query.get("file", "")
        line = query.get("line", 0)
        char = query.get("char", 0)

        if not command:
            print(json.dumps({"error": "Missing 'command' field", "input": raw_line}))
            continue
        if not file_arg:
            print(json.dumps({"error": "Missing 'file' field", "input": raw_line}))
            continue

        result = _run_single(session, command, file_arg, line, char)
        output = _format_output(command, file_arg, line, char, result)
        print(json.dumps(output))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
