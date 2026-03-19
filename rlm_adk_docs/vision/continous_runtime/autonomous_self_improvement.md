<!-- validated: 2026-03-09 -->

# Autonomous Self-Improvement (Cron-Triggered Agents)

**Status:** Conceptual — no implementation yet

**What it does:** Agents are spawned on a schedule (cron or event-driven) to perform maintenance, improvement, and audit tasks without human prompting. Each autonomous agent reads the orientation guide (`UNDERSTAND.md`) to understand the product direction, then executes its assigned task.

---

## Planned Autonomous Task Types

| Task | Trigger | What It Does |
|------|---------|-------------|
| **Gap Audit** | Daily cron | Scan `rlm_adk_docs/gap_registry.json` for open observability/test gaps. Propose fixes or close resolved gaps. |
| **Doc Staleness Check** | Daily cron | Compare `<!-- validated: -->` dates against source file modification times. Flag or update stale docs. |
| **Test Coverage Expansion** | Weekly cron | Identify untested failure modes from FMEA matrix. Generate new fixture JSON files for uncovered scenarios. |
| **REPL Pattern Mining** | After each run | Analyze recent REPL executions for reusable patterns. Extract candidates for new skills. |
| **Dependency Audit** | Weekly cron | Check for outdated dependencies, security advisories, ADK version changes that affect monkey-patches. |
| **Performance Baseline** | Weekly cron | Run provider-fake contract suite, compare timing against historical baselines. Flag regressions. |

## Architecture

```
Cron / Event Trigger
  → Spawn coding agent with task-specific prompt
  → Agent reads UNDERSTAND.md → identifies relevant branches
  → Agent reads branch docs for task context
  → Agent executes task (code changes, doc updates, fixture generation)
  → Agent creates PR or updates tracking artifacts
  → Results logged for self-improvement feedback loop
```

## Constraints for Autonomous Agents

- Must operate within a worktree (isolated from main branch)
- Must create PRs, never push directly to main
- Must run tests before proposing changes
- Must update any docs they find stale during their work
- Must log their actions for auditability

## Open Design Questions

- How does the agent decide task priority when multiple gaps/issues exist?
- What's the feedback signal for "this autonomous improvement was valuable"?
- How do we prevent autonomous agents from creating churn (low-value PRs)?
- Should autonomous agents have a token/cost budget per run?

## Related Docs

- [testing.md](../testing.md) — FMEA patterns, fixture authoring
- [observability.md](../observability.md) — gap registry, tracing

## Research References

- `ai_docs/codebase_documentation_research/lsp_and_staleness_prevention.md`
- `ai_docs/codebase_documentation_research/code_to_doc_tools.md`
