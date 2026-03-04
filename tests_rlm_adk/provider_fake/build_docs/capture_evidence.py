"""Capture evidence script — runs the request_body_roundtrip fixture and
persists captured request bodies with marker extraction for the demo doc."""

import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract
from tests_rlm_adk.provider_fake.fixtures import save_captured_requests

FIXTURE_PATH = FIXTURE_DIR / "request_body_roundtrip.json"
OUTPUT_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = OUTPUT_DIR / "captured_requests.json"

MARKERS = [
    ("«ARTIFACT_START»", "«ARTIFACT_END»", "artifact dict in worker request", [1]),
    ("«WORKER_INSTRUCTION_START»", "«WORKER_INSTRUCTION_END»", "instruction in worker request", [1]),
    ("«WORKER_RESPONSE_START»", "«WORKER_RESPONSE_END»", "worker response in reasoning iter2", [2]),
    ("«STDOUT_SENTINEL_START»", "«STDOUT_SENTINEL_END»", "stdout sentinel in reasoning iter2", [2]),
    ("«FINAL_ANSWER_START»", "«FINAL_ANSWER_END»", "final answer in session state", None),
    ("«DYNAMIC_CONTEXT_START»", "«DYNAMIC_CONTEXT_END»", "dynamic context in systemInstruction", [0, 2]),
]


def _find_content(text: str, start: str, end: str) -> str | None:
    s = text.find(start)
    e = text.find(end)
    if s == -1 or e == -1 or e <= s:
        return None
    return text[s + len(start):e]


async def main():
    print("=" * 70)
    print("Request Body Capture — Evidence Collection")
    print("=" * 70)

    # Run fixture
    print("\n[1] Running request_body_roundtrip fixture...")
    result = await run_fixture_contract(FIXTURE_PATH)
    print(f"    Contract passed: {result.passed}")
    print(f"    Captured requests: {len(result.captured_requests)}")

    # Save to disk
    print(f"\n[2] Persisting captured requests to: {OUTPUT_PATH}")
    save_captured_requests(result.captured_requests, OUTPUT_PATH, result.captured_metadata)
    print(f"    Written: {OUTPUT_PATH.stat().st_size} bytes")

    # Summarize each captured request
    print("\n[3] Request body summaries:")
    for i, req in enumerate(result.captured_requests):
        keys = sorted(req.keys())
        req_str = json.dumps(req, ensure_ascii=False)
        print(f"\n    Call {i}:")
        print(f"      Top-level keys: {keys}")
        print(f"      Serialized length: {len(req_str)} chars")
        if "systemInstruction" in req:
            si = json.dumps(req["systemInstruction"], ensure_ascii=False)
            print(f"      systemInstruction length: {len(si)} chars")
        if "tools" in req:
            print(f"      tools count: {len(req.get('tools', []))}")
        if "contents" in req:
            print(f"      contents count: {len(req.get('contents', []))}")
            roles = [c.get("role") for c in req.get("contents", [])]
            print(f"      content roles: {roles}")

    # Extract marker content
    print("\n[4] Marker extraction (content between guillemet pairs):")
    all_ok = True
    for start_m, end_m, desc, indices in MARKERS:
        if indices is None:
            continue
        for idx in indices:
            req_str = json.dumps(result.captured_requests[idx], ensure_ascii=False)
            content = _find_content(req_str, start_m, end_m)
            present = content is not None
            if not present:
                all_ok = False
            label = f"{start_m}..{end_m} (call {idx})"
            if present:
                # Truncate for readability
                display = content.strip()
                if len(display) > 120:
                    display = display[:120] + "..."
                print(f"\n    {label}")
                print(f"      Description: {desc}")
                print(f"      Content ({len(content)} chars): {display}")
            else:
                print(f"\n    {label}")
                print(f"      NOT FOUND")

    # Verification summary
    print("\n" + "=" * 70)
    if all_ok:
        print("ALL MARKERS PRESENT — content not truncated")
    else:
        print("WARNING: Some markers missing!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
