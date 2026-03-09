Here’s the second pass, ranked for **large-scale AI dataset collection / RAG ingestion**, with maintenance and practical pipeline value weighted more heavily than raw stars.

## Ranked matrix

| Rank  | Repo                            |   Language | Adoption / maintenance                                                     | Extraction approach                   | Auth / paid support                                                        | Output fit for AI pipelines                                                 | My take                                                  |
| ----- | ------------------------------- | ---------: | -------------------------------------------------------------------------- | ------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------- |
| **1** | `jakub-k-slys/substack-api`     | TypeScript | **54 stars**, active issues, docs, latest release **Mar 3, 2026**          | Unofficial internal API client        | Supports authenticated workflows and broader entity access                 | Strong for structured ingestion, analytics, comments/profiles/posts         | **Best overall SDK** ([GitHub][1])                       |
| **2** | `NHagar/substack_api`           |     Python | Mature, widely referenced; used as a base by other repos                   | Unofficial API wrapper                | Can access paywalled content you already have rights to via auth           | Strong Python base for notebooks, ETL, metadata-first ingestion             | **Best Python foundation** ([GitHub][2])                 |
| **3** | `alexferrari88/sbstck-dl`       |         Go | **205 stars**, **26 forks**, recent release activity incl. **Sep 3, 2025** | Bulk downloader / archival CLI        | Has private-newsletter-related support and issues around private downloads | Excellent for corpus building, Markdown/HTML/text archives, resumable pulls | **Best bulk archiver** ([GitHub][3])                     |
| **4** | `ma2za/python-substack`         |     Python | **10 releases**, latest release **Dec 21, 2025**                           | Python client with login-based access | Uses credentials / env-based auth                                          | Good if you want Python and more direct authenticated usage                 | **Promising Python alternative** ([GitHub][4])           |
| **5** | `timf34/Substack2Markdown`      |     Python | **394 stars**, **145 forks**, latest release **Aug 10, 2024**              | Export / convert to Markdown          | Supports free and premium posts                                            | Very strong for Markdown-first corpora and local knowledge bases            | **Best Markdown exporter, but less fresh** ([GitHub][5]) |
| **6** | `DominiquePaul/scrape-substack` |     Python | **3 stars**, no releases                                                   | API-based scraper extending NHagar    | Adds retries/backoff; supports Notes / likes / reads metadata              | Interesting for research metadata, but weak adoption                        | **Niche, not a default pick** ([GitHub][6])              |
| **7** | `benclmnt/substackscraper`      |         Go | Small repo, limited signals                                                | CLI on undocumented v1 endpoints      | Cookie-based paid/public-preview handling                                  | Fine for simple Markdown pulls, not ideal as a core dependency              | **Useful but fragile** ([GitHub][7])                     |

## What changed from the first pass

The biggest correction is that I would now put **`ma2za/python-substack` above `Substack2Markdown` and `scrape-substack`** for most serious engineering work, because it shows much better recent maintenance than those repos. `Substack2Markdown` is still strong, but its last release being in August 2024 makes it more of an exporter you adopt cautiously than a living SDK. ([GitHub][4])

## Best by use case

If you want a **true ingestion SDK**, use **`jakub-k-slys/substack-api`** first if TypeScript is acceptable. It is the clearest sign of a modern, maintained client rather than a one-off scraper, and it exposes richer Substack objects like comments and profiles. ([GitHub][8])

If you want **Python-first ETL or notebook work**, start with **`NHagar/substack_api`** and evaluate **`ma2za/python-substack`** as a second option. `NHagar` has stronger reputation and downstream reuse; `ma2za` has stronger recent release cadence from the evidence I found. ([GitHub][2])

If you want **large local corpora for RAG**, **`sbstck-dl`** is the best fit. The combination of archive-oriented CLI design, multiple output formats, release activity, and file/image handling makes it the most practical tool for building a document store you can chunk and embed. ([GitHub][9])

If you specifically want **Markdown output for Obsidian / plain-text corpora**, **`Substack2Markdown`** is still very attractive because of its adoption and export ergonomics. I just would not treat it as the canonical foundation for a long-lived ingestion platform unless you verify it against current Substack behavior yourself. ([GitHub][5])

## RAG-readiness scorecard

I’d score them like this for your kind of workflow:

* **`jakub-k-slys/substack-api`**: 9/10
* **`NHagar/substack_api`**: 8.5/10
* **`sbstck-dl`**: 8.5/10
* **`ma2za/python-substack`**: 8/10
* **`Substack2Markdown`**: 7.5/10
* **`scrape-substack`**: 6/10
* **`substackscraper`**: 5.5/10

That scoring is my judgment, based on the visible signals above: release recency, feature depth, auth support, output usefulness, and whether the repo looks like an SDK versus a brittle scraper. The scores themselves are inference, not repo-published metrics. Supported facts are cited above. ([GitHub][1])

## My blunt recommendation

For a serious pipeline, I would not bet on “mystery scrapers.” I would choose one of these two paths:

**Path A: structured-first**

* `jakub-k-slys/substack-api` or `NHagar/substack_api`
* save raw JSON
* normalize to your schema
* render Markdown/text downstream only as a derived artifact

**Path B: archive-first**

* `sbstck-dl`
* keep HTML + Markdown + attachments
* chunk from Markdown/text
* retain raw HTML for reprocessing later

For your style of agentic pipeline, **Path A is cleaner** if you want metadata-rich retrieval and incremental sync. **Path B is better** if you care about preserving formatting fidelity and attachments for later re-parsing. ([GitHub][8])

## Important correction on GraphQL

I still do **not** have evidence that the best public Substack tools are mainly GraphQL-based. The credible repos and writeups I found point much more toward **reverse-engineered internal web/API traffic and undocumented endpoints** than a clearly publicized GraphQL-heavy tool ecosystem. ([iam.slys.dev][10])

Next, I can turn this into a **decision table specifically for your local-first prototype**: SQLite + raw JSON + Markdown + chunking + vector store, with a recommended repo and folder layout.

[1]: https://github.com/jakub-k-slys/substack-api/releases?utm_source=chatgpt.com "Releases · jakub-k-slys/substack-api"
[2]: https://github.com/NHagar/substack_api?utm_source=chatgpt.com "NHagar/substack_api: Unofficial wrapper for Substack's API"
[3]: https://github.com/alexferrari88?utm_source=chatgpt.com "Alex Ferrari alexferrari88"
[4]: https://github.com/ma2za/python-substack?utm_source=chatgpt.com "ma2za/python-substack"
[5]: https://github.com/timf34/Substack2Markdown?utm_source=chatgpt.com "Substack2Markdown"
[6]: https://github.com/DominiquePaul/scrape-substack?utm_source=chatgpt.com "A python package to easily scrape substack"
[7]: https://github.com/benclmnt/substackscraper?utm_source=chatgpt.com "benclmnt/substackscraper: A scraper for Substack articles"
[8]: https://github.com/jakub-k-slys/substack-api?utm_source=chatgpt.com "jakub-k-slys/substack-api"
[9]: https://github.com/alexferrari88/sbstck-dl/releases?utm_source=chatgpt.com "Releases · alexferrari88/sbstck-dl"
[10]: https://iam.slys.dev/p/no-official-api-no-problem-how-i?utm_source=chatgpt.com "No official API⁉️ No problem‼️ How I reverse-engineered ..."
