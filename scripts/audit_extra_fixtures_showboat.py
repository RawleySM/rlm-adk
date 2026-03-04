#!/usr/bin/env python3
"""Audit demo_showboat evidence for each provider-fake extra fixture.

Usage examples:
    python3 scripts/audit_extra_fixtures_showboat.py
    python3 scripts/audit_extra_fixtures_showboat.py \
      --fixtures-audit-json /tmp/extra_fixtures_review_queue.json \
      --out-json /tmp/extra_fixtures_showboat.json \
      --out-csv /tmp/extra_fixtures_showboat.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

TEAM_FILE_PATTERN = re.compile(r"review_team_([a-z])\.json$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse demo_showboat markdown/python files for evidence tied to "
            "provider-fake extra fixtures."
        )
    )
    parser.add_argument(
        "--fixtures-audit-json",
        default=None,
        help="Optional JSON output from audit_extra_fixtures_review_queue.py.",
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
        "--demo-dir",
        default="demo_showboat",
        help="Directory containing demo evidence files.",
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


def list_fixture_json_files(fixtures_dir: Path) -> list[str]:
    names = [
        path.name
        for path in fixtures_dir.glob("*.json")
        if path.is_file() and path.name != "index.json"
    ]
    return sorted(names)


def collect_review_queue_fixtures(compiled_json: Mapping[str, Any]) -> set[str]:
    queue: set[str] = set()
    for review in compiled_json.get("reviews", []):
        if not isinstance(review, Mapping):
            continue
        if review.get("review_type") != "fixture":
            continue
        fixture = review.get("fixture")
        if isinstance(fixture, str):
            normalized = normalize_fixture_name(fixture)
            if normalized:
                queue.add(normalized)

    verdicts = compiled_json.get("verdicts")
    if isinstance(verdicts, Mapping):
        for fixture in verdicts.keys():
            if isinstance(fixture, str):
                normalized = normalize_fixture_name(fixture)
                if normalized:
                    queue.add(normalized)
    return queue


def value_mentions_fixture(value: Any, fixture_name: str, fixture_rel_path: str) -> bool:
    for _, text in iter_json_strings(value):
        if fixture_name in text or fixture_rel_path in text:
            return True
    return False


def recommendation_mentions_fixture(
    recommendation: Mapping[str, Any],
    fixture_name: str,
    fixture_rel_path: str,
) -> bool:
    if recommendation.get("type") != "new_fixture":
        return False
    candidates: dict[str, Any] = {
        "action": recommendation.get("action"),
        "notes": recommendation.get("notes"),
        "evidence": recommendation.get("evidence"),
    }
    resolution = recommendation.get("resolution")
    if isinstance(resolution, Mapping):
        for key in ("action", "notes", "evidence"):
            candidates[f"resolution.{key}"] = resolution.get(key)
    return any(value_mentions_fixture(candidate, fixture_name, fixture_rel_path) for candidate in candidates.values())


def review_team_letter(team_file_name: str) -> str | None:
    match = TEAM_FILE_PATTERN.search(team_file_name)
    if not match:
        return None
    return match.group(1).upper()


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

            found = False
            recommendations = review.get("recommendations")
            if isinstance(recommendations, Sequence):
                for recommendation_index, recommendation in enumerate(recommendations):
                    if not isinstance(recommendation, Mapping):
                        continue
                    if recommendation_mentions_fixture(
                        recommendation=recommendation,
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
                            }
                        )
                        found = True

            if value_mentions_fixture(review, fixture_name, fixture_rel_path):
                hits.append(
                    {
                        "team": team_letter,
                        "team_file": team_file,
                        "demo_file": demo_file,
                        "review_index": review_index,
                        "recommendation_index": None,
                        "match_type": "review_text_match",
                    }
                )
                found = True

            if found:
                continue

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for hit in sorted(
        hits,
        key=lambda item: (
            item.get("team_file") or "",
            int(item.get("review_index", -1)),
            -1 if item.get("recommendation_index") is None else int(item["recommendation_index"]),
            item.get("match_type") or "",
        ),
    ):
        key = (
            hit.get("team"),
            hit.get("team_file"),
            hit.get("demo_file"),
            hit.get("review_index"),
            hit.get("recommendation_index"),
            hit.get("match_type"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def recompute_fixtures_audit_records(
    fixtures_dir: Path,
    compiled_json_path: Path,
    review_dir: Path,
) -> list[dict[str, Any]]:
    compiled_json = read_json_file(compiled_json_path)
    if not isinstance(compiled_json, Mapping):
        raise SystemExit(f"Expected object in compiled JSON: {compiled_json_path}")

    review_docs: list[tuple[Path, Mapping[str, Any]]] = []
    for review_file in sorted(review_dir.glob("*.json")):
        review_doc = read_json_file(review_file)
        if isinstance(review_doc, Mapping):
            review_docs.append((review_file, review_doc))

    all_fixtures = list_fixture_json_files(fixtures_dir)
    queue = collect_review_queue_fixtures(compiled_json)
    extras = sorted([fixture for fixture in all_fixtures if fixture not in queue])

    records: list[dict[str, Any]] = []
    for fixture in extras:
        fixture_rel_path = f"tests_rlm_adk/fixtures/provider_fake/{fixture}"
        hits = collect_review_team_hits_for_fixture(
            fixture_name=fixture,
            review_docs=review_docs,
            fixture_rel_path=fixture_rel_path,
        )
        records.append(
            {
                "fixture": fixture,
                "in_review_queue": fixture in queue,
                "generated_by_review_team": bool(hits),
                "review_team_hits": hits,
            }
        )
    records.sort(key=lambda item: item["fixture"])
    return records


def load_fixture_audit_records(
    fixtures_audit_json: Path | None,
    fixtures_dir: Path,
    compiled_json_path: Path,
    review_dir: Path,
) -> tuple[list[dict[str, Any]], str]:
    if fixtures_audit_json is not None:
        payload = read_json_file(fixtures_audit_json)
        if not isinstance(payload, Mapping):
            raise SystemExit(f"Expected object in fixtures audit JSON: {fixtures_audit_json}")
        records = payload.get("extra_fixtures")
        if not isinstance(records, Sequence):
            raise SystemExit(
                "fixtures audit JSON must include `extra_fixtures` as a list."
            )
        normalized: list[dict[str, Any]] = []
        for item in records:
            if not isinstance(item, Mapping):
                continue
            fixture = item.get("fixture")
            if not isinstance(fixture, str):
                continue
            review_team_hits = item.get("review_team_hits")
            if not isinstance(review_team_hits, Sequence):
                review_team_hits = []
            normalized.append(
                {
                    "fixture": fixture,
                    "in_review_queue": bool(item.get("in_review_queue", False)),
                    "generated_by_review_team": bool(item.get("generated_by_review_team", False)),
                    "review_team_hits": list(review_team_hits),
                }
            )
        normalized.sort(key=lambda row: row["fixture"])
        return normalized, "loaded_fixtures_audit_json"

    return (
        recompute_fixtures_audit_records(
            fixtures_dir=fixtures_dir,
            compiled_json_path=compiled_json_path,
            review_dir=review_dir,
        ),
        "recomputed_from_defaults",
    )


def list_demo_files(demo_dir: Path) -> list[Path]:
    files = [
        path
        for path in demo_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".py"}
    ]
    return sorted(files)


def fixture_direct_mentions(fixture: str, demo_files: list[Path], demo_dir: Path) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    for path in demo_files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        line_numbers = [index for index, line in enumerate(lines, start=1) if fixture in line]
        if line_numbers:
            mentions.append(
                {
                    "file": str(path.relative_to(demo_dir)),
                    "line_numbers": line_numbers,
                }
            )
    mentions.sort(key=lambda item: item["file"])
    return mentions


def extract_teams_from_hits(review_team_hits: Sequence[Any]) -> list[str]:
    teams: set[str] = set()
    for hit in review_team_hits:
        if not isinstance(hit, Mapping):
            continue
        team = hit.get("team")
        if isinstance(team, str) and team.strip():
            teams.add(team.strip().upper())
            continue
        team_file = hit.get("team_file")
        if isinstance(team_file, str):
            inferred = review_team_letter(team_file)
            if inferred:
                teams.add(inferred)
    return sorted(teams)


def linked_team_demo_files(
    review_team_hits: Sequence[Any],
    demo_dir: Path,
) -> list[dict[str, Any]]:
    teams = extract_teams_from_hits(review_team_hits)
    linked: dict[tuple[str | None, str], dict[str, Any]] = {}

    for team in teams:
        demo_file = f"demo_fmea_team_{team.lower()}.md"
        exists = (demo_dir / demo_file).exists()
        linked[(team, demo_file)] = {
            "team": team,
            "demo_file": demo_file,
            "exists": exists,
        }

    for hit in review_team_hits:
        if not isinstance(hit, Mapping):
            continue
        demo_file = hit.get("demo_file")
        if not isinstance(demo_file, str) or not demo_file.strip():
            continue
        team = hit.get("team")
        team_value = team.strip().upper() if isinstance(team, str) and team.strip() else None
        key = (team_value, demo_file)
        linked[key] = {
            "team": team_value,
            "demo_file": demo_file,
            "exists": (demo_dir / demo_file).exists(),
        }

    return sorted(linked.values(), key=lambda item: ((item.get("team") or ""), item["demo_file"]))


def classify_showboat_status(
    direct_mentions: list[dict[str, Any]],
    team_demo_links: list[dict[str, Any]],
) -> str:
    if direct_mentions:
        return "DEMO_CONFIRMED"
    if any(bool(item.get("exists")) for item in team_demo_links):
        return "TEAM_DEMO_ONLY"
    return "NO_DEMO_EVIDENCE"


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "fixture",
                "showboat_status",
                "generated_by_review_team",
                "in_review_queue",
                "direct_mention_files",
                "direct_mention_lines",
                "review_teams",
                "linked_team_demo_files",
            ],
        )
        writer.writeheader()
        for record in records:
            direct_mention_files = ";".join(item["file"] for item in record["direct_mentions"])
            direct_mention_lines = ";".join(
                f"{item['file']}:{','.join(str(x) for x in item['line_numbers'])}"
                for item in record["direct_mentions"]
            )
            review_teams = ";".join(record["review_teams"])
            linked_team_demo = ";".join(
                f"{item['demo_file']}:{1 if item['exists'] else 0}"
                for item in record["linked_team_demo_files"]
            )
            writer.writerow(
                {
                    "fixture": record["fixture"],
                    "showboat_status": record["showboat_status"],
                    "generated_by_review_team": record["generated_by_review_team"],
                    "in_review_queue": record["in_review_queue"],
                    "direct_mention_files": direct_mention_files,
                    "direct_mention_lines": direct_mention_lines,
                    "review_teams": review_teams,
                    "linked_team_demo_files": linked_team_demo,
                }
            )


def main() -> None:
    args = parse_args()

    fixtures_audit_json = Path(args.fixtures_audit_json) if args.fixtures_audit_json else None
    fixtures_dir = Path(args.fixtures_dir)
    compiled_json_path = Path(args.compiled_json)
    review_dir = Path(args.review_dir)
    demo_dir = Path(args.demo_dir)
    out_json_path = Path(args.out_json) if args.out_json else None
    out_csv_path = Path(args.out_csv) if args.out_csv else None

    fixture_records, fixture_source = load_fixture_audit_records(
        fixtures_audit_json=fixtures_audit_json,
        fixtures_dir=fixtures_dir,
        compiled_json_path=compiled_json_path,
        review_dir=review_dir,
    )
    demo_files = list_demo_files(demo_dir)

    output_records: list[dict[str, Any]] = []
    for fixture_record in fixture_records:
        fixture = fixture_record["fixture"]
        review_team_hits = fixture_record.get("review_team_hits", [])
        direct_mentions = fixture_direct_mentions(fixture, demo_files=demo_files, demo_dir=demo_dir)
        team_demo_links = linked_team_demo_files(review_team_hits=review_team_hits, demo_dir=demo_dir)
        showboat_status = classify_showboat_status(direct_mentions=direct_mentions, team_demo_links=team_demo_links)
        review_teams = extract_teams_from_hits(review_team_hits)

        output_records.append(
            {
                "fixture": fixture,
                "in_review_queue": bool(fixture_record.get("in_review_queue", False)),
                "generated_by_review_team": bool(fixture_record.get("generated_by_review_team", False)),
                "review_teams": review_teams,
                "direct_mentions": direct_mentions,
                "linked_team_demo_files": team_demo_links,
                "showboat_status": showboat_status,
            }
        )

    output_records.sort(key=lambda item: item["fixture"])

    status_counts: dict[str, int] = defaultdict(int)
    for item in output_records:
        status_counts[item["showboat_status"]] += 1

    summary = {
        "fixture_source": fixture_source,
        "extra_fixture_count": len(output_records),
        "demo_file_count_scanned": len(demo_files),
        "status_counts": {key: status_counts[key] for key in sorted(status_counts.keys())},
        "direct_mention_fixture_count": sum(1 for item in output_records if item["direct_mentions"]),
        "total_direct_mentions": sum(len(item["direct_mentions"]) for item in output_records),
    }

    result = {
        "inputs": {
            "fixtures_audit_json": str(fixtures_audit_json) if fixtures_audit_json else None,
            "fixtures_dir": str(fixtures_dir),
            "compiled_json": str(compiled_json_path),
            "review_dir": str(review_dir),
            "demo_dir": str(demo_dir),
        },
        "summary": summary,
        "extra_fixtures": output_records,
    }

    print(f"Extra fixtures audited: {summary['extra_fixture_count']}")
    print(f"Demo files scanned (.md/.py): {summary['demo_file_count_scanned']}")
    print(f"Fixtures with direct demo mentions: {summary['direct_mention_fixture_count']}")
    for label in sorted(summary["status_counts"].keys()):
        print(f"  {label}: {summary['status_counts'][label]}")

    if out_json_path:
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        out_json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if out_csv_path:
        write_csv(out_csv_path, output_records)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
