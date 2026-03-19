# NotebookLM Skill Enhancement Proposal

**Date:** 2026-03-19
**Source:** Code architect review of pipeline execution trace

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

## 4. Proposed: `workflows/research.md`

### File path
`~/.claude/skills/notebooklm/workflows/research.md`

### Pipeline phases

```
Phase 1: Source Discovery
  Step 1: search_youtube.py → /tmp/youtube-candidates.json
  Step 2: search_substack.py → /tmp/substack-candidates.json

Phase 2: Notebook Creation + Source Import
  Step 3: notebooklm create "{topic}"
  Step 4: Auto-add YouTube sources (--auto-add flag)
  Step 5: Add Substack sources (loop over JSON)
  Step 6: notebooklm source list --json → /tmp/notebooklm-sources.json

Phase 3: Vault Import
  Step 7: mkdir vault structure
  Step 8: import_sources.py (existing)
  Step 9: Create dashboard from template

Phase 4: Research Questions
  Step 10: notebooklm ask --new --json (2-6 questions)
  Step 11: extract_passages.py (existing)
  Step 12: resolve_citations.py (existing)

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

## Implementation Checklist

- [ ] Create `scripts/search_substack.py`
- [ ] Create `scripts/search_youtube.py`
- [ ] Create `workflows/research.md`
- [ ] Update `SKILL.md` (description, routing table, scripts table)
- [ ] Test: `search_youtube.py "test query" --max-results 5`
- [ ] Test: `search_substack.py "test query" --skip-categories`
- [ ] Test: Full pipeline end-to-end on a small topic

### No changes needed to existing scripts
`import_sources.py`, `extract_passages.py`, and `resolve_citations.py` integrate cleanly as the downstream stage — they require no modifications.
