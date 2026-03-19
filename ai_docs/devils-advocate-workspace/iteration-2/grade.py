#!/usr/bin/env python3
"""Grade iteration-2 reports — adds referencing scheme assertions."""
import json
import re
from pathlib import Path

WORKSPACE = Path("/home/rawley-stanhope/dev/rlm-adk/.claude/skills/devils-advocate-workspace/iteration-2")

ASSERTIONS = [
    "Report has a dedicated ADK Callback Opportunities section",
    "Report has Vision Alignment Assessment with 2+ vision areas",
    "Report has Prior Art Findings with URLs or search queries",
    "Report has Cross-Cutting Themes section",
    "Report has Prioritized Recommendations (numbered)",
    "ADK section names specific callback types",
    "Vision section references actual vision concepts",
    "Report uses A-prefixed IDs for callback findings (A1, A2, etc.)",
    "Report uses V-prefixed IDs for vision recommendations (V1, V2, etc.)",
    "Report uses P-prefixed IDs for prior art capabilities (P1, P2, etc.)",
    "Report uses X-prefixed IDs for cross-cutting themes (X1, X2, etc.)",
    "Report uses R-prefixed IDs for recommendations with Traces-to lines (R1, R2, etc.)",
    "Report includes Reference Key table at top",
]

CALLBACK_KEYWORDS = ["before_model", "after_model", "before_tool", "after_tool",
                     "before_agent", "after_agent", "on_event", "BasePlugin",
                     "before_run", "after_run"]

VISION_KEYWORDS = ["polya", "topology", "dynamic skill", "skill loading",
                   "continuous runtime", "self-improvement", "autonomous",
                   "interactive dashboard", "inventing on principle"]


def grade_report(text: str) -> list[dict]:
    results = []
    low = text.lower()

    # 1-7: same structural assertions as iteration-1
    results.append({"text": ASSERTIONS[0], "passed": bool(re.search(r"##\s*ADK\s+Callback", text, re.I)),
                    "evidence": "Found ADK Callback heading" if re.search(r"##\s*ADK\s+Callback", text, re.I) else "Missing"})

    has_vh = bool(re.search(r"##\s*Vision\s+Alignment", text, re.I))
    va = sum(1 for k in ["polya", "dynamic skill", "continuous runtime", "interactive dashboard"] if k in low)
    results.append({"text": ASSERTIONS[1], "passed": has_vh and va >= 2,
                    "evidence": f"Heading: {has_vh}, areas: {va}/4"})

    has_pa = bool(re.search(r"##\s*Prior\s+Art", text, re.I))
    has_urls = bool(re.search(r"https?://", text))
    results.append({"text": ASSERTIONS[2], "passed": has_pa and has_urls,
                    "evidence": f"Heading: {has_pa}, URLs: {has_urls}"})

    results.append({"text": ASSERTIONS[3], "passed": bool(re.search(r"##\s*Cross-Cutting", text, re.I)),
                    "evidence": "Found" if re.search(r"##\s*Cross-Cutting", text, re.I) else "Missing"})

    has_rh = bool(re.search(r"##\s*Prioritized\s+Rec", text, re.I))
    has_num = bool(re.search(r"###\s*R\d+\.", text) or re.search(r"\n\d+\.\s+\*\*", text))
    results.append({"text": ASSERTIONS[4], "passed": has_rh and has_num,
                    "evidence": f"Heading: {has_rh}, numbered: {has_num}"})

    cbs = [k for k in CALLBACK_KEYWORDS if k in low]
    results.append({"text": ASSERTIONS[5], "passed": len(cbs) >= 3,
                    "evidence": f"Found: {cbs}"})

    vs = [k for k in VISION_KEYWORDS if k in low]
    results.append({"text": ASSERTIONS[6], "passed": len(vs) >= 2,
                    "evidence": f"Found: {vs}"})

    # 8-12: NEW referencing scheme assertions
    a_ids = re.findall(r"###\s+A\d+\.", text)
    results.append({"text": ASSERTIONS[7], "passed": len(a_ids) >= 2,
                    "evidence": f"A-prefixed headings: {len(a_ids)}"})

    v_ids = re.findall(r"###\s+V\d+\.", text)
    results.append({"text": ASSERTIONS[8], "passed": len(v_ids) >= 2,
                    "evidence": f"V-prefixed headings: {len(v_ids)}"})

    p_ids = re.findall(r"###\s+P\d+\.", text)
    results.append({"text": ASSERTIONS[9], "passed": len(p_ids) >= 2,
                    "evidence": f"P-prefixed headings: {len(p_ids)}"})

    x_ids = re.findall(r"###\s+X\d+\.", text)
    results.append({"text": ASSERTIONS[10], "passed": len(x_ids) >= 2,
                    "evidence": f"X-prefixed headings: {len(x_ids)}"})

    r_ids = re.findall(r"###\s+R\d+\.", text)
    traces = len(re.findall(r"[Tt]races?\s+to", text))
    results.append({"text": ASSERTIONS[11], "passed": len(r_ids) >= 2 and traces >= 2,
                    "evidence": f"R-prefixed headings: {len(r_ids)}, Traces-to lines: {traces}"})

    # 13: Reference Key table
    has_ref = bool(re.search(r"Reference\s+Key", text, re.I))
    results.append({"text": ASSERTIONS[12], "passed": has_ref,
                    "evidence": "Found Reference Key" if has_ref else "Missing"})

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
        rp = WORKSPACE / eval_name / config / "outputs" / "report.md"
        if not rp.exists():
            print(f"SKIP {eval_name}/{config}")
            continue
        text = rp.read_text()
        grades = grade_report(text)
        passed = sum(1 for g in grades if g["passed"])
        total = len(grades)
        grading = {"eval_name": eval_name, "config": config, "pass_rate": passed/total,
                   "passed": passed, "total": total, "expectations": grades}
        (WORKSPACE / eval_name / config / "grading.json").write_text(json.dumps(grading, indent=2))
        print(f"{eval_name}/{config}: {passed}/{total} ({passed/total:.0%})")


if __name__ == "__main__":
    main()
