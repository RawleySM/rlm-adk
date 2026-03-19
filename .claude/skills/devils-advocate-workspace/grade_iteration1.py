#!/usr/bin/env python3
"""Grade iteration-1 reports against assertions."""
import json
import re
from pathlib import Path

WORKSPACE = Path("/home/rawley-stanhope/dev/rlm-adk/.claude/skills/devils-advocate-workspace/iteration-1")

ASSERTIONS = [
    "Report has a dedicated ADK Callback Opportunities section analyzing callback under-utilization",
    "Report has a Vision Alignment Assessment section referencing at least 2 of the 4 vision areas",
    "Report has a Prior Art Findings section with URLs or search queries",
    "Report has a Cross-Cutting Themes section identifying patterns across multiple critics",
    "Report has a Prioritized Recommendations section with numbered actionable items",
    "ADK section names specific callback types (before_model, after_tool, BasePlugin, etc.) not just generic advice",
    "Vision section references actual vision concepts (Polya topology, dynamic skill loading, continuous runtime, or dashboard)",
]

CALLBACK_KEYWORDS = [
    "before_model", "after_model", "before_tool", "after_tool",
    "before_agent", "after_agent", "on_event", "BasePlugin",
    "before_run", "after_run",
]

VISION_KEYWORDS = [
    "polya", "topology", "dynamic skill", "skill loading",
    "continuous runtime", "self-improvement", "autonomous",
    "interactive dashboard", "inventing on principle",
]


def grade_report(report_text: str) -> list[dict]:
    """Grade a report against all assertions."""
    results = []
    text_lower = report_text.lower()

    # 1. ADK Callback section
    has_adk = bool(re.search(r"##\s*ADK\s+Callback", report_text, re.IGNORECASE))
    results.append({
        "text": ASSERTIONS[0],
        "passed": has_adk,
        "evidence": "Found '## ADK Callback' heading" if has_adk else "No dedicated ADK Callback section heading found",
    })

    # 2. Vision Alignment section with 2+ areas
    has_vision_heading = bool(re.search(r"##\s*Vision\s+Alignment", report_text, re.IGNORECASE))
    vision_areas_found = sum(1 for kw in ["polya", "dynamic skill", "continuous runtime", "interactive dashboard"]
                            if kw in text_lower)
    passed_vision = has_vision_heading and vision_areas_found >= 2
    results.append({
        "text": ASSERTIONS[1],
        "passed": passed_vision,
        "evidence": f"Vision heading: {has_vision_heading}, vision areas mentioned: {vision_areas_found}/4",
    })

    # 3. Prior Art section with URLs
    has_prior_art = bool(re.search(r"##\s*Prior\s+Art", report_text, re.IGNORECASE))
    has_urls = bool(re.search(r"https?://", report_text))
    has_search_queries = "site:" in text_lower or "search quer" in text_lower
    passed_prior = has_prior_art and (has_urls or has_search_queries)
    results.append({
        "text": ASSERTIONS[2],
        "passed": passed_prior,
        "evidence": f"Prior Art heading: {has_prior_art}, URLs found: {has_urls}, search queries: {has_search_queries}",
    })

    # 4. Cross-Cutting Themes
    has_themes = bool(re.search(r"##\s*Cross-Cutting\s+Themes", report_text, re.IGNORECASE))
    results.append({
        "text": ASSERTIONS[3],
        "passed": has_themes,
        "evidence": "Found '## Cross-Cutting Themes' heading" if has_themes else "No Cross-Cutting Themes section found",
    })

    # 5. Prioritized Recommendations
    has_recs = bool(re.search(r"##\s*Prioritized\s+Recommendations", report_text, re.IGNORECASE))
    has_numbered = bool(re.search(r"###\s*\d+\.", report_text) or re.search(r"\n\d+\.\s+\*\*", report_text))
    passed_recs = has_recs and has_numbered
    results.append({
        "text": ASSERTIONS[4],
        "passed": passed_recs,
        "evidence": f"Prioritized Recs heading: {has_recs}, numbered items: {has_numbered}",
    })

    # 6. Specific callback types named
    callbacks_found = [kw for kw in CALLBACK_KEYWORDS if kw in text_lower]
    passed_callbacks = len(callbacks_found) >= 3
    results.append({
        "text": ASSERTIONS[5],
        "passed": passed_callbacks,
        "evidence": f"Callback types found: {callbacks_found}",
    })

    # 7. Vision concepts referenced
    vision_found = [kw for kw in VISION_KEYWORDS if kw in text_lower]
    passed_vconcepts = len(vision_found) >= 2
    results.append({
        "text": ASSERTIONS[6],
        "passed": passed_vconcepts,
        "evidence": f"Vision concepts found: {vision_found}",
    })

    return results


def main():
    evals = [
        ("plan-file-review", "with_skill"),
        ("plan-file-review", "without_skill"),
        ("poke-holes-proposal", "with_skill"),
        ("poke-holes-proposal", "without_skill"),
        ("inline-cron-plan", "with_skill"),
        ("inline-cron-plan", "without_skill"),
    ]

    for eval_name, config in evals:
        report_path = WORKSPACE / eval_name / config / "outputs" / "report.md"
        if not report_path.exists():
            print(f"SKIP {eval_name}/{config}: report not found")
            continue

        report_text = report_path.read_text()
        grades = grade_report(report_text)

        passed = sum(1 for g in grades if g["passed"])
        total = len(grades)

        grading = {
            "eval_name": eval_name,
            "config": config,
            "pass_rate": passed / total,
            "passed": passed,
            "total": total,
            "expectations": grades,
        }

        out_path = WORKSPACE / eval_name / config / "grading.json"
        out_path.write_text(json.dumps(grading, indent=2))
        print(f"{eval_name}/{config}: {passed}/{total} ({passed/total:.0%})")


if __name__ == "__main__":
    main()
