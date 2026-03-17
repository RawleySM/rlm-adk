"""User-provided context directory serialization.

Walks a user-supplied directory, reads textual files, and packs as many as
possible into a ``ctx`` dict (smallest-first) until a character budget is
exhausted.  Files that don't fit are recorded in ``unserialized`` so the
agent can load them on demand via ``open()``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_TEXTUAL_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".py", ".json", ".yaml", ".yml", ".csv", ".xml", ".toml",
    ".cfg", ".log", ".html", ".css", ".js", ".ts", ".sql", ".sh", ".env",
    ".ini", ".rst", ".r", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".rb",
    ".pl", ".swift", ".kt",
})


@dataclass
class UserContextResult:
    """Result of loading a user-provided context directory."""

    ctx: dict[str, str] = field(default_factory=dict)
    serialized: list[str] = field(default_factory=list)
    unserialized: list[str] = field(default_factory=list)
    exceeded: bool = False
    total_chars: int = 0
    dir_path: str = ""

    def build_manifest(self) -> str:
        """Build a manifest string for dynamic instruction injection."""
        lines: list[str] = []
        lines.append("Pre-loaded context variable: user_ctx (dict)")

        if self.serialized:
            lines.append('Pre-loaded files (access via user_ctx["<filename>"]):')
            for name in self.serialized:
                chars = len(self.ctx[name])
                lines.append(f"  - {name} ({chars:,} chars)")

        if self.unserialized:
            lines.append("Files exceeding pre-load threshold (load via open()):")
            for name in self.unserialized:
                full_path = os.path.join(self.dir_path, name)
                # We need the size; read the file to get it
                try:
                    size = len(open(full_path, encoding="utf-8").read())  # noqa: SIM115
                except Exception:
                    size = 0
                lines.append(
                    f"  - {name} ({size:,} chars)"
                    f' \u2192 open("{full_path}")'
                )

        total_files = len(self.serialized) + len(self.unserialized)
        pre = len(self.serialized)
        req_open = len(self.unserialized)
        if req_open:
            lines.append(
                f"Total: {total_files} files, {pre} pre-loaded,"
                f" {req_open} requires open()"
            )
        else:
            lines.append(f"Total: {total_files} files, {pre} pre-loaded")

        return "\n".join(lines)


def load_user_context(
    dir_path: str, max_chars: int = 500_000
) -> UserContextResult:
    """Load textual files from *dir_path* into a context dict.

    Files are sorted smallest-first so the budget accommodates the maximum
    number of files.  Files that don't fit are recorded in ``unserialized``.
    """
    collected: list[tuple[str, str, int]] = []  # (rel_path, content, size)

    for root, _dirs, files in os.walk(dir_path):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _TEXTUAL_EXTENSIONS:
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, dir_path)
            try:
                content = open(full, encoding="utf-8").read()  # noqa: SIM115
            except (UnicodeDecodeError, OSError):
                continue
            collected.append((rel, content, len(content)))

    # Sort smallest first
    collected.sort(key=lambda t: t[2])

    ctx: dict[str, str] = {}
    serialized: list[str] = []
    unserialized: list[str] = []
    running = 0

    for rel, content, size in collected:
        if running + size <= max_chars:
            ctx[rel] = content
            serialized.append(rel)
            running += size
        else:
            unserialized.append(rel)

    return UserContextResult(
        ctx=ctx,
        serialized=serialized,
        unserialized=unserialized,
        exceeded=len(unserialized) > 0,
        total_chars=running,
        dir_path=dir_path,
    )
