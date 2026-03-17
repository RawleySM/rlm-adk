"""E2E tests proving codex exec works headlessly with full-access permissions.

These tests invoke the REAL codex CLI binary -- no mocking.  They verify that
the fire-and-forget subprocess pattern used by the Codex Transfer system
actually works.

Run only these tests:
    .venv/bin/python -m pytest scripts/codex_transfer/tests/e2e/test_codex_headless.py -v -m codex --timeout=120
"""

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_FLAGS = [
    "--dangerously-bypass-approvals-and-sandbox",
    "--ephemeral",
]


def _build_cmd(
    codex_bin: str,
    *,
    prompt: str | None = None,
    model: str = "gpt-5.4",
    cwd: str | Path | None = None,
    output: str | Path | None = None,
    json_mode: bool = False,
    enable_features: list[str] | None = None,
    extra_flags: list[str] | None = None,
    stdin_marker: bool = False,
) -> list[str]:
    """Build a codex exec command list."""
    cmd = [codex_bin, "exec"] + list(_BASE_FLAGS)

    if model:
        cmd += ["-m", model]
    if cwd:
        cmd += ["-C", str(cwd)]
    if output:
        cmd += ["-o", str(output)]
    if json_mode:
        cmd.append("--json")
    for feat in enable_features or []:
        cmd += ["--enable", feat]
    for flag in extra_flags or []:
        cmd.append(flag)

    if stdin_marker:
        cmd.append("-")
    elif prompt:
        cmd.append(prompt)

    return cmd


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.codex
@pytest.mark.slow
class TestCodexExecBasic:
    """Basic codex exec headless tests."""

    def test_codex_exec_full_access_simple_prompt(self, codex_bin, repo_root, output_file):
        """Prove codex exec runs a simple prompt headlessly and exits 0."""
        cmd = _build_cmd(
            codex_bin,
            prompt="What is 2 + 2? Answer with just the number, nothing else.",
            cwd=repo_root,
            output=str(output_file),
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, (
            f"codex exec failed (rc={result.returncode}).\n"
            f"stderr:\n{result.stderr[:2000]}"
        )
        assert output_file.exists(), "Output file was not created"
        content = output_file.read_text().strip()
        assert len(content) > 0, "Output file is empty"
        # The answer should contain "4" somewhere
        assert "4" in content, f"Expected '4' in output, got: {content[:500]}"

    def test_codex_exec_stdin_prompt(self, codex_bin, repo_root, output_file):
        """Prove prompt can be piped via stdin using the '-' marker."""
        prompt = "What is 3 * 7? Answer with just the number, nothing else."
        cmd = _build_cmd(
            codex_bin,
            cwd=repo_root,
            output=str(output_file),
            stdin_marker=True,
        )
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, (
            f"codex exec (stdin) failed (rc={result.returncode}).\n"
            f"stderr:\n{result.stderr[:2000]}"
        )
        assert output_file.exists(), "Output file was not created"
        content = output_file.read_text().strip()
        assert len(content) > 0, "Output file is empty"
        assert "21" in content, f"Expected '21' in output, got: {content[:500]}"

    def test_codex_exec_json_output(self, codex_bin, repo_root):
        """Prove --json flag produces JSONL event stream on stdout."""
        cmd = _build_cmd(
            codex_bin,
            prompt="Say the word 'hello' and nothing else.",
            cwd=repo_root,
            json_mode=True,
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, (
            f"codex exec --json failed (rc={result.returncode}).\n"
            f"stderr:\n{result.stderr[:2000]}"
        )

        # stdout should contain at least one valid JSON line
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        assert len(lines) > 0, "No JSONL lines in stdout"

        parsed_count = 0
        for line in lines:
            try:
                obj = json.loads(line)
                assert isinstance(obj, dict), f"JSONL line is not a dict: {line[:200]}"
                parsed_count += 1
            except json.JSONDecodeError:
                # Some lines may be non-JSON (progress indicators, etc.)
                pass

        assert parsed_count > 0, (
            f"No valid JSON objects found in {len(lines)} stdout lines.\n"
            f"First 3 lines: {lines[:3]}"
        )

    def test_codex_exec_output_file(self, codex_bin, repo_root, output_file):
        """Prove the -o flag writes the final message to the specified file."""
        cmd = _build_cmd(
            codex_bin,
            prompt="List the numbers 1 through 5, one per line.",
            cwd=repo_root,
            output=str(output_file),
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"rc={result.returncode}, stderr={result.stderr[:1000]}"
        assert output_file.exists(), "-o did not create the output file"
        content = output_file.read_text()
        assert len(content) > 0, "Output file is empty"
        # Should contain at least some of the numbers 1-5
        found = sum(1 for n in ["1", "2", "3", "4", "5"] if n in content)
        assert found >= 3, f"Expected at least 3 of [1..5] in output, found {found}: {content[:500]}"

    def test_codex_exec_working_directory(self, codex_bin, repo_root, output_file):
        """Prove the -C flag sets the agent's working directory."""
        cmd = _build_cmd(
            codex_bin,
            prompt=(
                "Run 'pwd' and tell me the current working directory. "
                "Output ONLY the absolute path, nothing else."
            ),
            cwd=repo_root,
            output=str(output_file),
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"rc={result.returncode}, stderr={result.stderr[:1000]}"
        content = output_file.read_text()
        # The output should reference the repo root path
        assert "rlm-adk" in content or str(repo_root) in content, (
            f"Expected repo root in pwd output, got: {content[:500]}"
        )


@pytest.mark.codex
@pytest.mark.slow
class TestCodexExecSubAgents:
    """Tests for multi_agent and child_agents_md features."""

    def test_codex_exec_sub_agents(self, codex_bin, repo_root, output_file):
        """Prove multi_agent feature flag works -- prompt asks codex to use sub-agents."""
        prompt = (
            "Read AGENTS.md in the current directory. "
            "Summarize what this project does in 2 sentences. "
            "Then spawn a sub-agent to list the top-level Python files. "
            "Output your findings."
        )
        cmd = _build_cmd(
            codex_bin,
            prompt=prompt,
            cwd=repo_root,
            output=str(output_file),
            enable_features=["multi_agent", "child_agents_md"],
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,  # sub-agents may take longer
        )

        assert result.returncode == 0, (
            f"codex exec with sub-agents failed (rc={result.returncode}).\n"
            f"stderr:\n{result.stderr[:2000]}"
        )
        assert output_file.exists(), "Output file was not created"
        content = output_file.read_text()
        assert len(content) > 10, f"Output too short ({len(content)} chars)"

        # Should reference the project in some way -- look for key terms
        content_lower = content.lower()
        project_terms = ["rlm", "adk", "agent", "orchestrat", "reasoning", "repl"]
        found_terms = [t for t in project_terms if t in content_lower]
        assert len(found_terms) >= 1, (
            f"Output does not reference project concepts. "
            f"Searched for {project_terms}, found none.\n"
            f"Output: {content[:1000]}"
        )


@pytest.mark.codex
@pytest.mark.slow
class TestCodexExecDetached:
    """Tests for fire-and-forget subprocess pattern (Popen + start_new_session)."""

    def test_codex_exec_detached_launch(self, codex_bin, repo_root, tmp_path):
        """Prove Popen with start_new_session=True launches a detached codex process.

        This is the pattern codex_launcher.py will use.  We verify:
        1. The subprocess starts (PID > 0)
        2. The PID exists shortly after launch
        3. We can kill it cleanly (cleanup)
        """
        output_file = tmp_path / "detached_output.md"
        stderr_file = tmp_path / "detached_stderr.log"

        cmd = _build_cmd(
            codex_bin,
            # Use a prompt that takes a moment so the process is still alive
            # when we check
            prompt=(
                "Read the file AGENTS.md. Then list every directory in the current "
                "working directory. Describe each directory's purpose in one sentence."
            ),
            cwd=repo_root,
            output=str(output_file),
        )

        with open(stderr_file, "w") as stderr_fh:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_fh,
                start_new_session=True,
            )

        pid = proc.pid
        assert pid > 0, "Popen did not return a valid PID"

        # Give the process a moment to actually start
        time.sleep(2)

        # Verify the process is (or was) running by checking if PID exists
        try:
            # os.kill with signal 0 checks existence without killing
            os.kill(pid, 0)
            process_exists = True
        except OSError:
            # Process already exited -- that is also acceptable for a fast prompt
            process_exists = False
            # Verify it exited successfully
            proc.wait(timeout=5)
            assert proc.returncode == 0, (
                f"Detached process exited with rc={proc.returncode}"
            )

        if process_exists:
            # Process is still running -- good, it is detached.
            # Clean up: terminate gracefully, then force-kill if needed.
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                proc.wait(timeout=30)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    proc.wait(timeout=10)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    pass

    def test_codex_exec_detached_completes(self, codex_bin, repo_root, tmp_path):
        """Prove a detached codex process can run to completion and produce output."""
        output_file = tmp_path / "detached_complete_output.md"
        stderr_file = tmp_path / "detached_complete_stderr.log"

        cmd = _build_cmd(
            codex_bin,
            prompt="What is 10 + 10? Answer with just the number.",
            cwd=repo_root,
            output=str(output_file),
        )

        with open(stderr_file, "w") as stderr_fh:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_fh,
                start_new_session=True,
            )

        # Wait for completion with timeout
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            pytest.fail("Detached codex process did not complete within 120s")

        assert proc.returncode == 0, (
            f"Detached process failed (rc={proc.returncode}).\n"
            f"stderr: {stderr_file.read_text()[:1000]}"
        )
        assert output_file.exists(), "Detached process did not create output file"
        content = output_file.read_text().strip()
        assert "20" in content, f"Expected '20' in output, got: {content[:500]}"


@pytest.mark.codex
@pytest.mark.slow
class TestCodexExecEdgeCases:
    """Edge-case and robustness tests for codex exec."""

    def test_codex_exec_empty_prompt_from_stdin(self, codex_bin, repo_root):
        """Verify behavior when an empty string is piped via stdin."""
        cmd = _build_cmd(
            codex_bin,
            cwd=repo_root,
            stdin_marker=True,
        )
        result = subprocess.run(
            cmd,
            input="",
            capture_output=True,
            text=True,
            timeout=30,
        )
        # codex should either exit 0 (no-op) or exit non-zero (error) --
        # the key assertion is that it does NOT hang.
        # We just verify it completed within the timeout.
        assert result.returncode is not None, "codex exec did not terminate"

    def test_codex_exec_json_and_output_combined(self, codex_bin, repo_root, output_file):
        """Prove --json and -o can be used together."""
        cmd = _build_cmd(
            codex_bin,
            prompt="What is 5 + 5? Answer with just the number.",
            cwd=repo_root,
            output=str(output_file),
            json_mode=True,
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"rc={result.returncode}, stderr={result.stderr[:1000]}"

        # Output file should exist with the final message
        assert output_file.exists(), "-o file not created when combined with --json"
        output_content = output_file.read_text().strip()
        assert len(output_content) > 0, "Output file is empty"

        # stdout should have JSONL events
        json_lines = [
            ln for ln in result.stdout.strip().splitlines()
            if ln.strip()
        ]
        parsed = 0
        for line in json_lines:
            try:
                json.loads(line)
                parsed += 1
            except json.JSONDecodeError:
                pass
        assert parsed > 0, "No JSONL events on stdout when combined with -o"

    def test_codex_exec_multiline_stdin_prompt(self, codex_bin, repo_root, output_file):
        """Prove multi-line prompts work via stdin."""
        prompt = (
            "Step 1: Calculate 100 divided by 4.\n"
            "Step 2: Add 5 to the result.\n"
            "Step 3: Output ONLY the final number, nothing else."
        )
        cmd = _build_cmd(
            codex_bin,
            cwd=repo_root,
            output=str(output_file),
            stdin_marker=True,
        )
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"rc={result.returncode}, stderr={result.stderr[:1000]}"
        content = output_file.read_text().strip()
        assert "30" in content, f"Expected '30' in output, got: {content[:500]}"
