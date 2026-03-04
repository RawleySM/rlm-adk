#!/usr/bin/env python3
"""Audit provider-fake extra fixtures against review-team evidence and queue inclusion.

Usage examples:
    python3 scripts/audit_extra_fixtures_review_queue.py
    python3 scripts/audit_extra_fixtures_review_queue.py \
      --out-json /tmp/extra_fixtures_review_queue.json \
      --out-csv /tmp/extra_fixtures_review_queue.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

FM_PATTERN = re.compile(r"\bFM-\d{2}\b")
TEAM_FILE_PATTERN = re.compile(r"review_team_([a-z])\.json$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse review-team JSON files and audit provider-fake extra fixtures for "
            "generation evidence and review-queue inclusion."
        )
    )
    parser.add_argument(
        "--fixtures-dir",
        default="tests_rlm_adk/fixtures/provider_fake",
        help="Directory with provider_fake fixture JSON files.",
    )
    parser.add_argument(
        "--compiled-json",
        default="rlm_adk_docs/FMEA/fmea_gaps_compiled_2.json",
        help="Compiled FMEA gaps JSON file.",
    )
    parser.add_argument(
        "--review-dir",
        default="rlm_adk_docs/FMEA/review",
        help="Directory containing review_team_*.json files.",
    )
    parser.add_argument(
        "--fmea-md",
        default="rlm_adk_docs/FMEA/rlm_adk_FMEA.md",
        help="FMEA markdown file used for failure-mode linkage checks.",
    )
    parser.add_argument(
        "--out-json",
        default=None,
        help="Optional output path for full JSON report.",
    )
    parser.add_argument(
        "--out-csv",
        default=None,
        help="Optional output path for condensed CSV report.",
    )
    return parser.parse_args()


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_fixture_name(name_or_path: str) -> str:
    value = name_or_path.strip()
    return Path(value).name if value else ""


def iter_json_strings(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    """Recursively yield all string leaves in a JSON-like object."""
    if isinstance(value, str):
        yield path, value
        return
    if isinstance(value, Mapping):
        for key in sorted(value.keys(), key=lambda item: str(item)):
            next_path = path + (str(key),)
            yield from iter_json_strings(value[key], next_path)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            next_path = path + (f"[{index}]",)
            yield from iter_json_strings(item, next_path)


def joined_path(parts: tuple[str, ...]) -> str:
    return ".".join(parts) if parts else "$"


def compact_excerpt(text: str, fixture_name: str, fixture_rel_path: str, width: int = 180) -> str:
    needle = fixture_name if fixture_name in text else fixture_rel_path
    idx = text.find(needle)
    if idx < 0:
        return text[:width]
    start = max(0, idx - 40)
    end = min(len(text), idx + len(needle) + 80)
    snippet = text[start:end].strip()
    return snippet if len(snippet) <= width else snippet[: width - 3] + "..."


def collect_review_queue_fixtures(compiled_json: Mapping[str, Any]) -> tuple[set[str], dict[str, list[str]]]:
    reasons: dict[str, set[str]] = defaultdict(set)

    for review in compiled_json.get("reviews", []):
        if not isinstance(review, Mapping):
            continue
        if review.get("review_type") != "fixture":
            continue
        fixture = review.get("fixture")
        if isinstance(fixture, str):
            normalized = normalize_fixture_name(fixture)
            if normalized:
                reasons[normalized].add("compiled.reviews")

    verdicts = compiled_json.get("verdicts")
    if isinstance(verdicts, Mapping):
        for fixture in verdicts.keys():
            if not isinstance(fixture, str):
                continue
            normalized = normalize_fixture_name(fixture)
            if normalized:
                reasons[normalized].add("compiled.verdicts")

    queue = set(reasons.keys())
    reason_map = {fixture: sorted(values) for fixture, values in reasons.items()}
    return queue, reason_map


def list_fixture_json_files(fixtures_dir: Path) -> list[str]:
    names = [
        path.name
        for path in fixtures_dir.glob("*.json")
        if path.is_file() and path.name != "index.json"
    ]
    return sorted(names)


def extract_failure_modes(review_obj: Mapping[str, Any]) -> list[str]:
    modes: set[str] = set()
    failure_modes = review_obj.get("failure_modes")
    if isinstance(failure_modes, str):
        modes.update(FM_PATTERN.findall(failure_modes))
    elif isinstance(failure_modes, Sequence):
        for item in failure_modes:
            if isinstance(item, str):
                modes.update(FM_PATTERN.findall(item))
    return sorted(modes)


def review_team_letter(team_file_name: str) -> str | None:
    match = TEAM_FILE_PATTERN.search(team_file_name)
    if not match:
        return None
    return match.group(1).upper()


def value_mentions_fixture(value: Any, fixture_name: str, fixture_rel_path: str) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for path, text in iter_json_strings(value):
        if fixture_name in text or fixture_rel_path in text:
            matches.append(
                {
                    "matched_field_path": joined_path(path),
                    "matched_text_excerpt": compact_excerpt(text, fixture_name, fixture_rel_path),
                }
            )
    return matches


def collect_structured_new_fixture_hits(
    recommendation: Mapping[str, Any],
    fixture_name: str,
    fixture_rel_path: str,
) -> list[dict[str, str]]:
    """Rule 1: new_fixture recommendation with resolution/action/notes/evidence mentions."""
    if recommendation.get("type") != "new_fixture":
        return []

    candidates: dict[str, Any] = {
        "action": recommendation.get("action"),
        "notes": recommendation.get("notes"),
        "evidence": recommendation.get("evidence"),
    }
    resolution = recommendation.get("resolution")
    if isinstance(resolution, Mapping):
        for key in ("action", "notes", "evidence"):
            candidates[f"resolution.{key}"] = resolution.get(key)

    hits: list[dict[str, str]] = []
    for field_name, field_value in candidates.items():
        if field_value is None:
            continue
        for item in value_mentions_fixture(field_value, fixture_name, fixture_rel_path):
            item["matched_field_path"] = f"{field_name}.{item['matched_field_path']}"
            hits.append(item)
    return hits


def collect_review_team_hits_for_fixture(
    fixture_name: str,
    review_docs: list[tuple[Path, Mapping[str, Any]]],
    fixture_rel_path: str,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []

    for team_file_path, team_doc in review_docs:
        team_file = team_file_path.name
        team_letter = (
            str(team_doc.get("team")).strip().upper()
            if isinstance(team_doc.get("team"), str) and team_doc.get("team")
            else review_team_letter(team_file)
        )
        demo_file = team_doc.get("demo_file") if isinstance(team_doc.get("demo_file"), str) else None
        reviews = team_doc.get("reviews")
        if not isinstance(reviews, Sequence):
            continue

        for review_index, review in enumerate(reviews):
            if not isinstance(review, Mapping):
                continue
            failure_modes = extract_failure_modes(review)

            recommendations = review.get("recommendations")
            if isinstance(recommendations, Sequence):
                for recommendation_index, recommendation in enumerate(recommendations):
                    if not isinstance(recommendation, Mapping):
                        continue

                    for match in collect_structured_new_fixture_hits(
                        recommendation,
                        fixture_name=fixture_name,
                        fixture_rel_path=fixture_rel_path,
                    ):
                        hits.append(
                            {
                                "team": team_letter,
                                "team_file": team_file,
                                "demo_file": demo_file,
                                "review_index": review_index,
                                "recommendation_index": recommendation_index,
                                "match_type": "new_fixture_evidence",
                                "matched_field_path": (
                                    f"reviews.[{review_index}].recommendations.[{recommendation_index}]."
                                    f"{match['matched_field_path']}"
                                ),
                                "matched_text_excerpt": match["matched_text_excerpt"],
                                "failure_modes": failure_modes,
                            }
                        )

            # Rule 2: any review/recommendation field containing fixture filename string.
            for match in value_mentions_fixture(review, fixture_name, fixture_rel_path):
                hits.append(
                    {
                        "team": team_letter,
                        "team_file": team_file,
                        "demo_file": demo_file,
                        "review_index": review_index,
                        "recommendation_index": None,
                        "match_type": "review_text_match",
                        "matched_field_path": f"reviews.[{review_index}].{match['matched_field_path']}",
                        "matched_text_excerpt": match["matched_text_excerpt"],
                        "failure_modes": failure_modes,
                    }
                )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for hit in sorted(
        hits,
        key=lambda item: (
            item.get("team_file") or "",
            int(item.get("review_index", -1)),
            -1 if item.get("recommendation_index") is None else int(item["recommendation_index"]),
            item.get("match_type") or "",
            item.get("matched_field_path") or "",
            item.get("matched_text_excerpt") or "",
        ),
    ):
        key = (
            hit.get("team_file"),
            hit.get("review_index"),
            hit.get("recommendation_index"),
            hit.get("match_type"),
            hit.get("matched_field_path"),
            hit.get("matched_text_excerpt"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def extract_fmea_modes_present(fmea_md_text: str) -> set[str]:
    return set(FM_PATTERN.findall(fmea_md_text))


def fmea_presence_records(inferred_modes: list[str], fmea_modes_present: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "failure_mode": mode,
            "present_in_fmea_md": mode in fmea_modes_present,
        }
        for mode in sorted(inferred_modes)
    ]


def status_label(in_review_queue: bool, generated_by_review_team: bool) -> str:
    if generated_by_review_team and in_review_queue:
        return "GENERATED_AND_QUEUED"
    if generated_by_review_team and not in_review_queue:
        return "GENERATED_NOT_QUEUED"
    return "NOT_FOUND_IN_REVIEW_TEAMS"


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "fixture",
                "in_review_queue",
                "in_review_queue_reason",
                "generated_by_review_team",
                "status_label",
                "inferred_failure_modes",
                "fmea_modes_present",
                "review_team_hit_count",
                "review_team_files",
            ],
        )
        writer.writeheader()
        for record in records:
            fmea_modes = ";".join(
                f"{item['failure_mode']}:{1 if item['present_in_fmea_md'] else 0}"
                for item in record["fmea_modes_present"]
            )
            review_team_files = sorted(
                {
                    str(hit.get("team_file"))
                    for hit in record["review_team_hits"]
                    if hit.get("team_file")
                }
            )
            writer.writerow(
                {
                    "fixture": record["fixture"],
                    "in_review_queue": record["in_review_queue"],
                    "in_review_queue_reason": record["in_review_queue_reason"],
                    "generated_by_review_team": record["generated_by_review_team"],
                    "status_label": record["status_label"],
                    "inferred_failure_modes": ";".join(record["inferred_failure_modes"]),
                    "fmea_modes_present": fmea_modes,
                    "review_team_hit_count": len(record["review_team_hits"]),
                    "review_team_files": ";".join(review_team_files),
                }
            )


def main() -> None:
    args = parse_args()

    fixtures_dir = Path(args.fixtures_dir)
    compiled_json_path = Path(args.compiled_json)
    review_dir = Path(args.review_dir)
    fmea_md_path = Path(args.fmea_md)
    out_json_path = Path(args.out_json) if args.out_json else None
    out_csv_path = Path(args.out_csv) if args.out_csv else None

    compiled_json = read_json_file(compiled_json_path)
    if not isinstance(compiled_json, Mapping):
        raise SystemExit(f"Expected object in compiled JSON: {compiled_json_path}")

    review_docs: list[tuple[Path, Mapping[str, Any]]] = []
    for review_file in sorted(review_dir.glob("*.json")):
        review_doc = read_json_file(review_file)
        if isinstance(review_doc, Mapping):
            review_docs.append((review_file, review_doc))

    all_fixtures = list_fixture_json_files(fixtures_dir)
    review_queue_fixtures, queue_reasons = collect_review_queue_fixtures(compiled_json)
    extras = sorted([fixture for fixture in all_fixtures if fixture not in review_queue_fixtures])

    fmea_modes_present = extract_fmea_modes_present(fmea_md_path.read_text(encoding="utf-8"))

    records: list[dict[str, Any]] = []
    for fixture in extras:
        fixture_rel_path = f"tests_rlm_adk/fixtures/provider_fake/{fixture}"
        in_review_queue = fixture in review_queue_fixtures
        reason = (
            "Matched " + ", ".join(queue_reasons.get(fixture, []))
            if in_review_queue
            else "Not found in compiled fixture review queue (compiled.reviews + compiled.verdicts)."
        )
        hits = collect_review_team_hits_for_fixture(
            fixture_name=fixture,
            review_docs=review_docs,
            fixture_rel_path=fixture_rel_path,
        )
        inferred_failure_modes = sorted(
            {
                mode
                for hit in hits
                for mode in hit.get("failure_modes", [])
                if isinstance(mode, str)
            }
        )
        generated = bool(hits)
        record = {
            "fixture": fixture,
            "in_review_queue": in_review_queue,
            "in_review_queue_reason": reason,
            "generated_by_review_team": generated,
            "review_team_hits": hits,
            "inferred_failure_modes": inferred_failure_modes,
            "fmea_modes_present": fmea_presence_records(
                inferred_modes=inferred_failure_modes,
                fmea_modes_present=fmea_modes_present,
            ),
            "status_label": status_label(
                in_review_queue=in_review_queue,
                generated_by_review_team=generated,
            ),
        }
        records.append(record)

    records.sort(key=lambda item: item["fixture"])

    status_counts: dict[str, int] = defaultdict(int)
    for record in records:
        status_counts[record["status_label"]] += 1

    summary = {
        "total_fixture_json_files": len(all_fixtures),
        "review_queue_fixture_count": len(review_queue_fixtures),
        "extra_fixture_count": len(records),
        "generated_by_review_team_count": sum(1 for item in records if item["generated_by_review_team"]),
        "status_counts": {key: status_counts[key] for key in sorted(status_counts.keys())},
        "total_review_team_hits": sum(len(item["review_team_hits"]) for item in records),
    }

    result = {
        "inputs": {
            "fixtures_dir": str(fixtures_dir),
            "compiled_json": str(compiled_json_path),
            "review_dir": str(review_dir),
            "fmea_md": str(fmea_md_path),
        },
        "summary": summary,
        "extra_fixtures": records,
    }

    print(f"Total fixture JSON files: {summary['total_fixture_json_files']}")
    print(f"Review queue fixtures: {summary['review_queue_fixture_count']}")
    print(f"Extra fixtures audited: {summary['extra_fixture_count']}")
    print(f"Generated by review teams: {summary['generated_by_review_team_count']}")
    for label in sorted(summary["status_counts"].keys()):
        print(f"  {label}: {summary['status_counts'][label]}")

    if out_json_path:
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        out_json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if out_csv_path:
        write_csv(out_csv_path, records)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

