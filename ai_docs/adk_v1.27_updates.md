# ADK Python v1.27.0 Release Notes

**Release Date:** March 12, 2026
**Commit:** `501c827`
**Source:** https://github.com/google/adk-python/releases/tag/v1.27.0

---

## Features

### Core
- Introduced A2A request interceptors in RemoteA2aAgent
- Added UiWidget to EventActions for experimental UI Widgets feature
- **Auth:** Pluggable auth integration support via AuthProviderRegistry in CredentialManager
- **Support for all `types.SchemaUnion` as output_schema in LLM Agent**
- Durable runtime support
- **Runners:** Pass GetSessionConfig through Runner to session service

### Models
- PDF document support in Anthropic LLM
- Streaming support for Anthropic models (closes #3250)
- Output schema with tools for LiteLlm models (closes #3969)
- Preserve thought_signature in LiteLLM tool calls (closes #4650)

### Web
- Updated human-in-the-loop: developers can respond to long-running functions directly in chat
- Render artifacts when resuming
- Light mode style fixes
- Token level streaming fixes

### Observability
- **Telemetry:** New `gen_ai.agent.version` span attribute
- **OTEL:** Added `gen_ai.tool.definitions` to experimental semconv
- **OTEL:** Experimental semantic convention and `gen_ai.client.inference.operation.details` event
- Missing token usage span attributes during model usage
- Tool execution error code capture in OpenTelemetry spans

### Tools
- Warning when accessing DEFAULT_SKILL_SYSTEM_INSTRUCTION
- `preserve_property_names` option for OpenAPIToolset
- GCS filesystem support for Skills (text and PDF formats)
- `list_skills_in_dir` utility function
- MCP App UI widgets support in MCPTool
- Dataplex Catalog search tool for BigQuery ADK
- **RunSkillScriptTool in SkillToolset**
- **ADK tools support in SkillToolset**
- BigQuery job labels limiting with reserved internal prefixes
- Bigtable execute_sql param support
- **Bigtable:** Cluster metadata tools
- GkeCodeExecutor execute-type param
- **Skill: BashTool addition**
- **Toolsets support in SkillToolset additional_tools field**

### Optimization
- `adk optimize` command
- LocalEvalService optimization infra interface
- GEPA root agent prompt optimizer

### Integrations
- Enhanced BigQuery plugin schema upgrades and error reporting
- BQ plugin enhancements: fork safety, auto views, trace continuity
- BigQuery Agent Analytics Plugin conflict error handling
- ADK CLI command tracking headers to Agent Engine

### A2A
- New A2aAgentExecutor implementation and A2A-ADK conversion
- New RemoteA2aAgent implementation and A2A-ADK conversion

---

## Bug Fixes

- Artifact services now accept dictionary representations of types.Part (closes #2886)
- ComputerUse tool response image data decoding to image blobs
- LiteLLM reasoning extraction expanded to include 'reasoning' field (closes #3694)
- Non-agent directory filtering in list_agents()
- Type Error fix by initializing user_content as Content object
- LiteLLM response length finish reason handling (closes #4482)
- SaveFilesAsArtifactsPlugin artifact delta writing for ADK Web UI
- Made invocation_context optional in convert_event_to_a2a_message
- Row-level locking optimization in append_event (closes #4655)
- Thought_signature preservation in FunctionCall GenAI/A2A conversions
- SSE event splitting prevention with artifactDelta for function resume (closes #4487)
- File name propagation during A2A to/from Genai Part conversion
- Thought propagation from A2A TextPart metadata to GenAI Part
- DEFAULT_SKILL_SYSTEM_INSTRUCTION re-export to avoid breaking changes
- Type string update refactoring in Anthropic tool param conversion
- **Simulation:** NoneType generated_content handling
- **EventCompaction storage/retrieval via custom_metadata in Vertex AISessionService (closes #3465)**
- **Before/after tool callbacks in Live mode (closes #4704)**
- **Temp-scoped state visibility to subsequent agents in same invocation**
- **Tools:** JSON Schema boolean schema handling in Gemini conversion
- A2A EXPERIMENTAL warning typo correction
- agent_engine_sandbox_code_executor update in ADK
- Bigtable query tools async function conversion
- LiteLLM test UsageMetadataChunk expectations (closes #4680)
- Toolbox server and SDK package version updates
- Session validation before streaming instead of eager runner advancement

---

## Code Refactoring

- Reusable function extraction from hitl and auth preprocessor
- Optimization data types base class and TypeVar renaming

---

## RLM-ADK Relevance Tags

**High relevance (starred above):**
- `types.SchemaUnion` as output_schema — directly impacts dispatch.py structured output, worker_retry.py, agent.py
- BashTool in Skills — enables headless CLI/coding agent invocation from REPL
- RunSkillScriptTool / SkillToolset enhancements — new skill execution patterns
- Before/after tool callbacks in Live mode — affects callback architecture
- Temp-scoped state visibility fix — affects AR-CRIT-001 dispatch state patterns
- Row-level locking in append_event — affects session service robustness
- EventCompaction via custom_metadata — affects session service efficiency
- OTEL tool error capture — enhances observability plugins
