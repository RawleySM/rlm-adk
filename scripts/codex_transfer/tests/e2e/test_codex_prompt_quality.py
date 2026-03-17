"""Tests verifying constructed prompts include all required elements.

The Codex Transfer system builds a prompt for the codex exec invocation that
must include specific instructions so the receiving Codex agent can orient
itself.  These tests verify the prompt construction logic.

Run:
    .venv/bin/python -m pytest scripts/codex_transfer/tests/e2e/test_codex_prompt_quality.py -v
"""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Prompt builder (reference implementation for testing)
# ---------------------------------------------------------------------------

# This mirrors the expected prompt construction from codex_launcher.py.
# When the real module is available, these tests should be updated to import
# from it directly.


def build_codex_prompt(
    *,
    handoff_content: str,
    repo_root: str | Path,
    agents_md_path: str | Path | None = None,
    claude_session_summary: str | None = None,
) -> str:
    """Build the full prompt for codex exec.

    Parameters
    ----------
    handoff_content:
        The markdown handoff document content.
    repo_root:
        Path to the repository root.
    agents_md_path:
        Path to AGENTS.md (defaults to repo_root/AGENTS.md).
    claude_session_summary:
        Optional summary of the Claude session being transferred.

    Returns
    -------
    The constructed prompt string.
    """
    if agents_md_path is None:
        agents_md_path = Path(repo_root) / "AGENTS.md"

    sections = []

    # Section 1: AGENTS.md instruction
    sections.append(
        f"Read and follow the instructions in {agents_md_path}. "
        f"This file defines the project structure, conventions, and agent roles."
    )

    # Section 2: Codebase exploration instruction
    sections.append(
        f"Explore the codebase rooted at {repo_root}. "
        f"Understand the directory layout, key modules, and recent changes "
        f"before proceeding with any task."
    )

    # Section 3: Claude session review (if available)
    if claude_session_summary:
        sections.append(
            f"The previous Claude Code session provided this context:\n\n"
            f"{claude_session_summary}"
        )

    # Section 4: Handoff content
    sections.append(
        f"## Handoff Document\n\n"
        f"The following handoff document describes the task to continue:\n\n"
        f"{handoff_content}"
    )

    return "\n\n---\n\n".join(sections)


# ===========================================================================
# Tests
# ===========================================================================


class TestPromptIncludesAgentsMdInstruction:
    """Verify the prompt instructs codex to read AGENTS.md."""

    def test_prompt_references_agents_md(self, sample_handoff_path, repo_root):
        content = sample_handoff_path.read_text()
        prompt = build_codex_prompt(
            handoff_content=content,
            repo_root=repo_root,
        )
        assert "AGENTS.md" in prompt

    def test_prompt_includes_agents_md_path(self, sample_handoff_path, repo_root):
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
        )
        expected_path = str(repo_root / "AGENTS.md")
        assert expected_path in prompt

    def test_prompt_agents_md_comes_first(self, sample_handoff_path, repo_root):
        """AGENTS.md instruction should appear before handoff content."""
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
        )
        agents_pos = prompt.index("AGENTS.md")
        handoff_pos = prompt.index("Handoff Document")
        assert agents_pos < handoff_pos, (
            "AGENTS.md instruction should come before handoff content"
        )

    def test_prompt_custom_agents_md_path(self, sample_handoff_path, repo_root):
        custom_path = repo_root / "docs" / "CUSTOM_AGENTS.md"
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
            agents_md_path=custom_path,
        )
        assert str(custom_path) in prompt


class TestPromptIncludesCodebaseExplorerInstruction:
    """Verify the prompt instructs codex to explore the codebase."""

    def test_prompt_references_repo_root(self, sample_handoff_path, repo_root):
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
        )
        assert str(repo_root) in prompt

    def test_prompt_includes_explore_instruction(self, sample_handoff_path, repo_root):
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
        )
        prompt_lower = prompt.lower()
        assert "explore" in prompt_lower or "understand" in prompt_lower

    def test_prompt_mentions_directory_layout(self, sample_handoff_path, repo_root):
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
        )
        prompt_lower = prompt.lower()
        assert "directory" in prompt_lower or "layout" in prompt_lower or "structure" in prompt_lower


class TestPromptIncludesClaudeSessionReview:
    """Verify the prompt includes Claude session context when provided."""

    def test_prompt_includes_session_summary(self, sample_handoff_path, repo_root):
        summary = "Completed 55 FMEA tests. 1 test failing. BUG-13 coverage pending."
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
            claude_session_summary=summary,
        )
        assert summary in prompt

    def test_prompt_without_session_summary(self, sample_handoff_path, repo_root):
        """When no session summary is provided, prompt should still be valid."""
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
            claude_session_summary=None,
        )
        assert "AGENTS.md" in prompt
        assert "Handoff Document" in prompt
        # Should NOT contain the session review section marker
        assert "previous Claude Code session" not in prompt

    def test_prompt_session_summary_after_agents_md(self, sample_handoff_path, repo_root):
        """Session summary should appear after AGENTS.md instruction."""
        summary = "Session context goes here."
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
            claude_session_summary=summary,
        )
        agents_pos = prompt.index("AGENTS.md")
        summary_pos = prompt.index(summary)
        assert summary_pos > agents_pos

    def test_prompt_session_summary_before_handoff(self, sample_handoff_path, repo_root):
        """Session summary should appear before the handoff document."""
        summary = "Session context goes here."
        prompt = build_codex_prompt(
            handoff_content=sample_handoff_path.read_text(),
            repo_root=repo_root,
            claude_session_summary=summary,
        )
        summary_pos = prompt.index(summary)
        handoff_pos = prompt.index("Handoff Document")
        assert summary_pos < handoff_pos


class TestPromptIncludesHandoffContent:
    """Verify the prompt includes the full handoff document content."""

    def test_prompt_includes_handoff_markdown(self, sample_handoff_path, repo_root):
        content = sample_handoff_path.read_text()
        prompt = build_codex_prompt(
            handoff_content=content,
            repo_root=repo_root,
        )
        # The handoff content should appear verbatim in the prompt
        assert content in prompt

    def test_prompt_includes_handoff_header(self, sample_handoff_path, repo_root):
        content = sample_handoff_path.read_text()
        prompt = build_codex_prompt(
            handoff_content=content,
            repo_root=repo_root,
        )
        assert "Session Handoff Document" in prompt

    def test_prompt_includes_what_remains(self, sample_handoff_path, repo_root):
        content = sample_handoff_path.read_text()
        prompt = build_codex_prompt(
            handoff_content=content,
            repo_root=repo_root,
        )
        assert "What Remains" in prompt

    def test_prompt_includes_key_files(self, sample_handoff_path, repo_root):
        content = sample_handoff_path.read_text()
        prompt = build_codex_prompt(
            handoff_content=content,
            repo_root=repo_root,
        )
        assert "Key Files" in prompt
        assert "test_fmea_e2e.py" in prompt

    def test_prompt_handoff_section_marked(self, sample_handoff_path, repo_root):
        """Handoff content should be under a clear section header."""
        content = sample_handoff_path.read_text()
        prompt = build_codex_prompt(
            handoff_content=content,
            repo_root=repo_root,
        )
        assert "## Handoff Document" in prompt

    def test_prompt_empty_handoff_still_valid(self, repo_root):
        """Prompt should be valid even with empty handoff content."""
        prompt = build_codex_prompt(
            handoff_content="",
            repo_root=repo_root,
        )
        assert "AGENTS.md" in prompt
        assert "Handoff Document" in prompt

    def test_prompt_total_structure(self, sample_handoff_path, repo_root):
        """Verify the overall prompt has the expected section order."""
        summary = "Previous session context."
        content = sample_handoff_path.read_text()
        prompt = build_codex_prompt(
            handoff_content=content,
            repo_root=repo_root,
            claude_session_summary=summary,
        )

        # Verify ordering: AGENTS.md < explore < session < handoff
        agents_pos = prompt.index("AGENTS.md")
        explore_pos = prompt.index("Explore")
        session_pos = prompt.index("previous Claude Code session")
        handoff_pos = prompt.index("Handoff Document")

        assert agents_pos < explore_pos < session_pos < handoff_pos, (
            f"Section order wrong: AGENTS.md@{agents_pos}, "
            f"Explore@{explore_pos}, session@{session_pos}, "
            f"handoff@{handoff_pos}"
        )
