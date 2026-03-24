# ADK Skills API Surface -- google-adk 1.27.3

Reference document for understanding what the upstream ADK provides for building
and consuming skills. All paths below are relative to
`.venv/lib/python3.12/site-packages/google/adk/`.

---

## 1. ADK Skill Class Hierarchy

```
pydantic.BaseModel
  |
  +-- google.adk.skills.models.Frontmatter       # L1: discovery metadata
  +-- google.adk.skills.models.Script             # wrapper for script source
  +-- google.adk.skills.models.Resources          # L3: references, assets, scripts
  +-- google.adk.skills.models.Skill              # L1+L2+L3 composite

ABC (abc.ABC)
  |
  +-- google.adk.tools.base_tool.BaseTool         # abstract tool base
  |     |
  |     +-- google.adk.tools.skill_toolset.ListSkillsTool         # tool: list_skills
  |     +-- google.adk.tools.skill_toolset.LoadSkillTool          # tool: load_skill
  |     +-- google.adk.tools.skill_toolset.LoadSkillResourceTool  # tool: load_skill_resource
  |     +-- google.adk.tools.skill_toolset.RunSkillScriptTool     # tool: run_skill_script
  |
  +-- google.adk.tools.base_toolset.BaseToolset   # abstract toolset base
        |
        +-- google.adk.tools.skill_toolset.SkillToolset  # the composite toolset

(helper, not exported)
  google.adk.tools.skill_toolset._SkillScriptCodeExecutor  # script execution helper
```

Every class in the `skill_toolset` module (ListSkillsTool, LoadSkillTool,
LoadSkillResourceTool, RunSkillScriptTool, SkillToolset) is decorated with
`@experimental(FeatureName.SKILL_TOOLSET)`. The feature flag
`SKILL_TOOLSET` is registered as `FeatureStage.EXPERIMENTAL, default_on=True`
in the feature registry, meaning it is active by default but emits a
UserWarning on first use.

---

## 2. Core Skill Data Models (`google.adk.skills.models`)

### 2.1 Frontmatter

```python
class Frontmatter(BaseModel):
    """L1 skill content: metadata parsed from SKILL.md for skill discovery."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str                          # kebab-case, validated: ^[a-z0-9]+(-[a-z0-9]+)*$, max 64 chars
    description: str                   # required, max 1024 chars
    license: str | None = None
    compatibility: str | None = None   # max 500 chars
    allowed_tools: str | None = Field(
        default=None,
        alias="allowed-tools",         # accepts YAML-friendly key
        serialization_alias="allowed-tools",
    )
    metadata: dict[str, Any] = {}      # arbitrary k/v; special key: "adk_additional_tools" (list[str])
```

**Validation rules:**
- `name` is NFKC-normalized, must match `^[a-z0-9]+(-[a-z0-9]+)*$`, max 64 chars.
- `description` must be non-empty, max 1024 chars.
- `compatibility` max 500 chars.
- `metadata["adk_additional_tools"]` must be a `list` if present.
- `extra="allow"` means unknown frontmatter keys are silently accepted.

### 2.2 Script

```python
class Script(BaseModel):
    src: str

    def __str__(self) -> str:
        return self.src
```

Thin wrapper around script source text.

### 2.3 Resources

```python
class Resources(BaseModel):
    """L3 skill content: additional instructions, assets, and scripts."""

    references: dict[str, str | bytes] = {}   # relative_path -> content
    assets: dict[str, str | bytes] = {}       # relative_path -> content
    scripts: dict[str, Script] = {}           # relative_path -> Script

    def get_reference(self, reference_id: str) -> str | bytes | None
    def get_asset(self, asset_id: str) -> str | bytes | None
    def get_script(self, script_id: str) -> Script | None
    def list_references(self) -> list[str]
    def list_assets(self) -> list[str]
    def list_scripts(self) -> list[str]
```

All accessor methods are simple `dict.get()` / `dict.keys()` wrappers. Binary
content (bytes) is supported for assets and references.

### 2.4 Skill

```python
class Skill(BaseModel):
    """Complete skill representation: L1 + L2 + L3."""

    frontmatter: Frontmatter           # L1 metadata
    instructions: str                  # L2 body from SKILL.md
    resources: Resources = Resources() # L3 references/assets/scripts

    @property
    def name(self) -> str:             # shortcut to frontmatter.name
    @property
    def description(self) -> str:      # shortcut to frontmatter.description
```

The three-level model:
- **L1 (Frontmatter):** Always visible to the agent via XML injection. Lightweight.
- **L2 (instructions):** Loaded on demand when the agent calls `load_skill`.
- **L3 (Resources):** Loaded on demand when the agent calls `load_skill_resource` or `run_skill_script`.

---

## 3. Skill Loading and Registration (`google.adk.skills._utils`)

### 3.1 Local filesystem loading

```python
def load_skill_from_dir(skill_dir: str | pathlib.Path) -> Skill
```

1. Resolves `skill_dir` to an absolute path.
2. Looks for `SKILL.md` or `skill.md` (case-insensitive fallback).
3. Splits content on `---` to extract YAML frontmatter and markdown body.
4. Parses frontmatter via `yaml.safe_load()`, validates with `Frontmatter.model_validate()`.
5. **Enforces name-directory match:** `skill_dir.name` must equal `frontmatter.name`.
6. Recursively loads `references/`, `assets/`, `scripts/` subdirectories.
7. Returns a fully populated `Skill` object.

```python
def list_skills_in_dir(skills_base_path: str | pathlib.Path) -> dict[str, Frontmatter]
```

Iterates subdirectories of `skills_base_path`, reads only frontmatter (L1) from each.
Skips invalid skills with a warning. Returns `{skill_id: Frontmatter}`.

### 3.2 GCS loading

```python
def load_skill_from_gcs_dir(bucket_name: str, skill_id: str, skills_base_path: str = "") -> Skill
def list_skills_in_gcs_dir(bucket_name: str, skills_base_path: str = "") -> dict[str, Frontmatter]
```

Mirrors the local filesystem API but reads from Google Cloud Storage using
`google.cloud.storage.Client`. Requires `google-cloud-storage` dependency.

### 3.3 Validation-only

```python
def _validate_skill_dir(skill_dir: str | pathlib.Path) -> list[str]
```

Returns a list of problem strings (empty = valid). Checks:
- Directory exists.
- `SKILL.md` found.
- Frontmatter parses without error.
- No unknown frontmatter keys (warns on extras).
- Name matches directory name.

```python
def _read_skill_properties(skill_dir: str | pathlib.Path) -> Frontmatter
```

Lightweight: reads only frontmatter, does not load instructions or resources.

### 3.4 SKILL.md format

```text
---
name: my-skill-name
description: What the skill does and when to use it.
license: Apache-2.0                     # optional
compatibility: gemini-2.0+             # optional, max 500 chars
allowed-tools: bash execute_code        # optional, space-delimited
metadata:                               # optional, arbitrary k/v
  adk_additional_tools:                 # special key: list of tool names
    - my_custom_tool
    - another_tool
---

# Markdown instructions (L2 body)

Step 1: ...
Step 2: ...
```

**Key constraint:** The directory containing SKILL.md must be named identically
to the `name` field in the frontmatter (enforced by `load_skill_from_dir`).

---

## 4. Skill Content Injection (`SkillToolset` and the LLM Request Pipeline)

### 4.1 The injection flow

When an LlmAgent has a `SkillToolset` in its `tools` list, the following
happens on every LLM request:

```
LlmAgent.tools = [SkillToolset(...), ...]
  |
  v
base_llm_flow._process_agent_tools(invocation_context, llm_request)
  |
  |-- for tool_union in agent.tools:
  |     |
  |     |-- if isinstance(tool_union, BaseToolset):
  |     |     await tool_union.process_llm_request(tool_context, llm_request)
  |     |       # ^^ THIS is where SkillToolset injects skill XML + default instruction
  |     |
  |     |-- tools = await _convert_tool_union_to_tools(tool_union, ...)
  |     |     # ^^ calls SkillToolset.get_tools_with_prefix() -> get_tools()
  |     |     # returns [ListSkillsTool, LoadSkillTool, LoadSkillResourceTool, RunSkillScriptTool]
  |     |     # plus any dynamically resolved additional tools
  |     |
  |     |-- for tool in tools:
  |           await tool.process_llm_request(tool_context, llm_request)
  |             # ^^ each tool registers its FunctionDeclaration
```

### 4.2 SkillToolset.process_llm_request

```python
async def process_llm_request(self, *, tool_context, llm_request) -> None:
    skills = self._list_skills()
    skills_xml = prompt.format_skills_as_xml(skills)
    instructions = []
    instructions.append(_DEFAULT_SKILL_SYSTEM_INSTRUCTION)
    instructions.append(skills_xml)
    llm_request.append_instructions(instructions)
```

This appends two things to the system instruction:
1. **Default skill system instruction** -- a multi-paragraph instruction block
   telling the model how to use skill tools.
2. **Skills XML** -- an `<available_skills>` block listing every registered
   skill's name and description.

### 4.3 Default skill system instruction

```text
You can use specialized 'skills' to help you with complex tasks. You MUST use
the skill tools to interact with these skills.

Skills are folders of instructions and resources that extend your capabilities
for specialized tasks. Each skill folder contains:
- **SKILL.md** (required): ...
- **references/** (Optional): ...
- **assets/** (Optional): ...
- **scripts/** (Optional): ...

This is very important:

1. If a skill seems relevant to the current user query, you MUST use the
   `load_skill` tool with `name="<SKILL_NAME>"` to read its full instructions
   before proceeding.
2. Once you have read the instructions, follow them exactly as documented
   before replying to the user...
3. The `load_skill_resource` tool is for viewing files within a skill's
   directory...
4. Use `run_skill_script` to run scripts from a skill's `scripts/` directory...
```

This instruction is considered internal/experimental. Accessing it via
`google.adk.tools.skill_toolset.DEFAULT_SKILL_SYSTEM_INSTRUCTION` emits a
UserWarning that content may change in minor/patch releases. Importing from
`google.adk.skills.DEFAULT_SKILL_SYSTEM_INSTRUCTION` or
`google.adk.skills.prompt.DEFAULT_SKILL_SYSTEM_INSTRUCTION` is deprecated and
redirects to the toolset module.

### 4.4 Skills XML format

```xml
<available_skills>
<skill>
<name>my-skill-name</name>
<description>What the skill does...</description>
</skill>
<skill>
<name>another-skill</name>
<description>Another skill description...</description>
</skill>
</available_skills>
```

Produced by `google.adk.skills.prompt.format_skills_as_xml()`. Accepts either
`list[Frontmatter]` or `list[Skill]` (both have `.name` and `.description`).
Values are HTML-escaped.

### 4.5 LlmRequest.append_instructions

```python
def append_instructions(self, instructions: list[str] | types.Content) -> list[types.Content]
```

For `list[str]`: joins with `\n\n` and concatenates to
`config.system_instruction` (string). If `system_instruction` is not yet set,
it becomes the new value. If it is a string, the new text is appended with
`\n\n` separator.

This means skill XML and default instructions end up as part of the model's
system instruction on every turn.

---

## 5. Skill Tools (registered as FunctionDeclarations)

### 5.1 ListSkillsTool

```
name: "list_skills"
description: "Lists all available skills with their names and descriptions."
parameters: {} (no params)
```

Returns the XML block from `format_skills_as_xml()`. Redundant with the
system instruction injection but available as an explicit tool call.

### 5.2 LoadSkillTool

```
name: "load_skill"
description: "Loads the SKILL.md instructions for a given skill."
parameters:
  name: string (required) -- The name of the skill to load.
```

Returns `{skill_name, instructions, frontmatter}`. Also records activation:

```python
state_key = f"_adk_activated_skill_{agent_name}"
activated_skills = list(tool_context.state.get(state_key, []))
if skill_name not in activated_skills:
    activated_skills.append(skill_name)
    tool_context.state[state_key] = activated_skills
```

This activation state is what triggers dynamic tool resolution (section 6).

### 5.3 LoadSkillResourceTool

```
name: "load_skill_resource"
description: "Loads a resource file (from references/, assets/, or scripts/) from within a skill."
parameters:
  skill_name: string (required)
  path: string (required) -- relative path starting with references/, assets/, or scripts/
```

For text content: returns `{skill_name, path, content}`.
For binary content: returns `{skill_name, path, status: "Binary file detected..."}` and
the `process_llm_request` override injects the binary data into the next LLM
request as inline_data.

### 5.4 RunSkillScriptTool

```
name: "run_skill_script"
description: "Executes a script from a skill's scripts/ directory."
parameters:
  skill_name: string (required)
  script_path: string (required) -- relative path (e.g., 'scripts/setup.py')
  args: object (optional) -- key-value pairs for script arguments
```

Requires a `BaseCodeExecutor` (either on the SkillToolset or the agent).
Builds a self-extracting Python wrapper that:
1. Materializes all skill files into a temp directory.
2. Runs `.py` scripts via `runpy.run_path()`.
3. Runs `.sh`/`.bash` scripts via `subprocess.run()` (with configurable timeout,
   default 300s).

Supported script types: `.py`, `.sh`, `.bash`. Returns structured result with
`{skill_name, script_path, stdout, stderr, status}`.

---

## 6. Dynamic Tool Resolution (adk_additional_tools)

This is the mechanism by which skills can bring additional tools into scope
only after they are activated.

### 6.1 Setup

```python
skill = Skill(
    frontmatter=Frontmatter(
        name="my-skill",
        description="...",
        metadata={
            "adk_additional_tools": ["my_custom_tool", "another_tool"]
        }
    ),
    instructions="...",
)

toolset = SkillToolset(
    skills=[skill],
    additional_tools=[my_custom_tool, another_tool_instance],  # ToolUnion list
)
```

The `additional_tools` parameter accepts `list[ToolUnion]` where
`ToolUnion = Union[Callable, BaseTool, BaseToolset]`. These are the candidates
that may be resolved later.

### 6.2 Resolution flow

```
SkillToolset.get_tools(readonly_context)
  |
  +-- self._tools = [ListSkillsTool, LoadSkillTool, LoadSkillResourceTool, RunSkillScriptTool]
  |
  +-- dynamic_tools = self._resolve_additional_tools_from_state(readonly_context)
  |     |
  |     +-- state_key = f"_adk_activated_skill_{agent_name}"
  |     +-- activated_skills = state.get(state_key, [])
  |     +-- for each activated skill:
  |     |     collect metadata["adk_additional_tools"] names
  |     +-- match names against self._provided_tools_by_name and self._provided_toolsets
  |     +-- return matched BaseTool instances (no duplicates, no name collisions)
  |
  +-- return self._tools + dynamic_tools
```

**Key points:**
- Tools are only resolved after `load_skill` has been called (which writes to state).
- Resolution happens on every `get_tools` call (which ADK calls on every LLM request turn).
- Callable additional_tools are wrapped in FunctionTool at SkillToolset init time.
- Toolsets in additional_tools are resolved via `get_tools_with_prefix()`.
- Name collisions with core skill tools are logged as errors and skipped.

---

## 7. Agent-Side Skill Parameters (LlmAgent)

Skills integrate with agents purely through the `tools` parameter:

```python
from google.adk.agents import LlmAgent
from google.adk.tools.skill_toolset import SkillToolset

agent = LlmAgent(
    name="my_agent",
    model="gemini-2.5-flash",
    instruction="You are a helpful assistant.",
    tools=[
        SkillToolset(skills=[skill1, skill2]),
        # ... other tools
    ],
)
```

### 7.1 Relevant LlmAgent parameters

| Parameter | Type | Relevance to Skills |
|---|---|---|
| `tools` | `list[ToolUnion]` | Where `SkillToolset` is placed. `ToolUnion = Union[Callable, BaseTool, BaseToolset]` |
| `include_contents` | `Literal['default', 'none']` | `'none'` means agent gets no prior history -- skill activation state still persists in session state but conversation context is lost |
| `instruction` | `str \| InstructionProvider` | The skill system instruction and XML are **appended** to whatever instruction is set here |
| `code_executor` | `BaseCodeExecutor \| None` | Fallback executor for `RunSkillScriptTool` if no executor is set on the SkillToolset |

### 7.2 How ToolUnion resolution works

In `llm_agent.py`:

```python
ToolUnion: TypeAlias = Union[Callable, BaseTool, BaseToolset]

async def _convert_tool_union_to_tools(tool_union, ctx, model, multiple_tools=False) -> list[BaseTool]:
    if isinstance(tool_union, BaseTool):
        return [tool_union]
    if callable(tool_union):
        return [FunctionTool(func=tool_union)]
    # At this point, tool_union must be a BaseToolset
    return await tool_union.get_tools_with_prefix(ctx)
```

So when `SkillToolset` is in the agent's tools list:
1. It is identified as a `BaseToolset`.
2. `_process_agent_tools` calls `toolset.process_llm_request()` first (injects XML).
3. Then calls `_convert_tool_union_to_tools()` which calls `get_tools_with_prefix()`.
4. The returned tools each have their `process_llm_request` called (registers FunctionDeclarations).

---

## 8. Experimental Feature Flag System

### 8.1 Feature name

`FeatureName.SKILL_TOOLSET = "SKILL_TOOLSET"`

### 8.2 Configuration

```python
FeatureName.SKILL_TOOLSET: FeatureConfig(
    FeatureStage.EXPERIMENTAL, default_on=True
)
```

### 8.3 How it works

The `@experimental(FeatureName.SKILL_TOOLSET)` decorator wraps `__init__` on
each skill tool class and the `SkillToolset` class. At construction time it
calls `is_feature_enabled(FeatureName.SKILL_TOOLSET)`. If disabled, a
`RuntimeError` is raised.

### 8.4 Enabling/disabling

Priority order (highest to lowest):
1. **Programmatic override:** `override_feature_enabled(FeatureName.SKILL_TOOLSET, True/False)`
2. **Environment variable:** `ADK_ENABLE_SKILL_TOOLSET=1` or `ADK_DISABLE_SKILL_TOOLSET=1`
3. **Registry default:** `default_on=True` (so skills are on by default)

### 8.5 Temporary override for testing

```python
from google.adk.features._feature_registry import temporary_feature_override, FeatureName

with temporary_feature_override(FeatureName.SKILL_TOOLSET, False):
    # SkillToolset construction would raise RuntimeError here
    ...
```

---

## 9. Callsite Hover Insights

The callsite hover JSON files confirm the following verified type signatures:

### From `skill_toolset_google-adk_callsite_hover.json`

- `format_skills_as_xml(skills: List[Frontmatter | Skill]) -> str`
- `BaseTool` is the base class (not a Pydantic model -- plain ABC)
- `ToolContext = Context` (type alias for the agent run context)

### From `catalog_google-adk_callsite_hover.json`

- `Skill(*, frontmatter: Frontmatter, instructions: str, resources: Resources = Resources())`
- `Frontmatter(*, name: str, description: str, license: str | None = None, compatibility: str | None = None, allowed_tools: str | None = None, metadata: dict[str, str] = {})`

### From `agent_google-adk_callsite_hover.json`

- `LlmAgent(*, name: str, ..., tools: list[ToolUnion] = list, ..., include_contents: Literal['default', 'none'] = 'default', ..., code_executor: BaseCodeExecutor | None = None, ...)`
- `App(*, name: str, root_agent: BaseAgent, plugins: list[BasePlugin] = list, ...)`

### From `polya_narrative_skill_google-adk_callsite_hover.json` and `repomix_skill_google-adk_callsite_hover.json`

Confirms the same Skill/Frontmatter/format_skills_as_xml signatures used in
the RLM-ADK codebase. The `format_skills_as_xml` accepts `List[Frontmatter]`
(not just `List[Skill]`), confirming that frontmatter-only discovery is the
intended L1 pattern.

---

## 10. Key Patterns for Implementors

### 10.1 Two approaches to skill delivery

**Approach A: SkillToolset (upstream, tool-based)**

The upstream `SkillToolset` treats skills as tool-mediated. The model must call
`load_skill` to get L2 instructions. Discovery happens via injected XML in the
system instruction. This is a multi-turn pattern: the model sees skill names,
decides one is relevant, calls `load_skill`, gets instructions, then follows
them.

```python
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.skills import load_skill_from_dir

toolset = SkillToolset(skills=[load_skill_from_dir("./skills/my-skill")])
agent = LlmAgent(name="agent", tools=[toolset])
```

**Approach B: Custom BaseTool (RLM-ADK obsolete pattern, prompt-injected)**

The RLM-ADK project previously implemented `RLMSkillToolset(BaseTool)` which
is a single tool (not a toolset) that:
- Injects L1 XML via `process_llm_request` (same as upstream).
- Exposes a single `load_skill` tool declaration.
- Tracks activation via `tool_context.state` keys.

This is simpler but lacks `list_skills`, `load_skill_resource`, and
`run_skill_script`.

### 10.2 Skill activation is stateful

Once `load_skill` is called, the skill name is recorded in session state under
`_adk_activated_skill_{agent_name}`. This persists across turns. Dynamic tools
specified in `adk_additional_tools` metadata only become available after
activation.

### 10.3 Name constraints

Skill names must be lowercase kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`), max 64
characters. The directory name must match the skill name exactly.

### 10.4 Binary content injection

`LoadSkillResourceTool` has a special `process_llm_request` override that
detects when the model viewed a binary file (images, PDFs, etc.) and injects
the binary data into the next LLM request as `inline_data` with appropriate
MIME type detection.

### 10.5 process_llm_request ordering

For a `BaseToolset`, the flow in `_process_agent_tools` is:
1. Call `toolset.process_llm_request()` (injects system instruction content).
2. Call `_convert_tool_union_to_tools()` to get individual tools.
3. Call each `tool.process_llm_request()` (registers FunctionDeclarations).

This means the toolset-level instruction injection happens **before** individual
tool declarations are registered.

### 10.6 Code executor resolution for scripts

`RunSkillScriptTool` resolves a code executor in this priority:
1. `SkillToolset._code_executor` (set via constructor `code_executor=` param).
2. `tool_context._invocation_context.agent.code_executor` (the agent's own executor).
3. If neither is set, returns an error.

---

## 11. Complete Public API Surface

### Imports from `google.adk.skills`

```python
from google.adk.skills import (
    Frontmatter,        # L1 metadata model
    Resources,          # L3 resources model
    Script,             # Script wrapper model
    Skill,              # L1+L2+L3 composite model
    load_skill_from_dir,     # Load skill from local directory
    load_skill_from_gcs_dir, # Load skill from GCS
    list_skills_in_dir,      # List skills (frontmatter only) from local dir
    list_skills_in_gcs_dir,  # List skills (frontmatter only) from GCS
)
```

### Imports from `google.adk.skills.prompt`

```python
from google.adk.skills.prompt import format_skills_as_xml
```

### Imports from `google.adk.tools.skill_toolset`

```python
from google.adk.tools.skill_toolset import (
    SkillToolset,            # The main toolset (BaseToolset subclass)
    ListSkillsTool,          # Individual tool classes (rarely needed directly)
    LoadSkillTool,
    LoadSkillResourceTool,
    RunSkillScriptTool,
    # DEFAULT_SKILL_SYSTEM_INSTRUCTION  # via __getattr__, emits warning
)
```

### Imports from `google.adk.features`

```python
from google.adk.features import (
    FeatureName,                  # FeatureName.SKILL_TOOLSET
    is_feature_enabled,           # Check if skills are enabled
    override_feature_enabled,     # Programmatically enable/disable
)
```

---

## 12. Summary

ADK 1.27.3 provides a complete, experimental skill system with three layers:

1. **Data models** (`google.adk.skills.models`): `Frontmatter`, `Skill`,
   `Resources`, `Script` -- Pydantic models for defining skills with L1/L2/L3
   content levels.

2. **Loading utilities** (`google.adk.skills._utils`): `load_skill_from_dir`,
   `list_skills_in_dir`, plus GCS variants -- load skills from filesystem or
   cloud storage.

3. **SkillToolset** (`google.adk.tools.skill_toolset`): A `BaseToolset`
   subclass that:
   - Injects L1 discovery XML into the system instruction on every LLM request.
   - Provides four tools: `list_skills`, `load_skill`, `load_skill_resource`,
     `run_skill_script`.
   - Supports dynamic tool resolution via `adk_additional_tools` metadata after
     skill activation.
   - Supports script execution via a code executor.

The skill system is designed around a **lazy loading pattern**: L1 metadata is
always visible (via XML injection), L2 instructions are loaded on demand (via
`load_skill` tool call), and L3 resources are loaded on demand (via
`load_skill_resource` or `run_skill_script` tool calls). This minimizes context
window usage while keeping all skills discoverable.

For agent developers, the integration point is simple: construct a
`SkillToolset` with a list of `Skill` objects and add it to the agent's `tools`
list. The toolset handles all system instruction injection, tool registration,
state tracking, and dynamic tool resolution automatically.
