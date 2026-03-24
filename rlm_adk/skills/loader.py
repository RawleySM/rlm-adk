"""Skill discovery and REPL-globals collection for the thread-bridge architecture."""

from __future__ import annotations

import functools
import importlib
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from google.adk.skills import Frontmatter, Skill

log = logging.getLogger(__name__)

_SKILLS_DIR: Path = Path(__file__).parent

_SKIP_DIRS: set[str] = {"obsolete", "__pycache__", "repl_skills", "research"}


def discover_skill_dirs(
    enabled_skills: set[str] | tuple[str, ...] | None = None,
) -> list[Path]:
    """Scan the skills directory for valid skill packages (those containing SKILL.md).

    Args:
        enabled_skills: If provided, only return dirs whose name is in this set.

    Returns:
        Sorted list of Path objects for discovered skill directories.
    """
    results: list[Path] = []
    if not _SKILLS_DIR.is_dir():
        return results

    for entry in sorted(_SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in _SKIP_DIRS or entry.name.startswith("."):
            continue
        if not (entry / "SKILL.md").exists():
            continue
        if enabled_skills is not None:
            # Support both underscore and kebab-case matching
            normalised = entry.name.replace("-", "_")
            enabled_normalised = {s.replace("-", "_") for s in enabled_skills}
            if normalised not in enabled_normalised:
                continue
        results.append(entry)

    return results


# ---------------------------------------------------------------------------
# llm_query_fn injection helpers
# ---------------------------------------------------------------------------


def _has_llm_query_fn_param(fn: Callable) -> bool:
    """Return True if *fn* has a parameter named ``llm_query_fn``."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return False
    return "llm_query_fn" in sig.parameters


def _wrap_with_llm_query_injection(
    fn: Callable,
    repl_globals: dict[str, Any],
) -> Callable:
    """Return a wrapper that injects ``llm_query_fn`` from *repl_globals* at call time.

    The wrapper reads ``repl_globals["llm_query"]`` lazily so the dict can be
    populated after wrapping (e.g. when the orchestrator wires the REPL).

    If the caller already passes ``llm_query_fn`` explicitly the wrapper does
    not override it.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if "llm_query_fn" not in kwargs:
            llm_query = repl_globals.get("llm_query")
            if llm_query is None:
                raise RuntimeError(
                    "llm_query not available in REPL globals. "
                    "Ensure the orchestrator has wired llm_query before "
                    "calling skill functions, or pass llm_query_fn explicitly."
                )
            kwargs["llm_query_fn"] = llm_query
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Module name resolution
# ---------------------------------------------------------------------------

_CANONICAL_SKILLS_DIR: Path = Path(__file__).parent
"""The real on-disk skills directory (never monkeypatched)."""


def _module_name_for(skill_dir: Path) -> str:
    """Return the importable dotted module name for *skill_dir*.

    If *skill_dir* lives under the canonical ``rlm_adk/skills/`` package the
    fully-qualified name ``rlm_adk.skills.<name>`` is returned.  Otherwise
    (e.g. in tests that monkeypatch ``_SKILLS_DIR`` to a ``tmp_path``) the
    bare directory name is returned so that callers can add the parent to
    ``sys.path`` themselves.
    """
    try:
        skill_dir.relative_to(_CANONICAL_SKILLS_DIR)
        return f"rlm_adk.skills.{skill_dir.name}"
    except ValueError:
        return skill_dir.name


# ---------------------------------------------------------------------------
# REPL globals collection
# ---------------------------------------------------------------------------


def collect_skill_repl_globals(
    enabled_skills: set[str] | tuple[str, ...] | None = None,
    repl_globals: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    if repl_globals is None:
        repl_globals = {}

    collected: dict[str, Any] = {}
    for skill_dir in discover_skill_dirs(enabled_skills):
        module_name = _module_name_for(skill_dir)
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            log.warning("Failed to import skill module %s", module_name, exc_info=True)
            continue

        exports: list[str] | None = getattr(mod, "SKILL_EXPORTS", None)
        if exports is None:
            continue

        for name in exports:
            obj = getattr(mod, name, None)
            if obj is None:
                log.warning("SKILL_EXPORTS references missing name %r in %s", name, module_name)
                continue
            if callable(obj) and _has_llm_query_fn_param(obj):
                obj = _wrap_with_llm_query_injection(obj, repl_globals)
            collected[name] = obj

    return collected


# ---------------------------------------------------------------------------
# ADK Skill loading (for SkillToolset L1/L2 discovery)
# ---------------------------------------------------------------------------


def _load_skill_from_dir(skill_dir: Path) -> Skill:
    """Load a Skill from a directory, tolerating name/dirname mismatch.

    ADK's ``load_skill_from_dir`` enforces ``dir.name == frontmatter.name``
    but our skill directories use Python package names (underscores) while
    frontmatter names use kebab-case.  This function parses SKILL.md manually.
    """
    skill_md = skill_dir / "SKILL.md"
    text = skill_md.read_text()
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid SKILL.md format in {skill_dir}")
    fm_data = yaml.safe_load(parts[1])
    fm = Frontmatter(**fm_data)
    instructions = parts[2].strip()
    return Skill(frontmatter=fm, instructions=instructions)


def load_adk_skills(
    enabled_skills: set[str] | tuple[str, ...] | None = None,
) -> list[Skill]:
    """Load ADK Skill objects from discovered skill directories.

    Returns a list of :class:`Skill` objects suitable for passing to
    :class:`SkillToolset`.
    """
    skills: list[Skill] = []
    for skill_dir in discover_skill_dirs(enabled_skills):
        try:
            skill = _load_skill_from_dir(skill_dir)
            skills.append(skill)
        except Exception:
            log.warning("Failed to load ADK skill from %s", skill_dir, exc_info=True)
    return skills
