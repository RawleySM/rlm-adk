Benchmark-driven skill improvement loop for understand_bench_v2.

Decides whether to run the benchmark or analyze + improve the skill.

## Decision Logic

1. **Discover the latest skill version**:
   ```bash
   ls -d rlm_adk/skills/understand_v* | sort -V | tail -1
   ```
   The latest directory name determines `SKILL_NAME` (e.g., `understand_v1`).

2. **Check if it has been benchmarked**:
   ```bash
   cat rlm_adk/.adk/bench_manifest.json 2>/dev/null
   ```
   If the manifest exists AND `manifest.skill == SKILL_NAME` AND `manifest.status == "complete"`, this skill has already been benchmarked. Go to step 4 (Analyze + Improve).

   Otherwise, go to step 3 (Run Benchmark).

3. **Run Benchmark** (no existing results for this skill version):
   ```bash
   .venv/bin/python scripts/run_understand_bench.py --skill $SKILL_NAME
   ```
   Monitor the [RLM:*] output lines:
   - `[RLM:PREFLIGHT]` — pre-flight check results
   - `[RLM:CASE]` — case start (n/total, case_id, difficulty)
   - `[RLM:SCORE]` — per-case scores (total, R, P, O, H, S)
   - `[RLM:SUITE]` — final suite summary
   - `[RLM:STUCK]` — agent is looping (may need to abort)
   - `[RLM:ERROR]` — errors to investigate

   After the run completes, the manifest at `rlm_adk/.adk/bench_manifest.json` will have `status: "complete"`. Proceed to step 4.

4. **Analyze + Improve** (benchmark results exist):

   a. Read the manifest:
      ```bash
      cat rlm_adk/.adk/bench_manifest.json
      ```

   b. For each case in `per_case` with `score < 60`:
      - Run the session report to understand what happened:
        ```bash
        .venv/bin/python -m rlm_adk.eval.session_report --trace-id $TRACE_ID
        ```
      - Identify failure patterns:
        - Low recall → skill instructions don't guide gap detection well enough
        - Low precision → agent is hallucinating artifacts not in gold set
        - Low order_score → retrieval ordering instructions are weak
        - Low halt_score → agent isn't halting when it should
        - Low skill_score → format skill identification instructions are incomplete

   c. Create the next skill version:
      - Copy the current skill directory:
        ```bash
        cp -r rlm_adk/skills/$SKILL_NAME rlm_adk/skills/understand_v$((N+1))
        ```
      - Edit `SKILL.md` to address the identified weaknesses
      - Update the frontmatter `name:` field to match the new version

   d. Report what changed and why. The user can then run `/understand-loop` again to benchmark the new version.

## Important Notes

- **Never run the full test suite** (`-m ""`). Only run the benchmark script.
- The benchmark script handles its own pre-flight checks and will abort if another benchmark is already running.
- Each benchmark run creates isolated sessions with `user_id='bench_user'`.
- Trace IDs are stored in the manifest for post-mortem analysis.
- The scoring rubric weights are: Recall 30%, Skill 25%, Precision 15%, Order 15%, Halt 15%.
