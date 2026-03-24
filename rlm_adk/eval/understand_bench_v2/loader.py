"""Loader for Understand-phase benchmark v2 case fixtures.

Unlike v1 which embeds content inline, v2 resolves FileRef entries
to actual files on disk in the corpus/ directory. The loader:
  1. Reads the case JSON
  2. Validates against BenchmarkCaseV2
  3. Resolves each FileRef to a real file path
  4. Builds a manifest with format/size/skill metadata
  5. Optionally loads file contents for inline processing
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from rlm_adk.eval.understand_bench_v2.file_type_registry import get_skills_for_file
from rlm_adk.eval.understand_bench_v2.types import BenchmarkCaseV2, FileRef

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent
_CORPUS_DIR = _PACKAGE_DIR / "corpus"


def load_case(case_path: str | Path) -> BenchmarkCaseV2:
    """Load a benchmark case from a JSON fixture file.

    Validates file references exist on disk and enriches
    FileRef entries with size_bytes and skills_required.
    """
    case_path = Path(case_path)
    raw = json.loads(case_path.read_text(encoding="utf-8"))
    case = BenchmarkCaseV2.model_validate(raw)

    # Enrich file references with on-disk metadata
    for fref in case.provided_files:
        _enrich_file_ref(fref)

    # Compute aggregate skills
    all_skills = set()
    for fref in case.provided_files:
        all_skills.update(fref.skills_required)
    case.total_skills_required = sorted(all_skills, key=lambda s: s.value)

    return case


def load_gold(gold_path: str | Path) -> list[str]:
    """Load a gold retrieval order from a JSON file."""
    gold_path = Path(gold_path)
    data = json.loads(gold_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError(
            f"Gold file must contain a JSON array, got {type(data).__name__}: {gold_path}"
        )
    return [str(item) for item in data]


def load_case_with_gold(
    case_path: str | Path,
) -> tuple[BenchmarkCaseV2, list[str]]:
    """Load a case and its corresponding gold retrieval order."""
    case = load_case(case_path)

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
    """Discover all benchmark case fixture files."""
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


def resolve_file_path(file_ref: FileRef, corpus_dir: Path | None = None) -> Path:
    """Resolve a FileRef to an absolute path in the corpus directory."""
    base = corpus_dir or _CORPUS_DIR
    return base / file_ref.filename


def build_manifest(case: BenchmarkCaseV2) -> list[dict[str, Any]]:
    """Build a manifest of all provided files with metadata.

    Returns a list suitable for injecting into the agent's context
    as a document inventory.
    """
    manifest: list[dict[str, Any]] = []
    for fref in case.provided_files:
        file_path = resolve_file_path(fref)
        manifest.append(
            {
                "ref_id": fref.ref_id,
                "filename": fref.filename,
                "display_name": fref.display_name,
                "format": fref.format,
                "doc_type": fref.doc_type,
                "size_bytes": fref.size_bytes,
                "exists_on_disk": file_path.is_file(),
                "skills_required": [s.value for s in fref.skills_required],
                "description": fref.description,
            }
        )
    return manifest


def load_file_content(file_ref: FileRef, corpus_dir: Path | None = None) -> str | bytes:
    """Load the actual content of a file referenced by a FileRef.

    Returns str for text-based formats, bytes for binary formats.
    """
    file_path = resolve_file_path(file_ref, corpus_dir)
    if not file_path.is_file():
        raise FileNotFoundError(f"Corpus file not found: {file_path}")

    binary_formats = {"pdf", "xlsx", "png", "jpg", "jpeg", "heic", "tiff", "gif", "bmp"}
    if file_ref.format.lower() in binary_formats:
        return file_path.read_bytes()
    return file_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _enrich_file_ref(fref: FileRef) -> None:
    """Enrich a FileRef with on-disk metadata and skill requirements."""
    file_path = resolve_file_path(fref)

    # Set size if file exists
    if file_path.is_file():
        fref.size_bytes = file_path.stat().st_size
    else:
        logger.warning("Corpus file not found: %s", file_path)

    # Compute skills if not already set
    if not fref.skills_required:
        fref.skills_required = get_skills_for_file(fref.doc_type, fref.format)
