"""Codex CLI wrapper for plan review invocations.

Stdlib-only. Runs codex exec in read-only sandbox mode.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result from a Codex review invocation."""

    verdict: str
    review_text: str
    findings: list[dict] = field(default_factory=list)
    raw_output: str = ""


def _build_review_prompt(
    plan_content: str,
    plan_file_path: Path,
    iteration: int,
    review_history: str,
    template_path: Path | None = None,
    repo_dir: Path | None = None,
    max_iterations: int | None = None,
) -> str:
    """Build the review prompt using {{VARIABLE}} template substitution.

    Uses the same convention as scripts/codex_transfer/docs/codex_prompt_template.md.
    """
    if template_path is None:
        template_path = config.TEMPLATE_PATH
    if repo_dir is None:
        repo_dir = config.REPO_DIR
    if max_iterations is None:
        max_iterations = config.MAX_ITERATIONS

    template = template_path.read_text()

    substitutions = {
        "{{PLAN_CONTENT}}": plan_content,
        "{{PLAN_FILE_PATH}}": str(plan_file_path),
        "{{ITERATION}}": str(iteration),
        "{{MAX_ITERATIONS}}": str(max_iterations),
        "{{REVIEW_HISTORY}}": review_history or "(First review — no prior history.)",
        "{{REPO_DIR}}": str(repo_dir),
    }

    result = template
    for var, value in substitutions.items():
        result = result.replace(var, value)

    return result


def _parse_verdict(review_text: str) -> str:
    """Parse the VERDICT line from review text.

    Returns APPROVED or NEEDS_REVISION.
    Defaults to NEEDS_REVISION if no valid verdict found (conservative).
    """
    match = re.search(config.VERDICT_PATTERN, review_text, re.MULTILINE)
    if match:
        return match.group(1)
    logger.warning("No valid VERDICT line found in review output; defaulting to NEEDS_REVISION")
    return config.VERDICT_NEEDS_REVISION


def _parse_findings(review_text: str) -> list[dict]:
    """Parse structured findings from review markdown.

    Extracts blocks matching: **[SEVERITY] Title**
    """
    findings = []
    pattern = re.compile(
        r"\*\*\[(High|Medium|Low)\]\s+(.+?)\*\*",
        re.IGNORECASE,
    )
    for match in pattern.finditer(review_text):
        findings.append(
            {
                "severity": match.group(1).capitalize(),
                "title": match.group(2).strip(),
            }
        )
    return findings


def run_review(
    plan_content: str,
    plan_file_path: Path,
    iteration: int,
    review_history: str,
    output_path: Path,
    template_path: Path | None = None,
    codex_bin: Path | None = None,
    model: str | None = None,
    repo_dir: Path | None = None,
    timeout: int | None = None,
) -> ReviewResult:
    """Run Codex CLI to review a plan.

    Args:
        plan_content: Full text of the plan to review.
        plan_file_path: Path to the plan file on disk.
        iteration: Current review iteration number.
        review_history: Concatenated previous reviews.
        output_path: Where codex writes its final message.
        template_path: Override template path.
        codex_bin: Override codex binary path.
        model: Override model name.
        repo_dir: Override repository root.
        timeout: Override subprocess timeout in seconds.

    Returns:
        ReviewResult with verdict, review text, and parsed findings.
    """
    if codex_bin is None:
        codex_bin = config.CODEX_BIN
    if model is None:
        model = config.CODEX_MODEL
    if repo_dir is None:
        repo_dir = config.REPO_DIR
    if timeout is None:
        timeout = config.CODEX_TIMEOUT

    prompt = _build_review_prompt(
        plan_content=plan_content,
        plan_file_path=plan_file_path,
        iteration=iteration,
        review_history=review_history,
        template_path=template_path,
        repo_dir=repo_dir,
    )

    cmd = [
        str(codex_bin),
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "-m",
        model,
        "-C",
        str(repo_dir),
        "-o",
        str(output_path),
        "-",  # read prompt from stdin
    ]

    logger.debug("Running: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        logger.error("Codex stderr: %s", result.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

    # Read the output file (codex -o writes the final message there)
    review_text = ""
    if output_path.exists():
        review_text = output_path.read_text()
    else:
        # Fallback: use stdout if -o didn't produce a file
        logger.warning("Codex -o did not produce output file; using stdout")
        review_text = result.stdout

    verdict = _parse_verdict(review_text)
    findings = _parse_findings(review_text)

    return ReviewResult(
        verdict=verdict,
        review_text=review_text,
        findings=findings,
        raw_output=result.stdout,
    )
