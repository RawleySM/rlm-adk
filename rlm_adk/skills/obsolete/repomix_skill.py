"""ADK Skill definition for the repomix REPL helpers.

Defines ``REPOMIX_SKILL`` using ``google.adk.skills.models.Skill`` and
provides ``build_skill_instruction_block()`` which returns the XML discovery
block + full usage instructions to append to the reasoning agent's
``static_instruction``.
"""

from __future__ import annotations

import textwrap

from google.adk.skills.models import Frontmatter, Skill
from google.adk.skills.prompt import format_skills_as_xml

REPOMIX_SKILL = Skill(
    frontmatter=Frontmatter(
        name="repomix-repl-helpers",
        description=(
            "Pre-built REPL functions for packing, probing, and sharding "
            "git repositories using repomix-python.  Call probe_repo(), "
            "pack_repo(), or shard_repo() directly in ```repl``` blocks "
            "with zero imports."
        ),
    ),
    instructions=textwrap.dedent("""\
## repomix-repl-helpers — Pre-built REPL Functions

Three helper functions are auto-loaded in the REPL.  Use them directly —
no imports needed.

### probe_repo(source, calculate_tokens=True) -> ProbeResult
Quick stats without returning the full packed content.
- `source`: local directory path **or** remote git URL
- Returns: `ProbeResult` with `.total_files`, `.total_chars`, `.total_tokens`,
  `.file_tree`, `.file_char_counts`, `.file_token_counts`

```repl
info = probe_repo("https://github.com/org/repo")
print(info)
print(f"Tokens: {info.total_tokens}")
```

### pack_repo(source, calculate_tokens=True) -> str
Pack the entire repo into a single XML string.  Best for small repos
(<125K tokens).
- `source`: local directory path **or** remote git URL
- Returns: XML string with `<file>`, `<path>`, `<content>` tags

```repl
xml = pack_repo("/path/to/local/repo")
analysis = llm_query(f"Analyze this repo:\\n\\n{xml}")
print(analysis)
```

### shard_repo(source, max_bytes_per_shard=512000, calculate_tokens=True) -> ShardResult
Pack + split into directory-aware chunks.  Best for large repos.
- `source`: local directory path **or** remote git URL
- `max_bytes_per_shard`: max bytes per chunk (default ~500KB)
- Returns: `ShardResult` with `.chunks` (list[str]), `.total_files`,
  `.total_chars`, `.total_tokens`

```repl
shards = shard_repo("https://github.com/org/repo")
print(shards)  # e.g. ShardResult(shards=4, files=120, ...)
prompts = [f"Analyze this section:\\n\\n{chunk}" for chunk in shards.chunks]
analyses = llm_query_batched(prompts)
combined = "\\n---\\n".join(f"Part {i+1}:\\n{a}" for i, a in enumerate(analyses))
final = llm_query(f"Synthesize:\\n\\n{combined}")
print(final)
```

### Recommended Strategy
1. `probe_repo(source)` to check token count
2. If `< 125K` tokens: `pack_repo(source)` + single `llm_query`
3. If `>= 125K` tokens: `shard_repo(source)` + `llm_query_batched` + aggregate
"""),
)


def build_skill_instruction_block() -> str:
    """Return the skill discovery XML + full instructions for prompt injection.

    Appended to ``static_instruction`` in :func:`create_reasoning_agent`.
    """
    discovery_xml = format_skills_as_xml([REPOMIX_SKILL.frontmatter])
    return f"\n{discovery_xml}\n{REPOMIX_SKILL.instructions}"
