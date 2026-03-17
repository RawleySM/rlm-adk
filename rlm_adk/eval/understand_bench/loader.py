"""Loader for Understand-phase benchmark case fixtures.

Reads benchmark case JSON files, validates them against the
:class:`BenchmarkCase` Pydantic model, resolves gold retrieval orders,
and assembles the ``provided_context_dict`` with an injected ``_manifest``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rlm_adk.eval.understand_bench.types import BenchmarkCase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Package directory — used as the default base for case/gold discovery.
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Extension-to-type mapping for manifest auto-detection.
# ---------------------------------------------------------------------------

_EXT_TYPE_MAP: dict[str, str] = {
    ".json": "structured",
    ".csv": "tabular",
    ".tsv": "tabular",
    ".md": "text",
    ".txt": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".pdf": "document",
    ".xml": "structured",
    ".yaml": "structured",
    ".yml": "structured",
}

# Keys that carry suffixed format metadata (e.g. "receipt.png_format")
# and internal keys that should be excluded from the manifest.
_INTERNAL_KEYS = {"_manifest"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_case(case_path: str | Path) -> BenchmarkCase:
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

    # Inject _manifest if not already present.
    if "_manifest" not in case.provided_context_dict:
        case.provided_context_dict["_manifest"] = build_context_manifest(
            case.provided_context_dict,
        )

    return case


def load_gold(gold_path: str | Path) -> list[str]:
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
    if not isinstance(data, list):
        raise TypeError(
            f"Gold file must contain a JSON array, got {type(data).__name__}: {gold_path}"
        )
    return [str(item) for item in data]


def load_case_with_gold(
    case_path: str | Path,
) -> tuple[BenchmarkCase, list[str]]:
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

    # Attempt to load a separate gold file.
    gold_file = _PACKAGE_DIR / "gold" / f"{case.case_id}.json"
    if gold_file.is_file():
        gold = load_gold(gold_file)
    else:
        logger.debug(
            "No gold file at %s; falling back to case.gold_retrieval_order",
            gold_file,
        )
        gold = list(case.gold_retrieval_order)

    return case, gold


def discover_cases(
    base_dir: str | Path | None = None,
    difficulty: str | None = None,
) -> list[Path]:
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

    if difficulty is not None:
        difficulty = difficulty.lower()
        subdirs = [cases_dir / difficulty]
    else:
        subdirs = [cases_dir / d for d in ("easy", "medium", "hard")]

    paths: list[Path] = []
    for subdir in subdirs:
        if subdir.is_dir():
            paths.extend(sorted(subdir.glob("*.json")))

    return sorted(paths)


def build_context_manifest(
    provided_context_dict: dict[str, Any],
) -> list[dict[str, Any]]:
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

    for filename, content in provided_context_dict.items():
        # Skip internal keys.
        if filename.startswith("_"):
            continue

        # Infer type from extension.
        suffix = _extract_suffix(filename)
        doc_type = _EXT_TYPE_MAP.get(suffix, "unknown")
        fmt = suffix.lstrip(".") if suffix else "unknown"

        # Compute approximate size.
        if isinstance(content, str):
            size_chars = len(content)
        else:
            # Dicts / lists — measure the JSON representation.
            size_chars = len(json.dumps(content, default=str))

        manifest.append(
            {
                "filename": filename,
                "type": doc_type,
                "format": fmt,
                "size_chars": size_chars,
            }
        )

    return manifest


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_suffix(filename: str) -> str:
    """Return the file extension from *filename*.

    Handles compound pseudo-extensions like ``"school_enrollment.pdf_text"``
    by checking for known suffixes first, then falling back to
    :meth:`Path.suffix`.
    """
    lower = filename.lower()
    # Check known compound patterns first (e.g. ".pdf_text" -> treat as ".txt").
    if lower.endswith("_text"):
        return ".txt"
    # Standard extension.
    suffix = Path(filename).suffix.lower()
    return suffix
