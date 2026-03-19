# NotebookLM Skill Enhancement Proposal

**Date:** 2026-03-19
**Source:** Code architect review of pipeline execution trace + Artem Zhutov article comparison + ytcli review

---

## 1. Pipeline Friction Analysis

### Phase A — Source Discovery (entirely ad-hoc, pre-skill)

The pipeline agent's trace shows 34 sources were assembled before the skill ran. This work happened in interactive sessions with no automation:

| Category | Friction | Evidence |
|---|---|---|
| YouTube source discovery | Inline Python, manual URL-by-URL add | No `search_youtube.py` existed; each URL required a separate `notebooklm source add` call |
| Substack discovery | 4 separate ad-hoc API calls with inline format debugging | `trending`, `category/public`, `archive?search=`, `publication/search` each needed separate inline scripts |
| Auth recovery | Inline Python snippet embedded in task prompt | NotebookLM cookie refresh code was copy-pasted into every prompt as contingency |
| Source URL loss | YouTube sources had `url: null` in exported JSON | The notebooklm CLI doesn't preserve original YouTube URLs in source list |
| Batch source add | No file-driven bulk add mode | `notebooklm source add` takes one URL at a time; 34 adds = 34 subprocess calls |
| Substack cross-newsletter search | Auth required, returned empty | `/api/v1/publication/search` returned 0 results for all queries |
| Source curation | Manual review of 10+ query results per query | No relevance filtering, date filtering, or dedup across queries |

### Phase B — Import/Ask/Resolve (structured, followed skill)

Zero friction — the existing skill scripts (`import_sources.py`, `extract_passages.py`, `resolve_citations.py`) covered this phase completely. The agent followed `workflows/import.md` and `workflows/ask.md` faithfully.

**Conclusion:** The skill automates the downstream pipeline well. The gap is entirely in **source discovery** — the upstream phase that feeds the notebook.

---

## 2. Proposed: `scripts/search_substack.py`

### File path
`~/.claude/skills/notebooklm/scripts/search_substack.py`

### Design

Three-layer priority search that codifies the working API endpoints:

```
Layer 1: Trending posts (/api/v1/trending?category_id=N)  — real-time signal, no auth
Layer 2: Category-ranked newsletters + archive search     — broad discovery, no auth
Layer 2b: Named newsletter archives                        — targeted, no auth
Layer 3: Global publication search                         — best-effort, requires auth
```

### CLI interface

```bash
python3 search_substack.py "AI agent advertising" \
    --category-ids 4 76964 \
    --newsletters "aireadycmo.substack.com" "newsletter.mkt1.co" \
    --date-after 2025-01-01 \
    --min-score 0.3 \
    --output /tmp/substack-sources.json \
    --print-commands
```

### Function signatures

```python
def search_trending(category_ids: list[int], keywords: list[str],
                    date_after: date | None, limit: int = 50) -> list[dict]

def search_category_archives(category_ids: list[int], query: str,
                             keywords: list[str], date_after: date | None,
                             max_newsletters: int = 10) -> list[dict]

def search_named_newsletters(newsletter_urls: list[str], query: str,
                             keywords: list[str], date_after: date | None) -> list[dict]

def search_publications_authenticated(queries: list[str],
                                      username: str = "rawleystanhope") -> list[dict]

def format_for_notebooklm(sources: list[dict], topic: str,
                           min_score: float = 0.0) -> dict
```

### Key design decisions

- **Score formula:** `(reactions * 1 + restacks * 2 + comments * 1.5) / 1000`, capped at 1.0. Restacks weighted higher because they signal expert endorsement.
- **Auth graceful degradation:** Never fails due to missing auth — logs a warning and skips Layer 3. Matches SubstackClient design in `client.py:142`.
- **Cross-newsletter limitation:** Publication search returns newsletters, not posts. Script marks these with `source_type: "newsletter"` so callers know to follow up with archive search.
- **Output format:** `{"topic", "query_date", "total", "sources": [{title, url, score, layer, ...}]}` — compatible with `notebooklm source add` loop.

### API calls used

| Endpoint | Layer | Auth | Purpose |
|----------|-------|------|---------|
| `GET /api/v1/trending?limit=50&category_id=N` | 1 | No | Currently viral posts |
| `GET /api/v1/category/public/{id}/{sort}?page=N` | 2 | No | Ranked newsletters per category |
| `GET {nl_url}/api/v1/archive?sort=top&search=Q` | 2/2b | No | Search within one newsletter |
| `GET /api/v1/publication/search?query=X` | 3 | Yes | Global newsletter discovery |

---

## 3. Proposed: `scripts/search_youtube.py`

### File path
`~/.claude/skills/notebooklm/scripts/search_youtube.py`

### Design

Multi-query search with deduplication, stats enrichment (view counts via separate API call), and optional auto-add to NotebookLM.

### CLI interface

```bash
python3 search_youtube.py "AI agent Facebook ads" \
    --also-search "Meta Advantage+ automation" "MCP server Claude ads" \
    --date-after 2024-01-01 \
    --min-views 1000 \
    --min-duration-secs 120 \
    --max-results 25 \
    --output /tmp/youtube-sources.json \
    --auto-add --max-add 20 \
    --notebooklm-bin ~/.venv/bin/notebooklm \
    --token /home/rawley-stanhope/dev/rlm-adk/token.json
```

### Function signatures

```python
def search_videos(youtube, query: str, max_results: int = 25,
                  published_after: str | None = None, order: str = "relevance") -> list[dict]

def fetch_video_stats(youtube, video_ids: list[str]) -> dict[str, dict]
# Batches in groups of 50 (API limit). Returns {video_id: {view_count, like_count, duration}}

def score_video(video: dict, stats: dict) -> float
# Log-scale view score: 1M views = 1.0, 100K = 0.83, 10K = 0.67, 1K = 0.5

def auto_add_to_notebooklm(sources: list[dict], max_add: int, notebooklm_bin: str) -> None
# Subprocess loop with 1s delay between adds
```

### Key design decisions

- **Multi-query deduplication:** `--also-search` accepts N additional queries; dedup by `video_id` before filtering. First matching query recorded in `matched_query` for provenance.
- **Stats as second API call:** `search().list()` doesn't return view counts; `videos().list(part="statistics")` costs 1 unit per video but makes view-count filtering reliable.
- **Shorts exclusion:** `--min-duration-secs 120` filters out Shorts/clips that add noise to NotebookLM (almost no transcript content).
- **Auto-add via subprocess:** `--auto-add` calls `notebooklm source add` per URL with 1s delay. `--max-add` caps to prevent flooding.

### API quota awareness

| Call | Cost | Typical run (3 queries, 25 results each) |
|------|------|------------------------------------------|
| `search().list()` | 100 units/query | 300 units |
| `videos().list()` | 1 unit/video | ~75 units |
| **Total** | | **~375 units** |
| Daily budget | | 10,000 units (~26 sessions/day) |

---

## 3b. Proposed: `scripts/generate_topic_hubs.py`

### Motivation

Artem Zhutov's Obsidian output creates **topic files as hub nodes** — opening a topic like "Claude Code" shows which 6 videos mentioned it, what they said, and linked passages. Our current `import_sources.py` writes `topics` to frontmatter but does not create the actual topic hub files. This leaves the knowledge graph disconnected: topics exist as tags in source files but have no corresponding nodes in the vault.

### File path
`~/.claude/skills/notebooklm/scripts/generate_topic_hubs.py`

### Design

```python
#!/usr/bin/env python3
"""Generate topic hub files from imported source frontmatter.

Reads all source .md files in a notebook's Sources/ directory,
extracts 'topics' from YAML frontmatter, and creates one hub .md
per unique topic with backlinks to all sources that mention it.

Usage:
  python3 generate_topic_hubs.py --slug my-notebook --dashboard "Dashboard Title"
"""
```

### Behavior

- Scan `Notes/NotebookLM/{slug}/Sources/*.md` for `topics:` frontmatter
- Extract unique topic names (strip `[[` and `]]` wrappers if present)
- For each topic, create `Notes/NotebookLM/{slug}/Topics/{Topic Name}.md` with:
  - Frontmatter: `type: topic`, `status: active`, `related: [[dashboard]]`
  - Body: `# {Topic Name}` heading + `## Sources` section with wikilinks to all source files that list this topic
- Report how many topic hubs were created vs. how many already existed
- Idempotent: re-running updates existing hub files with any new source backlinks

### CLI interface

```bash
python3 generate_topic_hubs.py \
    --slug ai-agent-advertising \
    --dashboard "AI Agent Advertising Dashboard" \
    --vault-root ~/Obsidian/MainVault
```

### Integration

This script runs after `import_sources.py` (Phase 3, Step 9) and before dashboard creation. It converts the flat `topics:` frontmatter tags into navigable hub nodes, completing the knowledge graph that Obsidian's graph view renders.

---

## 4. Proposed: `workflows/research.md`

### File path
`~/.claude/skills/notebooklm/workflows/research.md`

### Pipeline phases

```
Phase 1: Source Discovery (human-curated by default)
  Step 1: search_youtube.py → /tmp/youtube-candidates.json
  Step 2: search_substack.py → /tmp/substack-candidates.json
  Step 3: Review candidate JSONs — approve, reject, or edit entries
  Note: The --auto-add flag is an opt-in convenience. The default
  workflow outputs a candidate list for human review. Artem Zhutov's
  approach emphasizes deliberate source selection over automated bulk
  import: "much more granular control over the sources" — picking
  exactly which videos become research sources improves signal-to-noise.

Phase 2: Notebook Creation + Source Import
  Step 4: notebooklm create "{topic}"
  Step 5: Add approved YouTube sources (--auto-add flag OR manual loop)
  Step 6: Add approved Substack sources (loop over JSON)
  Step 7: notebooklm source list --json → /tmp/notebooklm-sources.json

Phase 3: Vault Import
  Step 8: mkdir vault structure
  Step 9: import_sources.py (existing)
  Step 10: Create dashboard from template

Phase 4: Research Questions
  Step 11: notebooklm ask --new --json (2-6 questions)
  Step 12: extract_passages.py (existing)
  Step 13: resolve_citations.py (existing)

Phase 4.5: Audio Overview (optional)
  Step 14: notebooklm audio generate --topic "gaps in {topic}"
  Generates a podcast-style audio summary of the notebook's sources.
  Output syncs to mobile via Obsidian Sync for async consumption.
  The `notebooklm generate` command family also supports:
    flashcards, slide-deck, quiz, mind-map, report
  Artem uses this to produce listenable digests of research gaps
  that he can review away from the terminal.

Phase 5: Verify
  Count source files, QA notes, check dashboard renders
```

### Workflow routing addition

| User says | Workflow |
|-----------|----------|
| "research", "find sources", "search YouTube", "search Substack", "full pipeline" | `workflows/research.md` |

---

## 5. SKILL.md Updates

### Description (frontmatter)

```
description: End-to-end research pipeline: discover sources from YouTube and Substack,
import into a NotebookLM notebook, ask research questions, and save cited answers into
an Obsidian knowledge graph as linked markdown files. Use when user says "notebooklm import",
"import notebook", "notebooklm ask", "research topic", "find sources", "search YouTube",
or wants to turn NotebookLM research into vault knowledge.
```

### Scripts table additions

| Script | Purpose |
|--------|---------|
| `scripts/search_youtube.py` | Search YouTube Data API v3 for topic-relevant videos; optional auto-add to active notebook |
| `scripts/search_substack.py` | Search Substack trending posts, category archives, and named newsletters; outputs NotebookLM-ready source list |
| `scripts/generate_topic_hubs.py` | Generate topic hub files from source frontmatter; creates navigable hub nodes in Obsidian vault |

---

## 6. Architecture Diagram

```
                    TOPIC / QUERY
                         |
          +--------------+--------------+
          |                             |
          v                             v
  search_youtube.py              search_substack.py
  (YouTube Data API v3)          (Substack APIs)
  - Primary + --also-search      - Layer 1: Trending
  - Stats fetch (views)          - Layer 2: Category archives
  - Duration filter              - Layer 2b: Named newsletters
  - Dedup by video_id            - Layer 3: Pub search (auth)
          |                             |
          v                             v
  /tmp/youtube-candidates.json   /tmp/substack-candidates.json
          |                             |
          +-------------+---------------+
                        |
                        v
              notebooklm source add
              (--auto-add flag OR manual loop)
                        |
                        v
              notebooklm source list --json
                        |
          +-------------+---------------+
          |                             |
          v                             v
  import_sources.py              notebooklm ask --new --json
  (existing skill script)        (2-6 research questions)
          |                             |
          v                    +--------+--------+
  Vault/Sources/*.md           |                 |
                        extract_passages   resolve_citations
                        (existing)         (existing)
                               |                 |
                               v                 v
                        /tmp/passage-map   Vault/QA/*.md
                                           [[Source#Passage N]]
                                                 |
                                                 v
                                      Notes/Dashboards/*.md
                                      (Dataview: sources + QA)
                                                 |
                                                 v
                                      Obsidian Graph View
```

### Auth dependencies

```
search_youtube.py  →  token.json (OAuth, gen-lang-client-0730373468)
                       YouTube Data API v3, 10K units/day

search_substack.py →  SubstackClient (browser-cookie3 Chrome extraction)
                       Layers 1+2: no auth required
                       Layer 3: auth required (returns empty without)

notebooklm CLI     →  ~/.notebooklm/storage_state.json (Playwright cookies)
```

---

## 7. ytcli Review: Keep Our Script

### Background

Artem Zhutov used the term "ytcli" in one screenshot caption in his Substack article. This prompted an investigation into whether we should adopt an existing YouTube CLI tool instead of building `search_youtube.py`.

### Findings

- **"ytcli" is not a real package.** Artem used it as informal shorthand. His `personal-os-skills` repo contains zero YouTube search scripts — source discovery is left entirely to the user.
- Packages actually named "ytcli" on GitHub are archived Rust/Python music player CLIs with no JSON output or research pipeline integration.
- **yt-dlp** (the most credible scraping alternative) has fragility problems: YouTube actively IP-bans scrapers, and yt-dlp requires frequent emergency upgrades to keep working. One yt-dlp advantage (view count in search results without a second API call) is negligible at our quota levels. Transcript extraction (yt-dlp's other advantage) is irrelevant since NotebookLM fetches its own transcripts from YouTube URLs.

### Our Data API v3 approach

- Stable, versioned Google API with OAuth authentication
- Correctly scoped: `youtube.readonly` permission only
- 10,000 units/day quota (~26 research sessions/day at typical usage)
- Already working — validated in `test_youtube_search.py`

### Verdict

**Keep `search_youtube.py` as designed. Do not adopt ytcli or yt-dlp.**

---

## Implementation Checklist

- [ ] Create `scripts/search_substack.py`
- [ ] Create `scripts/search_youtube.py`
- [ ] Create `scripts/generate_topic_hubs.py`
- [ ] Create `workflows/research.md`
- [ ] Add audio generate step to `workflows/research.md`
- [ ] Update `SKILL.md` (description, routing table, scripts table)
- [ ] Test: `search_youtube.py "test query" --max-results 5`
- [ ] Test: `search_substack.py "test query" --skip-categories`
- [ ] Test: `generate_topic_hubs.py --slug test-notebook`
- [ ] Verify `notebooklm audio generate` and `notebooklm generate flashcards` work with current CLI version
- [ ] Test: Full pipeline end-to-end on a small topic

### No changes needed to existing scripts
`import_sources.py`, `extract_passages.py`, and `resolve_citations.py` integrate cleanly as the downstream stage — they require no modifications.
