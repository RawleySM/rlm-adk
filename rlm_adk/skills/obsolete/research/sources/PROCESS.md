# Source Integration Process: Repeatable Methodology

This document records the process used to build the Substack research integration and generalizes it into a repeatable methodology for integrating any rich data source.

---

## Phase 1: Source Discovery and Library Selection

### Inputs
- Target data source name (e.g., "Substack")
- Language preference (e.g., Python)
- Desired capabilities (scraping, API access, auth, etc.)

### Activities

1. **Search purpose-built tool registries first** (fast, curated):
   - `npx skills find "<source> scraper"` (skills.sh ecosystem)
   - `npx skillfish search "<source>"` (skillfish ecosystem)
   - These return nothing most of the time but take seconds to check.

2. **Search GitHub broadly** via WebSearch:
   - Query: `"<source> API" OR "<source> scraper" language:<lang> stars:>10`
   - Categorize results: scraper/downloader/API-wrapper/SDK
   - Record: repo URL, stars, last commit date, language, install method, license

3. **Deep-evaluate top 2-3 candidates**:
   - Read README via direct fetch (DeepWiki indexing is unreliable for smaller repos)
   - Check: API surface completeness, auth support, maintenance activity, test coverage
   - Prefer: pip/npm-installable > git-clone, typed > untyped, actively maintained > archived

### Decision Point: Library Selection
- Criteria matrix: language fit, API coverage, star count, maintenance, install simplicity
- If no suitable library exists: evaluate building a thin client from scratch against the source's HTTP API

### Outputs
- Chosen library (name, repo URL, install command)
- Capability inventory (what the library can and cannot do)
- Known gaps to fill with direct API calls

---

## Phase 2: Integration Setup

### Inputs
- Chosen library from Phase 1
- Project directory structure conventions

### Activities

1. **Add dependency** to `pyproject.toml` (or equivalent package manifest)
2. **Create directory structure**: `<project>/skills/research/sources/<source>/`
3. **Create package files**: `__init__.py` at each level for import resolution
4. **Copy upstream README** into the source directory (reference material)
5. **Install**: `uv sync` / `pip install -e .` / equivalent

### Outputs
- Importable package at `<project>.skills.research.sources.<source>`
- Library installed and importable in the project venv

---

## Phase 3: Authentication Engineering

### Inputs
- Library installed from Phase 2
- Auth requirements from upstream docs

### Activities

1. **Write initial test script** to exercise the library's basic API
2. **Discover API surface discrepancies**: upstream README may not match actual code
   - Use `inspect.getsource()` to read actual class/function signatures
   - Fix test script based on real signatures, not documented ones
3. **Implement auth extraction** (method depends on source):

   **Branch A: Cookie-based auth** (Substack, Reddit old, etc.)
   - Attempt browser automation first (DevTools, JS injection) -- likely blocked by httpOnly flags
   - Fall back to reading browser's SQLite cookie DB directly
   - Use `browser-cookie3` (handles Chrome encryption variants across OS/versions)
   - Cache extracted cookies to `~/.config/<source>/cookies.json`

   **Branch B: API key auth** (OpenAI, Anthropic, etc.)
   - Read from environment variable or config file
   - No extraction pipeline needed

   **Branch C: OAuth flow** (Google, GitHub, etc.)
   - Implement token refresh cycle
   - Store refresh token securely, access token in memory

4. **Verify auth works**: run test script, confirm authenticated vs public access difference

### Decision Point: Auth Feasibility
- If cookie extraction fails after all fallbacks: degrade to public-only API
- If OAuth is too complex for the integration scope: check if API keys are available as alternative

### Outputs
- Working auth pipeline with fallback chain
- Test script that demonstrates authenticated access
- Cookie/token cache location documented

---

## Phase 4: Self-Healing Client Wrapper

### Inputs
- Working auth from Phase 3
- Upstream library API surface

### Activities

1. **Build client class** (`client.py`) that wraps the upstream library:
   - Lazy auth resolution (not at construction time)
   - Process-lifetime session caching
   - Graceful degradation (auth failure -> public API fallback)
2. **Implement retry/self-healing pipeline**:
   - For cookie auth: extract -> upgrade dependency -> retry -> cached fallback -> public fallback
   - For API keys: validate -> refresh -> re-read from env -> fail with clear error
3. **Expose high-level methods** that hide auth plumbing:
   - `get_subscriptions()`, `get_post_content()`, etc.
   - Auth injected transparently into upstream library calls

### Outputs
- `client.py` with self-healing auth and clean public API
- All upstream library complexity hidden behind simple method calls

---

## Phase 5: API Gap Discovery

### Inputs
- Working client from Phase 4
- Expected feature set from user requirements

### Activities

1. **Test against real data** and compare results to what the user sees in the UI
2. **Identify discrepancies**: public API may return incomplete data
   - Example: Substack's public profile API hid 8 of 94 subscriptions (paid subs hidden)
3. **Search for authenticated endpoints** that return complete data
   - Probe common REST patterns: `/api/v1/<resource>`, `/api/v1/me/<resource>`
   - Compare public vs authenticated responses
4. **Update client** to prefer authenticated endpoints where they return better data

### Decision Point: Gap Severity
- If gaps are minor (cosmetic, non-blocking): document and move on
- If gaps affect core functionality: find alternative endpoints or build workarounds

### Outputs
- Updated client with authenticated endpoint preferences
- Public vs authenticated API comparison table
- List of features that are truly unavailable via API

---

## Phase 6: Discovery Research (Parallel Agents)

### Inputs
- Working client from Phase 5
- Topic: "What discovery/exploration capabilities does this source offer?"

### Activities

Run two parallel research tracks:

**Agent 1: Strategy Research**
- Research discovery strategies for the source (blog posts, docs, community guides)
- Identify recommendation graphs, trending feeds, category systems
- Document third-party tools that augment discovery

**Agent 2: API Endpoint Probing**
- Brute-force probe common API endpoint patterns
- Test each with and without auth
- Record response shapes, pagination, rate limits
- Identify undocumented endpoints

**Merge findings**:
- Cross-reference Agent 1's strategies with Agent 2's discovered endpoints
- Build a multi-layer discovery pipeline (e.g., category seeding -> trending -> search -> graph walk)
- Document scoring/ranking signals available from the API

### Outputs
- Complete API endpoint reference (public vs authenticated)
- Multi-layer discovery pipeline design
- Scoring criteria for ranking discovered entities

---

## Phase 7: Documentation

### Inputs
- All outputs from Phases 1-6

### Activities

1. **Write comprehensive README** for the source integration:
   - Usage examples for every major feature
   - Auth setup instructions
   - Full API endpoint reference table
   - Discovery pipeline strategy
   - Limitations and caveats
2. **Iterative correction**: cross-check documentation against actual agent findings
3. **Include comparison tables**: public vs authenticated, available vs unavailable features

### Outputs
- `README.md` in the source directory
- Self-contained reference for anyone using or extending the integration

---

## Process Anti-Patterns (Lessons Learned)

1. **Do not trust upstream READMEs blindly.** Always verify API signatures with `inspect.getsource()` or by reading the actual library code. The Substack library's README examples had type errors.

2. **Do not attempt browser automation for httpOnly cookies.** DevTools shortcuts are blocked by extensions, and httpOnly cookies are inaccessible from JavaScript by design. Go straight to the browser's cookie database.

3. **Do not assume public APIs return complete data.** Substack's public profile API hid paid subscriptions. Always compare public API results against what the authenticated user sees in the UI.

4. **Do not skip the parallel research phase.** Strategy research (Agent 1) finds the "what to look for" while endpoint probing (Agent 2) finds the "what actually exists." Neither alone is sufficient.

5. **Chrome cookie encryption is non-trivial.** Do not attempt manual decryption (CBC/GCM key derivation varies by Chrome version and OS). Use `browser-cookie3` which handles all variants.
