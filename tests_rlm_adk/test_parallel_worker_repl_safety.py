"""Tests for parallel worker REPL chdir safety.

LocalREPL uses os.chdir(self.temp_dir) during code execution, which
creates a race condition when multiple REPLs execute concurrently
(e.g., in a ParallelAgent batch). Each REPL should see its OWN temp dir
as the current working directory, not another REPL's.

This test verifies that concurrent REPL executions do not interfere
with each other's working directory.
"""

import asyncio

import pytest

from rlm_adk.repl.local_repl import LocalREPL


class TestParallelWorkerChdirSafety:
    """Concurrent REPLs must not race on os.getcwd()."""

    @pytest.mark.asyncio
    async def test_concurrent_repls_do_not_race_on_cwd(self):
        """Each REPL should see its OWN temp dir when printing os.getcwd()."""
        repl_a = LocalREPL()
        repl_b = LocalREPL()

        try:
            # Verify each REPL has a distinct temp dir
            assert repl_a.temp_dir != repl_b.temp_dir

            # Execute concurrently using threads (since execute_code is synchronous)
            result_a, result_b = await asyncio.gather(
                asyncio.to_thread(
                    repl_a.execute_code, "import os; print(os.getcwd())"
                ),
                asyncio.to_thread(
                    repl_b.execute_code, "import os; print(os.getcwd())"
                ),
            )

            # Each REPL should see its OWN temp dir
            assert repl_a.temp_dir in result_a.stdout, (
                f"REPL A should see {repl_a.temp_dir} but got: {result_a.stdout.strip()}"
            )
            assert repl_b.temp_dir in result_b.stdout, (
                f"REPL B should see {repl_b.temp_dir} but got: {result_b.stdout.strip()}"
            )
            # The two CWDs should be different
            assert result_a.stdout.strip() != result_b.stdout.strip(), (
                "Two REPLs should see different CWDs but both see the same: "
                f"{result_a.stdout.strip()}"
            )
        finally:
            repl_a.cleanup()
            repl_b.cleanup()

    @pytest.mark.asyncio
    async def test_many_concurrent_repls_cwd_isolation(self):
        """Stress test: 8 concurrent REPLs should each see their own temp dir."""
        repls = [LocalREPL() for _ in range(8)]

        try:
            results = await asyncio.gather(
                *[
                    asyncio.to_thread(r.execute_code, "import os; print(os.getcwd())")
                    for r in repls
                ]
            )

            seen_cwds = set()
            for repl, result in zip(repls, results):
                cwd = result.stdout.strip()
                assert repl.temp_dir in cwd, (
                    f"REPL {repl.temp_dir} should see its own dir but got: {cwd}"
                )
                seen_cwds.add(cwd)

            # All CWDs should be distinct
            assert len(seen_cwds) == len(repls), (
                f"Expected {len(repls)} distinct CWDs but got {len(seen_cwds)}: {seen_cwds}"
            )
        finally:
            for r in repls:
                r.cleanup()
