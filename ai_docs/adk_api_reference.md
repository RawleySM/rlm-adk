# Google ADK (Agent Development Kit) - Python API Reference

> Compact reference for `google-adk`. Source: `src/google/adk/`.
> All imports assume `google.adk` as the top-level package.

---

## google.adk.agents

```python
from google.adk.agents import (
    BaseAgent, LlmAgent, Agent,  # Agent is alias for LlmAgent
    SequentialAgent, ParallelAgent, LoopAgent,
    RunConfig, InvocationContext,
    LiveRequest, LiveRequestQueue,
)
```

### BaseAgent

Base class for all agents. Pydantic `BaseModel`.

```python
class BaseAgent(BaseModel):
    name: str                      # Must be a valid Python identifier, cannot be "user"
    description: str = ''          # One-line description for agent delegation
    sub_agents: list[BaseAgent] = []
    parent_agent: Optional[BaseAgent] = None  # Set automatically, do not pass

    before_agent_callback: Optional[BeforeAgentCallback] = None
    after_agent_callback: Optional[AfterAgentCallback] = None
```

**Callback signatures:**
```python
# BeforeAgentCallback / AfterAgentCallback can be a single callable or list:
def my_callback(callback_context: CallbackContext) -> Optional[types.Content]:
    ...
# async version also supported
```

**Key methods:**
- `find_agent(name: str) -> Optional[BaseAgent]` -- Find agent by name in tree
- `find_sub_agent(name: str) -> Optional[BaseAgent]` -- Find in descendants only
- `clone(update: Mapping[str, Any] | None = None) -> BaseAgent` -- Deep copy agent tree
- `root_agent -> BaseAgent` -- Property, returns root of tree

---

### LlmAgent (alias: Agent)

LLM-powered agent. Extends `BaseAgent`.

```python
class LlmAgent(BaseAgent):
    model: Union[str, BaseLlm] = ''
    # When empty, inherits from parent or uses default ('gemini-2.5-flash')

    instruction: Union[str, InstructionProvider] = ''
    # Supports {variable_name} placeholders resolved from session state.
    # Can be a string or a callable: (ReadonlyContext) -> str

    global_instruction: Union[str, InstructionProvider] = ''
    # DEPRECATED. Use GlobalInstructionPlugin instead. Only root agent's takes effect.

    static_instruction: Optional[types.ContentUnion] = None
    # Static content sent as system instruction (for context caching optimization)

    tools: list[ToolUnion] = []
    # ToolUnion = Union[Callable, BaseTool, BaseToolset]
    # Plain functions are auto-wrapped in FunctionTool

    generate_content_config: Optional[types.GenerateContentConfig] = None
    # Adjust temperature, safety_settings, etc. Do NOT set tools/system_instruction here.

    # Agent transfer controls
    disallow_transfer_to_parent: bool = False
    disallow_transfer_to_peers: bool = False

    include_contents: Literal['default', 'none'] = 'default'
    # 'none' = agent receives no prior conversation history

    # Input/Output
    input_schema: Optional[type[BaseModel]] = None   # Schema when agent used as tool
    output_schema: Optional[type[BaseModel]] = None   # Structured output (disables tools)
    output_key: Optional[str] = None                  # Save output to session state key

    # Advanced
    planner: Optional[BasePlanner] = None
    code_executor: Optional[BaseCodeExecutor] = None

    # Callbacks
    before_model_callback: Optional[BeforeModelCallback] = None
    after_model_callback: Optional[AfterModelCallback] = None
    on_model_error_callback: Optional[OnModelErrorCallback] = None
    before_tool_callback: Optional[BeforeToolCallback] = None
    after_tool_callback: Optional[AfterToolCallback] = None
    on_tool_error_callback: Optional[OnToolErrorCallback] = None
```

**Class methods:**
- `LlmAgent.set_default_model(model: Union[str, BaseLlm]) -> None` -- Override global default model

**Callback type signatures:**
```python
# BeforeModelCallback
def before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]: ...

# AfterModelCallback
def after_model(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]: ...

# BeforeToolCallback
def before_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> Optional[dict]: ...

# AfterToolCallback
def after_tool(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict) -> Optional[dict]: ...
```

---

### SequentialAgent

Runs sub-agents one after another in order.

```python
class SequentialAgent(BaseAgent):
    # Inherits: name, description, sub_agents, before/after_agent_callback
    pass  # No additional fields
```

---

### ParallelAgent

Runs sub-agents concurrently with isolated branches.

```python
class ParallelAgent(BaseAgent):
    # Inherits: name, description, sub_agents, before/after_agent_callback
    pass  # No additional fields
```

---

### LoopAgent

Runs sub-agents in a loop until `exit_loop` is called or max_iterations reached.

```python
class LoopAgent(BaseAgent):
    max_iterations: Optional[int] = None
    # None = loop indefinitely until a sub-agent escalates (calls exit_loop)
```

---

### RunConfig

Runtime configuration passed to `runner.run()` / `runner.run_async()`.

```python
from google.adk.agents import RunConfig
from google.adk.agents.run_config import StreamingMode

class RunConfig(BaseModel):
    streaming_mode: StreamingMode = StreamingMode.NONE
    # StreamingMode.NONE | StreamingMode.SSE | StreamingMode.BIDI

    max_llm_calls: int = 500
    # Limit on total LLM calls per run. <= 0 means unbounded.

    speech_config: Optional[types.SpeechConfig] = None
    response_modalities: Optional[list[str]] = None
    support_cfc: bool = False   # Compositional Function Calling (experimental)
    save_live_blob: bool = False
    custom_metadata: Optional[dict[str, Any]] = None
```

---

## google.adk.apps

```python
from google.adk.apps import App, ResumabilityConfig
```

### App

Top-level container for an agentic application.

```python
class App(BaseModel):
    name: str                    # Must be a valid Python identifier
    root_agent: BaseAgent        # The root agent (one per app)
    plugins: list[BasePlugin] = []
    events_compaction_config: Optional[EventsCompactionConfig] = None
    context_cache_config: Optional[ContextCacheConfig] = None
    resumability_config: Optional[ResumabilityConfig] = None
```

### ResumabilityConfig

```python
class ResumabilityConfig(BaseModel):
    is_resumable: bool = False
```

---

## google.adk.runners

```python
from google.adk.runners import Runner, InMemoryRunner
```

### Runner

Manages agent execution within sessions.

```python
class Runner:
    def __init__(
        self,
        *,
        app: Optional[App] = None,          # Recommended: provide App
        app_name: Optional[str] = None,      # Required if no app
        agent: Optional[BaseAgent] = None,   # Required if no app
        artifact_service: Optional[BaseArtifactService] = None,
        session_service: BaseSessionService, # Required
        memory_service: Optional[BaseMemoryService] = None,
        credential_service: Optional[BaseCredentialService] = None,
        plugins: Optional[list[BasePlugin]] = None,  # DEPRECATED, use App
        plugin_close_timeout: float = 5.0,
        auto_create_session: bool = False,
    ): ...
```

**Key methods:**
```python
# Synchronous (for local testing only)
def run(
    self, *, user_id: str, session_id: str,
    new_message: types.Content,
    run_config: Optional[RunConfig] = None,
) -> Generator[Event, None, None]: ...

# Async (recommended for production)
async def run_async(
    self, *, user_id: str, session_id: str,
    new_message: Optional[types.Content] = None,
    invocation_id: Optional[str] = None,
    state_delta: Optional[dict[str, Any]] = None,
    run_config: Optional[RunConfig] = None,
) -> AsyncGenerator[Event, None]: ...

# Live mode (audio/video, experimental)
async def run_live(
    self, *, user_id: Optional[str] = None, session_id: Optional[str] = None,
    live_request_queue: LiveRequestQueue,
    run_config: Optional[RunConfig] = None,
) -> AsyncGenerator[Event, None]: ...

# Debug helper for quick testing
async def run_debug(
    self, user_messages: str | list[str], *,
    user_id: str = 'debug_user_id',
    session_id: str = 'debug_session_id',
    run_config: RunConfig | None = None,
    quiet: bool = False, verbose: bool = False,
) -> list[Event]: ...

# Cleanup
async def close(self): ...

# Async context manager support
async with runner:
    ...
```

### InMemoryRunner

Convenience runner with in-memory services (for testing/development).

```python
class InMemoryRunner(Runner):
    def __init__(
        self,
        agent: Optional[BaseAgent] = None,
        *,
        app_name: Optional[str] = None,     # Defaults to 'InMemoryRunner'
        plugins: Optional[list[BasePlugin]] = None,
        app: Optional[App] = None,
        plugin_close_timeout: float = 5.0,
    ): ...
```

Uses `InMemoryArtifactService`, `InMemorySessionService`, `InMemoryMemoryService` automatically.

---

## google.adk.events

```python
from google.adk.events import Event, EventActions
```

### Event

Represents a conversation event. Extends `LlmResponse`.

```python
class Event(LlmResponse):
    # From LlmResponse:
    content: Optional[types.Content] = None
    partial: Optional[bool] = None
    turn_complete: Optional[bool] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    usage_metadata: Optional[types.GenerateContentResponseUsageMetadata] = None
    grounding_metadata: Optional[types.GroundingMetadata] = None
    custom_metadata: Optional[dict[str, Any]] = None

    # Event-specific:
    invocation_id: str = ''
    author: str                    # 'user' or agent name
    actions: EventActions = EventActions()
    branch: Optional[str] = None
    long_running_tool_ids: Optional[set[str]] = None
    id: str = ''                   # Auto-generated UUID
    timestamp: float               # Auto-set to current time
```

**Key methods:**
- `is_final_response() -> bool` -- True if this is the final text response (not a tool call)
- `get_function_calls() -> list[types.FunctionCall]`
- `get_function_responses() -> list[types.FunctionResponse]`

### EventActions

Actions attached to an event.

```python
class EventActions(BaseModel):
    skip_summarization: Optional[bool] = None
    state_delta: dict[str, object] = {}     # State changes
    artifact_delta: dict[str, int] = {}     # Artifact updates (filename -> version)
    transfer_to_agent: Optional[str] = None
    escalate: Optional[bool] = None         # Escalate to parent/exit loop
    requested_auth_configs: dict[str, AuthConfig] = {}
    requested_tool_confirmations: dict[str, ToolConfirmation] = {}
    end_of_agent: Optional[bool] = None
    agent_state: Optional[dict[str, Any]] = None
    rewind_before_invocation_id: Optional[str] = None
```

---

## google.adk.tools

```python
from google.adk.tools import (
    FunctionTool, ToolContext, BaseTool, BaseToolset,
    AgentTool, LongRunningFunctionTool, ExampleTool,
    MCPToolset,                    # MCP protocol toolset
    google_search,                 # Built-in Google Search
    exit_loop,                     # Use in LoopAgent sub-agents
    transfer_to_agent,             # Manual agent transfer function
    TransferToAgentTool,           # Agent transfer with enum constraints
    load_artifacts, load_memory, preload_memory,
)
```

### BaseTool

Abstract base for all tools.

```python
class BaseTool(ABC):
    name: str
    description: str
    is_long_running: bool = False
    custom_metadata: Optional[dict[str, Any]] = None

    def __init__(self, *, name, description, is_long_running=False, custom_metadata=None): ...

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any: ...
```

### FunctionTool

Wraps a Python function as a tool. Auto-extracts name, docstring, and parameter schema.

```python
class FunctionTool(BaseTool):
    def __init__(
        self,
        func: Callable[..., Any],
        *,
        require_confirmation: Union[bool, Callable[..., bool]] = False,
    ): ...
```

The wrapped function can optionally accept `tool_context: ToolContext` as a parameter to access session state, artifacts, etc.

### LongRunningFunctionTool

For operations that return asynchronously.

```python
class LongRunningFunctionTool(FunctionTool):
    def __init__(self, func: Callable): ...
    # Sets is_long_running = True automatically
```

### AgentTool

Wraps an agent so it can be called as a tool by another agent.

```python
class AgentTool(BaseTool):
    def __init__(
        self,
        agent: BaseAgent,
        skip_summarization: bool = False,
        *,
        include_plugins: bool = True,
    ): ...
```

### BaseToolset

Base class for toolsets (collections of tools, e.g., MCP).

```python
class BaseToolset(ABC):
    def __init__(
        self, *,
        tool_filter: Optional[Union[ToolPredicate, list[str]]] = None,
        tool_name_prefix: Optional[str] = None,
    ): ...

    @abstractmethod
    async def get_tools(self, readonly_context: Optional[ReadonlyContext] = None) -> list[BaseTool]: ...

    async def close(self) -> None: ...
```

### ToolContext

Context available inside tool functions. Extends `CallbackContext`.

```python
class ToolContext(CallbackContext):
    function_call_id: Optional[str]
    tool_confirmation: Optional[ToolConfirmation]

    # Inherited from CallbackContext:
    @property
    def state(self) -> State: ...          # Mutable session state
    @property
    def agent_name(self) -> str: ...
    @property
    def invocation_id(self) -> str: ...
    @property
    def session(self) -> Session: ...
    @property
    def user_content(self) -> Optional[types.Content]: ...

    # Methods:
    def request_credential(self, auth_config: AuthConfig) -> None: ...
    def get_auth_response(self, auth_config: AuthConfig) -> AuthCredential: ...
    def request_confirmation(self, *, hint: Optional[str] = None, payload: Optional[Any] = None) -> None: ...
    async def search_memory(self, query: str) -> SearchMemoryResponse: ...

    # Inherited from CallbackContext:
    async def load_artifact(self, filename: str, version: Optional[int] = None) -> Optional[types.Part]: ...
    async def save_artifact(self, filename: str, artifact: types.Part) -> int: ...
    async def list_artifacts(self) -> list[str]: ...

    @property
    def actions(self) -> EventActions: ...  # Mutable event actions
```

### Built-in Tool Functions

```python
# exit_loop -- call from within a LoopAgent sub-agent to break the loop
from google.adk.tools import exit_loop
# Usage: add exit_loop to tools list of an LlmAgent inside a LoopAgent

# transfer_to_agent -- manual transfer function (usually auto-handled)
from google.adk.tools import transfer_to_agent

# google_search -- built-in Google Search grounding
from google.adk.tools import google_search
```

---

## google.adk.sessions

```python
from google.adk.sessions import (
    Session, State,
    BaseSessionService, InMemorySessionService,
    DatabaseSessionService,         # Requires sqlalchemy>=2.0
    VertexAiSessionService,
)
```

### Session

```python
class Session(BaseModel):
    id: str
    app_name: str
    user_id: str
    state: dict[str, Any] = {}
    events: list[Event] = []
    last_update_time: float = 0.0
```

### State

Dict-like object with delta tracking. Used in `CallbackContext.state` and `ToolContext.state`.

```python
class State:
    APP_PREFIX = "app:"     # Keys prefixed with app: are app-scoped
    USER_PREFIX = "user:"   # Keys prefixed with user: are user-scoped
    TEMP_PREFIX = "temp:"   # Keys prefixed with temp: are not persisted

    def __getitem__(self, key: str) -> Any: ...
    def __setitem__(self, key: str, value: Any): ...
    def __contains__(self, key: str) -> bool: ...
    def get(self, key: str, default: Any = None) -> Any: ...
    def update(self, delta: dict[str, Any]): ...
    def has_delta(self) -> bool: ...
    def to_dict(self) -> dict[str, Any]: ...
```

### BaseSessionService

Abstract session service interface.

```python
class BaseSessionService(ABC):
    async def create_session(
        self, *, app_name: str, user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session: ...

    async def get_session(
        self, *, app_name: str, user_id: str, session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]: ...

    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None,
    ) -> ListSessionsResponse: ...

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str,
    ) -> None: ...

    async def append_event(self, session: Session, event: Event) -> Event: ...
```

### InMemorySessionService

In-memory implementation for testing/development.

```python
class InMemorySessionService(BaseSessionService):
    def __init__(self): ...
```

---

## google.adk.artifacts

```python
from google.adk.artifacts import (
    BaseArtifactService, InMemoryArtifactService,
    FileArtifactService, GcsArtifactService,
)
```

### BaseArtifactService

```python
class BaseArtifactService(ABC):
    async def save_artifact(
        self, *, app_name: str, user_id: str, filename: str,
        artifact: types.Part, session_id: Optional[str] = None,
        custom_metadata: Optional[dict[str, Any]] = None,
    ) -> int: ...   # Returns version number (0-indexed)

    async def load_artifact(
        self, *, app_name: str, user_id: str, filename: str,
        session_id: Optional[str] = None, version: Optional[int] = None,
    ) -> Optional[types.Part]: ...

    async def list_artifact_keys(
        self, *, app_name: str, user_id: str,
        session_id: Optional[str] = None,
    ) -> list[str]: ...

    async def delete_artifact(
        self, *, app_name: str, user_id: str, filename: str,
        session_id: Optional[str] = None,
    ) -> None: ...
```

---

## google.adk.plugins

```python
from google.adk.plugins import (
    BasePlugin, DebugLoggingPlugin, LoggingPlugin, PluginManager,
)
```

### BasePlugin

Abstract base for plugins. Plugins apply globally to all agents in the runner.

```python
class BasePlugin(ABC):
    def __init__(self, name: str): ...

    # Lifecycle callbacks (all async, all return Optional values to short-circuit):
    async def on_user_message_callback(self, *, invocation_context, user_message) -> Optional[types.Content]: ...
    async def before_run_callback(self, *, invocation_context) -> Optional[types.Content]: ...
    async def on_event_callback(self, *, invocation_context, event) -> Optional[Event]: ...
    async def after_run_callback(self, *, invocation_context) -> None: ...
    async def close(self) -> None: ...

    # Agent callbacks:
    async def before_agent_callback(self, *, agent, callback_context) -> Optional[types.Content]: ...
    async def after_agent_callback(self, *, agent, callback_context) -> Optional[types.Content]: ...

    # Model callbacks:
    async def before_model_callback(self, *, callback_context, llm_request) -> Optional[LlmResponse]: ...
    async def after_model_callback(self, *, callback_context, llm_response) -> Optional[LlmResponse]: ...
    async def on_model_error_callback(self, *, callback_context, llm_request, error) -> Optional[LlmResponse]: ...

    # Tool callbacks:
    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> Optional[dict]: ...
    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> Optional[dict]: ...
    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error) -> Optional[dict]: ...
```

### DebugLoggingPlugin

Records detailed interaction data to a YAML file.

```python
class DebugLoggingPlugin(BasePlugin):
    def __init__(
        self, *,
        name: str = "debug_logging_plugin",
        output_path: str = "adk_debug.yaml",
        include_session_state: bool = True,
        include_system_instruction: bool = True,
    ): ...
```

---

## google.adk.memory

```python
from google.adk.memory import (
    BaseMemoryService, InMemoryMemoryService,
    VertexAiMemoryBankService,
)
```

---

## Common Patterns

### 1. Minimal Agent with Tools

```python
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner

def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"Weather in {city}: 72F, sunny"

agent = LlmAgent(
    name="weather_agent",
    model="gemini-2.5-flash",
    instruction="You help users check the weather.",
    tools=[get_weather],
)

runner = InMemoryRunner(agent=agent)
# or with App:
# from google.adk.apps import App
# app = App(name="weather_app", root_agent=agent)
# runner = InMemoryRunner(app=app)
```

### 2. Tool with ToolContext (accessing state and artifacts)

```python
from google.adk.tools import ToolContext

def save_note(note: str, tool_context: ToolContext) -> str:
    """Save a note to session state."""
    notes = tool_context.state.get("notes", [])
    notes.append(note)
    tool_context.state["notes"] = notes
    return f"Saved note #{len(notes)}"

agent = LlmAgent(
    name="notes_agent",
    instruction="Help users save and recall notes. Current notes: {notes}",
    tools=[save_note],
)
```

### 3. Sequential Pipeline

```python
from google.adk.agents import LlmAgent, SequentialAgent

researcher = LlmAgent(
    name="researcher",
    instruction="Research the topic and write findings.",
    output_key="research_results",
)

writer = LlmAgent(
    name="writer",
    instruction="Write a report based on: {research_results}",
)

pipeline = SequentialAgent(
    name="pipeline",
    sub_agents=[researcher, writer],
)
```

### 4. Parallel Execution

```python
from google.adk.agents import LlmAgent, ParallelAgent

analyst_a = LlmAgent(name="analyst_a", instruction="Analyze from perspective A.", output_key="analysis_a")
analyst_b = LlmAgent(name="analyst_b", instruction="Analyze from perspective B.", output_key="analysis_b")

parallel = ParallelAgent(
    name="parallel_analysis",
    sub_agents=[analyst_a, analyst_b],
)
```

### 5. Loop with Exit Condition

```python
from google.adk.agents import LlmAgent, LoopAgent
from google.adk.tools import exit_loop

reviewer = LlmAgent(
    name="reviewer",
    instruction="Review the draft. If it's good, call exit_loop. Otherwise provide feedback.",
    tools=[exit_loop],
)

loop = LoopAgent(
    name="review_loop",
    sub_agents=[reviewer],
    max_iterations=5,
)
```

### 6. Agent Delegation (Multi-Agent with Transfer)

```python
from google.adk.agents import LlmAgent

billing_agent = LlmAgent(
    name="billing_agent",
    description="Handles billing questions.",
    instruction="You handle billing inquiries.",
)

support_agent = LlmAgent(
    name="support_agent",
    description="Handles technical support.",
    instruction="You handle technical support.",
)

router = LlmAgent(
    name="router",
    instruction="Route user to the right agent based on their question.",
    sub_agents=[billing_agent, support_agent],
    # transfer_to_agent tool is auto-injected when sub_agents are present
)
```

### 7. Using App with Runner

```python
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

app = App(name="my_app", root_agent=my_agent, plugins=[my_plugin])

runner = Runner(
    app=app,
    session_service=InMemorySessionService(),
)
```

### 8. Running the Agent

```python
from google.genai import types

# Create session
session = await runner.session_service.create_session(
    app_name="my_app", user_id="user1"
)

# Run async (production)
async for event in runner.run_async(
    user_id="user1",
    session_id=session.id,
    new_message=types.Content(
        role="user",
        parts=[types.Part(text="Hello!")],
    ),
):
    if event.is_final_response() and event.content and event.content.parts:
        print(event.content.parts[0].text)

# Quick debug (testing)
events = await runner.run_debug("Hello, what can you do?")
```

### 9. Using output_key to Chain Agents

```python
step1 = LlmAgent(
    name="step1",
    instruction="Summarize the input.",
    output_key="summary",  # Stores output in state["summary"]
)

step2 = LlmAgent(
    name="step2",
    instruction="Expand on this summary: {summary}",
    # {summary} is auto-resolved from session state
)

pipeline = SequentialAgent(name="pipeline", sub_agents=[step1, step2])
```

### 10. Streaming Mode

```python
from google.adk.agents.run_config import RunConfig, StreamingMode

config = RunConfig(streaming_mode=StreamingMode.SSE)

async for event in runner.run_async(
    user_id="user1", session_id=session.id,
    new_message=types.Content(role="user", parts=[types.Part(text="Tell me a story")]),
    run_config=config,
):
    if event.partial and event.content:
        # Streaming text chunks
        text = ''.join(p.text or '' for p in event.content.parts if p.text)
        print(text, end='', flush=True)
```

### 11. State Management (Complete Reference)

**WARNING -- CRITICAL: NEVER MUTATE STATE THROUGH `ctx.session.state` DIRECTLY**

> Coding agents constantly default to `ctx.session.state["key"] = value`.
> **This is WRONG and will silently break state persistence.**
>
> `session.state` is a plain `dict[str, Any]` (defined in `Session` model).
> Writing to it directly **bypasses delta tracking entirely**. The session
> service persists state by replaying `event.actions.state_delta` dicts
> attached to events. If your change never appears in a `state_delta`, it
> will not be saved by any persistent session service (database, Cloud, etc.)
> and will not propagate to other agents or across invocations.
>
> **ALWAYS use one of the tracked mutation patterns listed below.**

**How delta tracking works (source: `State` class in `sessions/state.py`,
`CallbackContext` in `agents/callback_context.py`):**

1. `CallbackContext.__init__` creates a `State(value=invocation_context.session.state, delta=event_actions.state_delta)`.
2. When you write `ctx.state["key"] = value`, the `State.__setitem__` method writes to **both** the underlying session dict (`_value`) **and** the delta dict (`_delta`).
3. Because `_delta` is the same object reference as `event_actions.state_delta`, the change is automatically recorded on the event that will be appended to the session.
4. When the session service processes the event, it reads `event.actions.state_delta` and persists those changes (see `BaseSessionService._update_session_state`).
5. **If you write to `session.state` directly, step 2-4 never happen** -- the delta dict is never populated and the session service never sees the change.

#### Correct State Mutation Patterns

| Where | Object | How to mutate | Delta tracked? |
|---|---|---|---|
| Tool function | `tool_context: ToolContext` | `tool_context.state["key"] = value` | Yes |
| Before/after agent callback | `callback_context: CallbackContext` | `callback_context.state["key"] = value` | Yes |
| Before/after model callback | `callback_context: CallbackContext` | `callback_context.state["key"] = value` | Yes |
| Before/after tool callback | `callback_context: CallbackContext` | `callback_context.state["key"] = value` | Yes |
| Custom `BaseAgent._run_async_impl` | `ctx: InvocationContext` | Yield an `Event` with `actions=EventActions(state_delta={"key": value})` | Yes |
| Runner (external caller) | `runner.run_async(...)` | Pass `state_delta={"key": value}` in `run_async` (attaches delta to the user event) | Yes |

**Anti-patterns (NEVER do these):**

```python
# WRONG -- bypasses delta tracking, changes may be lost
ctx.session.state["key"] = value

# WRONG -- same problem through the invocation context
invocation_context.session.state["key"] = value

# WRONG -- reading is fine but writing is not tracked
session = tool_context.session
session.state["key"] = value
```

**Correct examples:**

```python
# In a tool function:
async def my_tool(query: str, tool_context: ToolContext) -> str:
    tool_context.state["results_count"] = 42          # tracked
    tool_context.state["app:global_counter"] = 100    # tracked, app-scoped
    return "done"

# In a before_agent_callback:
async def my_callback(callback_context: CallbackContext):
    callback_context.state["user:preference"] = "dark"  # tracked
    return None

# In a custom BaseAgent._run_async_impl:
async def _run_async_impl(self, ctx: InvocationContext):
    # ... do work ...
    yield Event(
        invocation_id=ctx.invocation_id,
        author=self.name,
        actions=EventActions(state_delta={"my_key": "my_value"}),
    )
```

#### State Key Prefixes

All prefix constants are defined in the `State` class (`sessions/state.py`):

| Prefix | Constant | Scope | Persistence | Description |
|---|---|---|---|---|
| *(none)* | *(default)* | Session | Persisted across invocations within the same session | Default scope. Keys without a prefix are session-scoped. |
| `app:` | `State.APP_PREFIX` | Application | Persisted and shared across ALL sessions and users for the app | Use for app-wide configuration or counters. |
| `user:` | `State.USER_PREFIX` | User | Persisted and shared across all sessions for a given user | Use for user preferences or profile data. |
| `temp:` | `State.TEMP_PREFIX` | Invocation | **NOT persisted** -- stripped before storage by `BaseSessionService._remove_temp_state_delta` | Use for scratch data needed only during the current invocation. |

```python
# Session-scoped (default): persisted within this session
tool_context.state["my_key"] = "value"

# App-scoped: shared across ALL sessions and users in the app
tool_context.state["app:shared_config"] = "value"

# User-scoped: shared across all sessions for this user
tool_context.state["user:preferences"] = "value"

# Temporary: available during this invocation only, NOT persisted
tool_context.state["temp:scratchpad"] = "value"
```

How prefix scoping works at the storage layer (source: `_session_util.extract_state_delta`
and `InMemorySessionService.append_event`):

- `app:` keys are stripped of the prefix and stored in a separate app-level dict, then merged back with the prefix when a session is loaded.
- `user:` keys are stripped of the prefix and stored in a separate user-level dict, then merged back with the prefix when a session is loaded.
- `temp:` keys are filtered out before the event is persisted (`_remove_temp_state_delta`). They exist only in the in-memory session during the current invocation.
- All other keys are stored directly in the session-level state dict.

#### All State Access Patterns

| Access path | Context | Read/Write | Delta tracked? | Notes |
|---|---|---|---|---|
| `tool_context.state` | Tool function (`ToolContext`) | Read-write | Yes | Preferred way to read/write state in tools. `ToolContext` extends `CallbackContext`. |
| `callback_context.state` | Agent/model/tool callbacks (`CallbackContext`) | Read-write | Yes | Preferred way to read/write state in callbacks. |
| `readonly_context.state` | `ReadonlyContext` (base of `CallbackContext`) | **Read-only** | N/A | Returns `MappingProxyType` -- writes raise `TypeError`. Used in contexts where mutation is not intended. |
| `ctx.session.state` | `InvocationContext` | Read-write on the raw dict | **NO** | Plain `dict` -- mutations bypass delta tracking. **Do NOT write here.** Reading is acceptable. |
| `event.actions.state_delta` | On yielded `Event` objects | Write (at creation) | Yes (this IS the delta) | Used in custom `BaseAgent._run_async_impl` to attach state changes to events. |
| `runner.run_async(..., state_delta=)` | External caller via `Runner` | Write (at call) | Yes | Attaches delta to the initial user event. |

---

## ADK CLI

The `adk` CLI is the main command-line tool for developing, testing, and deploying agents. Source: `src/google/adk/cli/`.

### Agent Directory Structure

The CLI expects agents to live in a parent directory, with each agent as a subfolder. The loader searches in this order:

```
agents_dir/
  my_agent/
    __init__.py          # Option A: exports root_agent or app directly
    agent.py             # Option B: defines root_agent or app here
    root_agent.yaml      # Option C: YAML config (experimental)
    .env                 # Optional: auto-loaded environment variables
    requirements.txt     # Optional: extra dependencies (for deploy)
```

The loader checks for an `app` (instance of `App`) first, then `root_agent` (instance of `BaseAgent`).

### Commands

**`adk create`** -- Scaffold a new agent project.

```bash
adk create [--model MODEL] [--api_key KEY] [--project P] [--region R] APP_NAME
```

Creates `APP_NAME/` with `__init__.py`, `agent.py` (or `root_agent.yaml`), and `.env`. Prompts interactively for missing options.

**`adk run`** -- Run an agent interactively in the terminal.

```bash
adk run [--save_session] [--session_id ID] [--replay FILE] [--resume FILE] \
        [--session_service_uri URI] [--artifact_service_uri URI] \
        [--use_local_storage/--no_use_local_storage] AGENT_PATH
```

`AGENT_PATH` is the path to the agent folder (not the parent). Type `exit` to quit. `--replay` runs queries from a JSON file non-interactively. `--resume` reloads a previously saved session.

**`adk web`** -- Start the development web UI (FastAPI + Angular).

```bash
adk web [--host HOST] [--port PORT] [--reload/--no-reload] \
        [--session_service_uri URI] [--artifact_service_uri URI] \
        [--memory_service_uri URI] [--a2a] [--trace_to_cloud] \
        [--log_level LEVEL] [-v] [AGENTS_DIR]
```

`AGENTS_DIR` defaults to the current directory. Each subfolder with a valid agent is auto-discovered. Default: `http://127.0.0.1:8000`.

**`adk api_server`** -- Start a headless FastAPI server (no web UI).

```bash
adk api_server [--host HOST] [--port PORT] [--a2a] [AGENTS_DIR]
```

Same options as `adk web` but without the Angular frontend. Use for production-style API serving.

**`adk eval`** -- Evaluate an agent against eval sets.

```bash
adk eval [--config_file_path PATH] [--print_detailed_results] \
         [--eval_storage_uri URI] AGENT_PATH EVAL_SET_FILE_OR_ID...
```

`EVAL_SET_FILE_OR_ID` can be a JSON file path or an eval set ID. Append `:case1,case2` to run specific cases. Requires `google-adk[eval]` extras.

**`adk deploy cloud_run`** -- Deploy to Google Cloud Run.

```bash
adk deploy cloud_run --project P --region R [--service_name NAME] \
                     [--port PORT] [--with_ui] [--a2a] AGENT_PATH \
                     [-- EXTRA_GCLOUD_ARGS...]
```

Builds a Docker image and deploys via `gcloud run deploy`. Use `--` to pass extra args to gcloud.

**`adk deploy agent_engine`** -- Deploy to Vertex AI Agent Engine.

```bash
adk deploy agent_engine [--project P --region R | --api_key KEY] \
                        [--agent_engine_id ID] [--display_name NAME] AGENT_PATH
```

Pass `--agent_engine_id` to update an existing deployment. Supports Express Mode via `--api_key`.

**`adk deploy gke`** -- Deploy to Google Kubernetes Engine.

```bash
adk deploy gke --project P --region R --cluster_name C [--service_name NAME] AGENT_PATH
```

Builds a container image with Cloud Build, generates a Kubernetes deployment manifest, and applies it to the cluster.
