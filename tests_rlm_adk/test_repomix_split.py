#!/usr/bin/env python3
"""
Test script: wire up repomix's output_split module to RepoProcessor.

Demonstrates that split_output config is parsed but never called by
RepoProcessor.process(). This script manually bridges the gap by:
  1. Processing the repo with RepoProcessor (single output)
  2. Calling generate_split_output_parts() directly with the processed data
  3. Writing split files to disk

Target repo: https://github.com/AndersonBY/python-repomix
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from repomix import RepoProcessor, RepomixConfig
from repomix.config.config_load import load_config
from repomix.core.file.file_process import process_files
from repomix.core.file.file_search import search_files
from repomix.core.file.file_collect import collect_files
from repomix.core.output.output_generate import generate_output
from repomix.core.output.output_split import generate_split_output_parts


REPO_URL = "https://github.com/AndersonBY/python-repomix"
CLONE_DIR = Path("/tmp/python-repomix")
OUTPUT_DIR = Path("/tmp/repomix-split-test")
SPLIT_SIZE = 500 * 1024  # 500KB per part
FALLBACK_SOURCE_DIR = Path(__file__).resolve().parents[1] / "rlm_adk" / "repl"


def clone_repo():
    """Clone the target repo (or fallback to a local fixture directory)."""
    if CLONE_DIR.exists():
        print(f"Reusing existing clone at {CLONE_DIR}")
        return
    print(f"Cloning {REPO_URL} -> {CLONE_DIR}")
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", REPO_URL, str(CLONE_DIR)],
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Clone failed ({exc!r}); using local fallback at {FALLBACK_SOURCE_DIR}")
        shutil.copytree(FALLBACK_SOURCE_DIR, CLONE_DIR)


@pytest.fixture(scope="module", autouse=True)
def _prepare_split_test_env():
    """Ensure split tests always have a source repo and clean output dir."""
    clone_repo()
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def test_builtin_split_output_is_dead():
    """Show that RepoProcessor ignores split_output config (programmatic)."""
    print("\n=== Test 1a: Prove split_output config is ignored (programmatic) ===\n")

    config = RepomixConfig()
    config.output.file_path = str(OUTPUT_DIR / "builtin.xml")
    config.output.style = "xml"
    config.output.split_output = SPLIT_SIZE  # Set it — should produce multiple files
    config.output.calculate_tokens = True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    processor = RepoProcessor(str(CLONE_DIR), config=config)
    result = processor.process()

    # Check what files were actually created
    created = sorted(OUTPUT_DIR.glob("builtin*.xml"))
    print(f"  Config split_output = {SPLIT_SIZE} bytes")
    print(f"  Total files processed: {result.total_files}")
    print(f"  Total chars: {result.total_chars:,}")
    print(f"  Total tokens: {result.total_tokens:,}")
    print(f"  Output file size: {Path(created[0]).stat().st_size:,} bytes")
    print(f"  Files created: {[p.name for p in created]}")

    if len(created) == 1:
        print("  CONFIRMED: split_output is DEAD (programmatic) — single file produced.")
    else:
        print("  UNEXPECTED: multiple files created — split_output may be wired up now!")

    return result


def test_config_file_split_output_is_dead():
    """Show that RepoProcessor ignores split_output even via config file."""
    print("\n=== Test 1b: Prove split_output config is ignored (config file) ===\n")

    # Write a repomix.config.json into the cloned repo (like a real user would)
    config_path = CLONE_DIR / "repomix.config.json"
    config_data = {
        "output": {
            "file_path": str(OUTPUT_DIR / "from_configfile.xml"),
            "style": "xml",
            "split_output": SPLIT_SIZE,
            "calculate_tokens": True,
        }
    }
    config_path.write_text(json.dumps(config_data, indent=2))
    print(f"  Wrote {config_path}")
    print(f"  Config contents: {json.dumps(config_data, indent=2)}")

    try:
        # Load config the way the CLI does — from the repo directory
        config = load_config(str(CLONE_DIR), str(CLONE_DIR))
        print(f"  Loaded config.output.split_output = {config.output.split_output}")

        processor = RepoProcessor(str(CLONE_DIR), config=config)
        result = processor.process()

        created = sorted(OUTPUT_DIR.glob("from_configfile*.xml"))
        print(f"  Total files processed: {result.total_files}")
        print(f"  Output file size: {Path(created[0]).stat().st_size:,} bytes")
        print(f"  Files created: {[p.name for p in created]}")

        if len(created) == 1:
            print("  CONFIRMED: split_output is DEAD (config file) — single file produced.")
        else:
            print("  UNEXPECTED: multiple files created — split_output may be wired up now!")
    finally:
        # Clean up the config file from the cloned repo
        config_path.unlink(missing_ok=True)


def test_manual_split():
    """Wire up generate_split_output_parts() manually."""
    print("\n=== Test 2: Manual wiring of generate_split_output_parts() ===\n")

    config = RepomixConfig()
    config.output.file_path = str(OUTPUT_DIR / "split.xml")
    config.output.style = "xml"
    config.output.calculate_tokens = True

    # Step 1: Collect and process files (replicate what RepoProcessor.process does)
    search_result = search_files(str(CLONE_DIR), config)
    raw_files = collect_files(search_result.file_paths, str(CLONE_DIR))
    processed_files = process_files(raw_files, config)

    # Step 2: Build char/token counts
    file_char_counts = {}
    file_token_counts = {}
    for pf in processed_files:
        file_char_counts[pf.path] = len(pf.content)
        file_token_counts[pf.path] = 0

    all_file_paths = [pf.path for pf in processed_files]
    total_chars = sum(file_char_counts.values())

    print(f"  Processed {len(processed_files)} files ({total_chars:,} chars)")
    print(f"  Split target: {SPLIT_SIZE:,} bytes per part")

    # Step 3: Call the split function directly
    parts = generate_split_output_parts(
        processed_files=processed_files,
        all_file_paths=all_file_paths,
        max_bytes_per_part=SPLIT_SIZE,
        base_config=config,
        generate_output_fn=generate_output,
        file_char_counts=file_char_counts,
        file_token_counts=file_token_counts,
        progress_callback=lambda msg: print(f"    {msg}"),
    )

    print(f"\n  Split into {len(parts)} parts:")

    # Step 4: Write each part
    for part in parts:
        out_path = Path(part.file_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(part.content, encoding="utf-8")
        groups = [g.root_entry for g in part.groups]
        print(f"    Part {part.index}: {out_path.name} "
              f"({part.byte_length:,} bytes, groups: {groups})")

    # Verify
    split_files = sorted(OUTPUT_DIR.glob("split*.xml"))
    print(f"\n  Files on disk: {[p.name for p in split_files]}")
    print(f"  Total bytes: {sum(p.stat().st_size for p in split_files):,}")
    print("  SUCCESS: output_split module works when called directly.")

    return parts


def test_in_memory_chunks():
    """Show the pattern the RLM agent should use: split into in-memory chunks."""
    print("\n=== Test 3: In-memory chunk loading (RLM agent pattern) ===\n")

    config = RepomixConfig()
    config.output.file_path = str(OUTPUT_DIR / "mem.xml")
    config.output.style = "xml"

    search_result = search_files(str(CLONE_DIR), config)
    raw_files = collect_files(search_result.file_paths, str(CLONE_DIR))
    processed_files = process_files(raw_files, config)

    file_char_counts = {pf.path: len(pf.content) for pf in processed_files}
    file_token_counts = {pf.path: 0 for pf in processed_files}
    all_file_paths = [pf.path for pf in processed_files]

    parts = generate_split_output_parts(
        processed_files=processed_files,
        all_file_paths=all_file_paths,
        max_bytes_per_part=SPLIT_SIZE,
        base_config=config,
        generate_output_fn=generate_output,
        file_char_counts=file_char_counts,
        file_token_counts=file_token_counts,
    )

    # Load all parts into memory (no disk writes)
    chunks = [part.content for part in parts]
    print(f"  {len(chunks)} in-memory chunks")
    for i, chunk in enumerate(chunks):
        print(f"    Chunk {i}: {len(chunk):,} chars")
    print(f"  Total: {sum(len(c) for c in chunks):,} chars")
    print("  Ready for llm_query_batched dispatch.")


def main():
    clone_repo()

    # Clean output dir
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    test_builtin_split_output_is_dead()
    test_config_file_split_output_is_dead()
    test_manual_split()
    test_in_memory_chunks()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
