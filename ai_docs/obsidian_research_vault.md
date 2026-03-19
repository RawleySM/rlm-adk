# Claude Code + NotebookLM + Obsidian: The Research Stack Nobody's Using

**Author:** Artem Zhutov
**Date:** February 24, 2026
**Source:** [artemxtech.substack.com](https://artemxtech.substack.com/p/notebooklm-has-a-knowledge-graph)
**Repo:** [github.com/ArtemXTech/personal-os-skills/tree/main/skills/notebooklm](https://github.com/ArtemXTech/personal-os-skills/tree/main/skills/notebooklm)

---

## The Problem

NotebookLM supports up to 300 sources but traditionally requires manual browser-based input. Research gets trapped inside NotebookLM — you copy-paste answers into your notes, lose the citations, and the research stays in a browser window you'll never reopen. There's no persistent connection to your note system.

## The Solution

A Claude Code skill that automates the entire research pipeline with three terminal commands:

1. **Search YouTube** for relevant videos
2. **Add videos as NotebookLM sources** automatically
3. **Query sources** and receive cited answers

Key workflow command:

```bash
notebooklm ask --new --json "What are the gaps in these videos?"
```

Answers return as structured JSON with markers tracing claims to specific sources and passages.

## Citation Accuracy

Testing revealed:

| Match Quality | Rate |
|---------------|------|
| Strong match  | ~60% |
| Partial match | ~31% |
| Weak match    | 10-15% |

## Knowledge Graph Integration (Obsidian)

Research lands in Obsidian as linked files:

- **Each source** becomes a markdown file with YouTube thumbnails
- **Topics** act as hub files
- **Citations** become wikilinks connecting Q&A to source passages
- Relationships visible in Obsidian's **graph view**

This creates a browsable, interconnected knowledge graph from NotebookLM research — citations are no longer throwaway text but navigable links between ideas and their origins.

## Additional Capabilities

- **Audio overviews:** Generates podcast-style discussions of sources
- **Flashcards:** Creates study cards from source material
- **Daily note chat:** Query 282+ personal journal entries with citations
- **Academic research:** Integrates arXiv papers with cited analysis

## Setup

Requires:
- Claude Code
- An Obsidian vault
- A Google account

Setup time: ~15 minutes.

## Relevance to RLM-ADK

Key takeaways for our research skill architecture:

1. **Citation-first design** — structured JSON with source markers is the right output format for research tools; matches our substack skill's inline-reference approach
2. **Knowledge graph as output** — writing interconnected markdown files (not flat reports) preserves research provenance and enables downstream discovery
3. **NotebookLM as a source layer** — its 300-source capacity + citation engine could serve as an intermediate aggregation step before RLM processing
4. **Terminal-native workflow** — three commands to go from search → sources → cited answers is the UX bar for research skills
