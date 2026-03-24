# Workflow: Parse, Resolve, and Update FMEA Gap Ledger

You are an expert software engineer tasked with systematically addressing gaps identified in a Failure Mode and Effects Analysis (FMEA) ledger.

Follow this strict, three-phase workflow to identify, resolve, and document a single FMEA gap:

## Phase 1: Parse & Select
1. Open and parse the JSON gap ledger file (e.g., `@fmea_gaps_compiled_2.json`).
2. Search the `reviews` array for a specific `fixture` entry that has an open recommendation.
3. Select **one** recommendation that meets the following criteria:
   - **Resolution Status:** "open"
   - **Priority:** "medium" or "high"
4. Clearly state which gap you have selected, including the target fixture, the failure mode (e.g., FM-15), the priority, and the specific action required.

## Phase 2: Resolve via Red/Green TDD
1. **Analyze:** Locate the relevant source code and test files mentioned in the recommendation or the FMEA entry.
2. **Red (Fail):** Implement the missing test assertion or the required source code change. If you write the test first, verify that it fails (or would fail) if the underlying feature is missing or broken.
3. **Green (Pass):** Make the necessary adjustments to the application code and/or the test file until the test passes. Run the test suite (e.g., using `uv run pytest`) to empirically prove the gap is resolved.
4. **Demonstrate:** Create a markdown demo file (e.g., using the `showboat` CLI tool via `uv run showboat`) that documents your resolution. The demo should include:
   - A description of the gap being closed.
   - The specific code or test changes made.
   - Captured execution output of the passing test.

## Phase 3: Update the Gap Ledger
1. Modify the JSON gap ledger file to update the specific recommendation you just completed.
2. Change the `resolution` object for the targeted recommendation as follows:
   - **"status"**: Change from `"open"` to `"implemented"`.
   - **"evidence"**: Provide the name of the new test method or the specific source file and line numbers altered (e.g., `"TestEmptyReasoningOutput::test_should_stop_is_true"`).
   - **"notes"**: Provide a concise summary of the fix. You **must** reference the generated markdown demo file in these notes (e.g., `"Added test to verify session termination. Demonstrated in demo_fm15_fix.md."`).

Execute these phases systematically and autonomously. Report back once the ledger has been successfully updated.