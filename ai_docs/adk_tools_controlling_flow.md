### **Controlling Agent Flow**

The `tool_context.actions` attribute in Python and TypeScript, `ToolContext.actions()` in Java, and `tool.Context.Actions()` in Go, holds an **EventActions** object. Modifying attributes on this object allows your tool to influence what the agent or framework does after the tool finishes execution.

- **`skip_summarization: bool`**: (Default: False) If set to True, instructs the ADK to bypass the LLM call that typically summarizes the tool's output. This is useful if your tool's return value is already a user-ready message.
- **`transfer_to_agent: str`**: Set this to the name of another agent. The framework will halt the current agent's execution and **transfer control of the conversation to the specified agent**. This allows tools to dynamically hand off tasks to more specialized agents.
- **`escalate: bool`**: (Default: False) Setting this to True signals that the current agent cannot handle the request and should pass control up to its parent agent (if in a hierarchy). In a LoopAgent, setting **escalate=True** in a sub-agent's tool will terminate the loop.

#### Example

```py
# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai import types

APP_NAME="customer_support_agent"
USER_ID="user1234"
SESSION_ID="1234"


def check_and_transfer(query: str, tool_context: ToolContext) -> str:
    """Checks if the query requires escalation and transfers to another agent if needed."""
    if "urgent" in query.lower():
        print("Tool: Detected urgency, transferring to the support agent.")
        tool_context.actions.transfer_to_agent = "support_agent"
        return "Transferring to the support agent..."
    else:
        return f"Processed query: '{query}'. No further action needed."

escalation_tool = FunctionTool(func=check_and_transfer)

main_agent = Agent(
    model='gemini-2.0-flash',
    name='main_agent',
    instruction="""You are the first point of contact for customer support of an analytics tool. Answer general queries. If the user indicates urgency, use the 'escalation_tool' tool.""",
    tools=[escalation_tool]
)

support_agent = Agent(
    model='gemini-2.0-flash',
    name='support_agent',
    instruction="""You are the dedicated support agent. Mentioned you are a support handler and please help the user with their urgent issue."""
)

main_agent.sub_agents = [support_agent]

# Session and Runner
async def setup_session_and_runner():
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    runner = Runner(agent=main_agent, app_name=APP_NAME, session_service=session_service)
    return session, runner

# Agent Interaction
async def call_agent_async(query):
    content = types.Content(role='user', parts=[types.Part(text=query)])
    session, runner = await setup_session_and_runner()
    events = runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=content)

    async for event in events:
        if event.is_final_response():
            final_response = event.content.parts[0].text
            print("Agent Response: ", final_response)

# Note: In Colab, you can directly use 'await' at the top level.
# If running this code as a standalone Python script, you'll need to use asyncio.run() or manage the event loop.
await call_agent_async("this is urgent, i cant login")
##### Explanation

- We define two agents: `main_agent` and `support_agent`. The `main_agent` is designed to be the initial point of contact.
- The `check_and_transfer` tool, when called by `main_agent`, examines the user's query.
- If the query contains the word "urgent", the tool accesses the `tool_context`, specifically **`tool_context.actions`**, and sets the transfer_to_agent attribute to `support_agent`.
- This action signals to the framework to **transfer the control of the conversation to the agent named `support_agent`**.
- When the `main_agent` processes the urgent query, the `check_and_transfer` tool triggers the transfer. The subsequent response would ideally come from the `support_agent`.
- For a normal query without urgency, the tool simply processes it without triggering a transfer.

This example illustrates how a tool, through EventActions in its ToolContext, can dynamically influence the flow of the conversation by transferring control to another specialized agent.

### **Authentication**

ToolContext provides mechanisms for tools interacting with authenticated APIs. If your tool needs to handle authentication, you might use the following:

- **`auth_response`** (in Python): Contains credentials (e.g., a token) if authentication was already handled by the framework before your tool was called (common with RestApiTool and OpenAPI security schemes). In TypeScript, this is retrieved via the getAuthResponse() method.
- **`request_credential(auth_config: dict)`** (in Python) or **`requestCredential(authConfig: AuthConfig)`** (in TypeScript): Call this method if your tool determines authentication is needed but credentials aren't available. This signals the framework to start an authentication flow based on the provided auth_config.
- **`get_auth_response()`** (in Python) or **`getAuthResponse(authConfig: AuthConfig)`** (in TypeScript): Call this in a subsequent invocation (after request_credential was successfully handled) to retrieve the credentials the user provided.

For detailed explanations of authentication flows, configuration, and examples, please refer to the dedicated Tool Authentication documentation page.

### **Context-Aware Data Access Methods**

These methods provide convenient ways for your tool to interact with persistent data associated with the session or user, managed by configured services.

- **`list_artifacts()`** (in Python) or **`listArtifacts()`** (in Java and TypeScript): Returns a list of filenames (or keys) for all artifacts currently stored for the session via the artifact_service. Artifacts are typically files (images, documents, etc.) uploaded by the user or generated by tools/agents.
- **`load_artifact(filename: str)`**: Retrieves a specific artifact by its filename from the **artifact_service**. You can optionally specify a version; if omitted, the latest version is returned. Returns a `google.genai.types.Part` object containing the artifact data and mime type, or None if not found.
- **`save_artifact(filename: str, artifact: types.Part)`**: Saves a new version of an artifact to the artifact_service. Returns the new version number (starting from 0).
- **`search_memory(query: str)`**: (Support in ADK Python, Go and TypeScript) Queries the user's long-term memory using the configured `memory_service`. This is useful for retrieving relevant information from past interactions or stored knowledge. The structure of the **SearchMemoryResponse** depends on the specific memory service implementation but typically contains relevant text snippets or conversation excerpts.

#### Example

```py
# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.tools import ToolContext, FunctionTool
from google.genai import types


def process_document(
    document_name: str, analysis_query: str, tool_context: ToolContext
) -> dict:
    """Analyzes a document using context from memory."""

    # 1. Load the artifact
    print(f"Tool: Attempting to load artifact: {document_name}")
    document_part = tool_context.load_artifact(document_name)

    if not document_part:
        return {"status": "error", "message": f"Document '{document_name}' not found."}

    document_text = document_part.text  # Assuming it's text for simplicity
    print(f"Tool: Loaded document '{document_name}' ({len(document_text)} chars).")

    # 2. Search memory for related context
    print(f"Tool: Searching memory for context related to: '{analysis_query}'")
    memory_response = tool_context.search_memory(
        f"Context for analyzing document about {analysis_query}"
    )
    memory_context = "\n".join(
        [
            m.events[0].content.parts[0].text
            for m in memory_response.memories
            if m.events and m.events[0].content
        ]
    )  # Simplified extraction
    print(f"Tool: Found memory context: {memory_context[:100]}...")

    # 3. Perform analysis (placeholder)
    analysis_result = f"Analysis of '{document_name}' regarding '{analysis_query}' using memory context: [Placeholder Analysis Result]"
    print("Tool: Performed analysis.")

    # 4. Save the analysis result as a new artifact
    analysis_part = types.Part.from_text(text=analysis_result)
    new_artifact_name = f"analysis_{document_name}"
    version = await tool_context.save_artifact(new_artifact_name, analysis_part)
    print(f"Tool: Saved analysis result as '{new_artifact_name}' version {version}.")

    return {
        "status": "success",
        "analysis_artifact": new_artifact_name,
        "version": version,
    }


doc_analysis_tool = FunctionTool(func=process_document)

# In an Agent:
# Assume artifact 'report.txt' was previously saved.
# Assume memory service is configured and has relevant past data.
# my_agent = Agent(..., tools=[doc_analysis_tool], artifact_service=..., memory_service=...)
```

```typescript
import { Part } from "@google/genai";
import { ToolContext } from "@google/adk";

// Analyzes a document using context from memory.
export async function processDocument(
  params: { documentName: string; analysisQuery: string },
  toolContext?: ToolContext
): Promise<Record<string, any>> {
  if (!toolContext) {
    throw new Error("ToolContext is required for this tool.");
  }

  // 1. List all available artifacts
  const artifacts = await toolContext.listArtifacts();
  console.log(`Listing all available artifacts: ${artifacts}`);

  // 2. Load an artifact
  console.log(`Tool: Attempting to load artifact: ${params.documentName}`);
  const documentPart = await toolContext.loadArtifact(params.documentName);
  if (!documentPart) {
    console.log(`Tool: Document '${params.documentName}' not found.`);
    return {
      status: "error",
      message: `Document '${params.documentName}' not found.`, 
    };
  }

  const documentText = documentPart.text ?? "";
  console.log(
    `Tool: Loaded document '${params.documentName}' (${documentText.length} chars).`
  );

  // 3. Search memory for related context
  console.log(`Tool: Searching memory for context related to '${params.analysisQuery}'`);
  const memory_results = await toolContext.searchMemory(params.analysisQuery);
  console.log(`Tool: Found ${memory_results.memories.length} relevant memories.`);
  const context_from_memory = memory_results.memories
    .map((m) => m.content.parts[0].text)
    .join("\n");

  // 4. Perform analysis (placeholder)
  const analysisResult =
    `Analysis of '${params.documentName}' regarding '${params.analysisQuery}':\n` +
    `Context from Memory:\n${context_from_memory}\n` +
    `[Placeholder Analysis Result]`;
  console.log("Tool: Performed analysis.");

  // 5. Save the analysis result as a new artifact
  const analysisPart: Part = { text: analysisResult };
  const newArtifactName = `analysis_${params.documentName}`;
  await toolContext.saveArtifact(newArtifactName, analysisPart);
  console.log(`Tool: Saved analysis result to '${newArtifactName}'.`);

  return {
    status: "success",
    analysis_artifact: newArtifactName,
  };
}
```

```go
// Copyright 2025 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
    "fmt"

    "google.golang.org/adk/tool"
    "google.golang.org/genai"
)

type processDocumentArgs struct {
    DocumentName  string `json:"document_name" jsonschema:"The name of the document to be processed."`
    AnalysisQuery string `json:"analysis_query" jsonschema:"The query for the analysis."`
}

type processDocumentResult struct {
    Status           string `json:"status"`
    AnalysisArtifact string `json:"analysis_artifact,omitempty"`
    Version          int64  `json:"version,omitempty"`
    Message          string `json:"message,omitempty"`
}

func processDocument(ctx tool.Context, args processDocumentArgs) (*processDocumentResult, error) {
    fmt.Printf("Tool: Attempting to load artifact: %s\n", args.DocumentName)

    // List all artifacts
    listResponse, err := ctx.Artifacts().List(ctx)
    if err != nil {
        return nil, fmt.Errorf("failed to list artifacts")
    }

    fmt.Println("Tool: Available artifacts:")
    for _, file := range listResponse.FileNames {
        fmt.Printf(" - %s\n", file)
    }

    documentPart, err := ctx.Artifacts().Load(ctx, args.DocumentName)
    if err != nil {
        return nil, fmt.Errorf("document '%s' not found", args.DocumentName)
    }

    fmt.Printf("Tool: Loaded document '%s' of size %d bytes.\n", args.DocumentName, len(documentPart.Part.InlineData.Data))

    // 3. Search memory for related context
    fmt.Printf("Tool: Searching memory for context related to: '%s'\n", args.AnalysisQuery)
    memoryResp, err := ctx.SearchMemory(ctx, args.AnalysisQuery)
    if err != nil {
        fmt.Printf("Tool: Error searching memory: %v\n", err)
    }
    memoryResultCount := 0
    if memoryResp != nil {
        memoryResultCount = len(memoryResp.Memories)
    }
    fmt.Printf("Tool: Found %d memory results.\n", memoryResultCount)

    analysisResult := fmt.Sprintf("Analysis of '%s' regarding '%s' using memory context: [Placeholder Analysis Result]", args.DocumentName, args.AnalysisQuery)
    fmt.Println("Tool: Performed analysis.")

    analysisPart := genai.NewPartFromText(analysisResult)
    newArtifactName := fmt.Sprintf("analysis_%s", args.DocumentName)
    version, err := ctx.Artifacts().Save(ctx, newArtifactName, analysisPart)
    if err != nil {
        return nil, fmt.Errorf("failed to save artifact")
    }
    fmt.Printf("Tool: Saved analysis result as '%s' version %d.\n", newArtifactName, version.Version)

    return &processDocumentResult{
        Status:           "success",
        AnalysisArtifact: newArtifactName,
        Version:          version.Version,
    }, nil
}
```

```java
// Analyzes a document using context from memory.
// You can also list, load and save artifacts using Callback Context or LoadArtifacts tool.
public static @NonNull Maybe<ImmutableMap<String, Object>> processDocument(
    @Annotations.Schema(description = "The name of the document to analyze.") String documentName,
    @Annotations.Schema(description = "The query for the analysis.") String analysisQuery,
    ToolContext toolContext) {

  // 1. List all available artifacts
  System.out.printf(
      "Listing all available artifacts %s:", toolContext.listArtifacts().blockingGet());

  // 2. Load an artifact to memory
  System.out.println("Tool: Attempting to load artifact: " + documentName);
  Part documentPart = toolContext.loadArtifact(documentName, Optional.empty()).blockingGet();
  if (documentPart == null) {
    System.out.println("Tool: Document '" + documentName + "' not found.");
    return Maybe.just(
        ImmutableMap.<String, Object>of(
            "status", "error", "message", "Document '" + documentName + "' not found."));
  }
  String documentText = documentPart.text().orElse("");
  System.out.println(
      "Tool: Loaded document '" + documentName + "' (" + documentText.length() + " chars).");

  // 3. Perform analysis (placeholder)
  String analysisResult =
      "Analysis of '"
          + documentName
          + "' regarding '"
          + analysisQuery
          + " [Placeholder Analysis Result]";
  System.out.println("Tool: Performed analysis.");

  // 4. Save the analysis result as a new artifact
  Part analysisPart = Part.fromText(analysisResult);
  String newArtifactName = "analysis_" + documentName;

  toolContext.saveArtifact(newArtifactName, analysisPart);

  return Maybe.just(
      ImmutableMap.<String, Object>builder()
          .put("status", "success")
          .put("analysis_artifact", newArtifactName)
          .build());
}
// FunctionTool processDocumentTool =
//      FunctionTool.create(ToolContextArtifactExample.class, "processDocument");
// In the Agent, include this function tool.
// LlmAgent agent = LlmAgent().builder().tools(processDocumentTool).build();
```

By leveraging the **ToolContext**, developers can create more sophisticated and context-aware custom tools that seamlessly integrate with ADK's architecture and enhance the overall capabilities of their agents.

## Defining Effective Tool Functions

When using a method or function as an ADK Tool, how you define it significantly impacts the agent's ability to use it correctly. The agent's Large Language Model (LLM) relies heavily on the function's **name**, **parameters (arguments)**, **type hints**, and **docstring** / **source code comments** to understand its purpose and generate the correct call.

Here are key guidelines for defining effective tool functions:

- **Function Name:**

  - Use descriptive, verb-noun based names that clearly indicate the action (e.g., `get_weather`, `searchDocuments`, `schedule_meeting`).
  - Avoid generic names like `run`, `process`, `handle_data`, or overly ambiguous names like `doStuff`. Even with a good description, a name like `do_stuff` might confuse the model about when to use the tool versus, for example, `cancelFlight`.
  - The LLM uses the function name as a primary identifier during tool selection.

- **Parameters (Arguments):**

  - Your function can have any number of parameters.
  - Use clear and descriptive names (e.g., `city` instead of `c`, `search_query` instead of `q`).
  - **Provide type hints in Python** for all parameters (e.g., `city: str`, `user_id: int`, `items: list[str]`). This is essential for ADK to generate the correct schema for the LLM.
  - Ensure all parameter types are **JSON serializable**. All java primitives as well as standard Python types like `str`, `int`, `float`, `bool`, `list`, `dict`, and their combinations are generally safe. Avoid complex custom class instances as direct parameters unless they have a clear JSON representation.
  - **Do not set default values** for parameters. E.g., `def my_func(param1: str = "default")`. Default values are not reliably supported or used by the underlying models during function call generation. All necessary information should be derived by the LLM from the context or explicitly requested if missing.
  - **`self` / `cls` Handled Automatically:** Implicit parameters like `self` (for instance methods) or `cls` (for class methods) are automatically handled by ADK and excluded from the schema shown to the LLM. You only need to define type hints and descriptions for the logical parameters your tool requires the LLM to provide.

- **Return Type:**

  - The function's return value **must be a dictionary (`dict`)** in Python, a **Map** in Java, or a plain **object** in TypeScript.
  - If your function returns a non-dictionary type (e.g., a string, number, list), the ADK framework will automatically wrap it into a dictionary/Map like `{'result': your_original_return_value}` before passing the result back to the model.
  - Design the dictionary/Map keys and values to be **descriptive and easily understood *by the LLM***. Remember, the model reads this output to decide its next step.
  - Include meaningful keys. For example, instead of returning just an error code like `500`, return `{'status': 'error', 'error_message': 'Database connection failed'}`.
  - It's a **highly recommended practice** to include a `status` key (e.g., `'success'`, `'error'`, `'pending'`, `'ambiguous'`) to clearly indicate the outcome of the tool execution for the model.

- **Docstring / Source Code Comments:**

  - **This is critical.** The docstring is the primary source of descriptive information for the LLM.
  - **Clearly state what the tool *does*.** Be specific about its purpose and limitations.
  - **Explain *when* the tool should be used.** Provide context or example scenarios to guide the LLM's decision-making.
  - **Describe *each parameter* clearly.** Explain what information the LLM needs to provide for that argument.
  - Describe the **structure and meaning of the expected `dict` return value**, especially the different `status` values and associated data keys.
  - **Do not describe the injected ToolContext parameter**. Avoid mentioning the optional `tool_context: ToolContext` parameter within the docstring description since it is not a parameter the LLM needs to know about. ToolContext is injected by ADK, *after* the LLM decides to call it.

  **Example of a good definition:**

```python
def lookup_order_status(order_id: str) -> dict:
  """Fetches the current status of a customer's order using its ID.

  Use this tool ONLY when a user explicitly asks for the status of
  a specific order and provides the order ID. Do not use it for
  general inquiries.

  Args:
      order_id: The unique identifier of the order to look up.

  Returns:
      A dictionary indicating the outcome.
      On success, status is 'success' and includes an 'order' dictionary.
      On failure, status is 'error' and includes an 'error_message'.
      Example success: {'status': 'success', 'order': {'state': 'shipped', 'tracking_number': '1Z9...'}}
      Example error: {'status': 'error', 'error_message': 'Order ID not found.'}
  """
  # ... function implementation to fetch status ...
  if status_details := fetch_status_from_backend(order_id):
    return {
        "status": "success",
        "order": {
            "state": status_details.state,
            "tracking_number": status_details.tracking,
        },
    }
  else:
    return {"status": "error", "error_message": f"Order ID {order_id} not found."}
```

```typescript
/**
 * Fetches the current status of a customer's order using its ID.
 *
 * Use this tool ONLY when a user explicitly asks for the status of
 * a specific order and provides the order ID. Do not use it for
 * general inquiries.
 *
 * @param params The parameters for the function.
 * @param params.order_id The unique identifier of the order to look up.
 * @returns A dictionary indicating the outcome.
 *          On success, status is 'success' and includes an 'order' dictionary.
 *          On failure, status is 'error' and includes an 'error_message'.
 *          Example success: {'status': 'success', 'order': {'state': 'shipped', 'tracking_number': '1Z9...'}}
 *          Example error: {'status': 'error', 'error_message': 'Order ID not found.'}
 */
async function lookupOrderStatus(params: { order_id: string }): Promise<Record<string, any>> {
  // ... function implementation to fetch status from a backend ...
  const status_details = await fetchStatusFromBackend(params.order_id);
  if (status_details) {
    return {
      "status": "success",
      "order": {
        "state": status_details.state,
        "tracking_number": status_details.tracking,
      },
    };
  } else {
    return { "status": "error", "error_message": `Order ID ${params.order_id} not found.` };
  }
}

// Placeholder for a backend call
async function fetchStatusFromBackend(order_id: string): Promise<{state: string, tracking: string} | null> {
    if (order_id === "12345") {
        return { state: "shipped", tracking: "1Z9..." };
    }
    return null;
}
```

```go
import (
    "fmt"

    "google.golang.org/adk/tool"
)

type lookupOrderStatusArgs struct {
    OrderID string `json:"order_id" jsonschema:"The ID of the order to look up."`
}

type order struct {
    State          string `json:"state"`
    TrackingNumber string `json:"tracking_number"`
}

type lookupOrderStatusResult struct {
    Status string `json:"status"`
    Order  order  `json:"order,omitempty"`
}

func lookupOrderStatus(ctx tool.Context, args lookupOrderStatusArgs) (*lookupOrderStatusResult, error) {
    // ... function implementation to fetch status ...
    statusDetails, ok := fetchStatusFromBackend(args.OrderID)
    if !ok {
        return nil, fmt.Errorf("order ID %s not found", args.OrderID)
    }
    return &lookupOrderStatusResult{
        Status: "success",
        Order: order{
            State:          statusDetails.State,
            TrackingNumber: statusDetails.Tracking,
        },
    }, nil
}
```

```java
/**
 * Retrieves the current weather report for a specified city.
 *
 * @param city The city for which to retrieve the weather report.
 * @param toolContext The context for the tool.
 * @return A dictionary containing the weather information.
 */
public static Map<String, Object> getWeatherReport(String city, ToolContext toolContext) {
    Map<String, Object> response = new HashMap<>();
    if (city.toLowerCase(Locale.ROOT).equals("london")) {
        response.put("status", "success");
        response.put(
                "report",
                "The current weather in London is cloudy with a temperature of 18 degrees Celsius and a"
                        + " chance of rain.");
    } else if (city.toLowerCase(Locale.ROOT).equals("paris")) {
        response.put("status", "success");
        response.put("report", "The weather in Paris is sunny with a temperature of 25 degrees Celsius.");
    } else {
        response.put("status", "error");
        response.put("error_message", String.format("Weather information for '%s' is not available.", city));
    }
    return response;
}
```

- **Simplicity and Focus:**
  - **Keep Tools Focused:** Each tool should ideally perform one well-defined task.
  - **Fewer Parameters are Better:** Models generally handle tools with fewer, clearly defined parameters more reliably than those with many optional or complex ones.
  - **Use Simple Data Types:** Prefer basic types (`str`, `int`, `bool`, `float`, `List[str]`, in **Python**; `int`, `byte`, `short`, `long`, `float`, `double`, `boolean` and `char` in **Java**; or `string`, `number`, `boolean`, and arrays like `string[]` in **TypeScript**) over complex custom classes or deeply nested structures as parameters when possible.
  - **Decompose Complex Tasks:** Break down functions that perform multiple distinct logical steps into smaller, more focused tools. For instance, instead of a single `update_user_profile(profile: ProfileObject)` tool, consider separate tools like `update_user_name(name: str)`, `update_user_address(address: str)`, `update_user_preferences(preferences: list[str])`, etc. This makes it easier for the LLM to select and use the correct capability.

By adhering to these guidelines, you provide the LLM with the clarity and structure it needs to effectively utilize your custom function tools, leading to more capable and reliable agent behavior.

## Toolsets: Grouping and Dynamically Providing Tools

Supported in ADKPython v0.5.0Typescript v0.2.0

Beyond individual tools, ADK introduces the concept of a **Toolset** via the `BaseToolset` interface (defined in `google.adk.tools.base_toolset`). A toolset allows you to manage and provide a collection of `BaseTool` instances, often dynamically, to an agent.

This approach is beneficial for:

- **Organizing Related Tools:** Grouping tools that serve a common purpose (e.g., all tools for mathematical operations, or all tools interacting with a specific API).
- **Dynamic Tool Availability:** Enabling an agent to have different tools available based on the current context (e.g., user permissions, session state, or other runtime conditions). The `get_tools` method of a toolset can decide which tools to expose.
- **Integrating External Tool Providers:** Toolsets can act as adapters for tools coming from external systems, like an OpenAPI specification or an MCP server, converting them into ADK-compatible `BaseTool` objects.

### The `BaseToolset` Interface

Any class acting as a toolset in ADK should implement the `BaseToolset` abstract base class. This interface primarily defines two methods:

- **`async def get_tools(...) -> list[BaseTool]:`** This is the core method of a toolset. When an ADK agent needs to know its available tools, it will call `get_tools()` on each `BaseToolset` instance provided in its `tools` list.

  - It receives an optional `readonly_context` (an instance of `ReadonlyContext`). This context provides read-only access to information like the current session state (`readonly_context.state`), agent name, and invocation ID. The toolset can use this context to dynamically decide which tools to return.
  - It **must** return a `list` of `BaseTool` instances (e.g., `FunctionTool`, `RestApiTool`).

- **`async def close(self) -> None:`** This asynchronous method is called by the ADK framework when the toolset is no longer needed, for example, when an agent server is shutting down or the `Runner` is being closed. Implement this method to perform any necessary cleanup, such as closing network connections, releasing file handles, or cleaning up other resources managed by the toolset.

### Using Toolsets with Agents

You can include instances of your `BaseToolset` implementations directly in an `LlmAgent`'s `tools` list, alongside individual `BaseTool` instances.

When the agent initializes or needs to determine its available capabilities, the ADK framework will iterate through the `tools` list:

- If an item is a `BaseTool` instance, it's used directly.
- If an item is a `BaseToolset` instance, its `get_tools()` method is called (with the current `ReadonlyContext`), and the returned list of `BaseTool`s is added to the agent's available tools.

### Example: A Simple Math Toolset

Let's create a basic example of a toolset that provides simple arithmetic operations.

```py
# 1. Define the individual tool functions
def add_numbers(a: int, b: int, tool_context: ToolContext) -> Dict[str, Any]:
    """Adds two integer numbers.
    Args:
        a: The first number.
        b: The second number.
    Returns:
        A dictionary with the sum, e.g., {'status': 'success', 'result': 5}
    """
    print(f"Tool: add_numbers called with a={a}, b={b}")
    result = a + b
    # Example: Storing something in tool_context state
    tool_context.state["last_math_operation"] = "addition"
    return {"status": "success", "result": result}


def subtract_numbers(a: int, b: int) -> Dict[str, Any]:
    """Subtracts the second number from the first.
    Args:
        a: The first number.
        b: The second number.
    Returns:
        A dictionary with the difference, e.g., {'status': 'success', 'result': 1}
    """
    print(f"Tool: subtract_numbers called with a={a}, b={b}")
    return {"status": "success", "result": a - b}


# 2. Create the Toolset by implementing BaseToolset
class SimpleMathToolset(BaseToolset):
    def __init__(self, prefix: str = "math_"):
        self.prefix = prefix
        # Create FunctionTool instances once
        self._add_tool = FunctionTool(
            func=add_numbers,
            name=f"{self.prefix}add_numbers",  # Toolset can customize names
        )
        self._subtract_tool = FunctionTool(
            func=subtract_numbers, name=f"{self.prefix}subtract_numbers"
        )
        print(f"SimpleMathToolset initialized with prefix '{self.prefix}'")

    async def get_tools(
        self, readonly_context: Optional[ReadonlyContext] = None
    ) -> List[BaseTool]:
        print(f"SimpleMathToolset.get_tools() called.")
        # Example of dynamic behavior:
        # Could use readonly_context.state to decide which tools to return
        # For instance, if readonly_context.state.get("enable_advanced_math"):
        #    return [self._add_tool, self._subtract_tool, self._multiply_tool]

        # For this simple example, always return both tools
        tools_to_return = [self._add_tool, self._subtract_tool]
        print(f"SimpleMathToolset providing tools: {[t.name for t in tools_to_return]}")
        return tools_to_return

    async def close(self) -> None:
        # No resources to clean up in this simple example
        print(f"SimpleMathToolset.close() called for prefix '{self.prefix}'.")
        await asyncio.sleep(0)  # Placeholder for async cleanup if needed


# 3. Define an individual tool (not part of the toolset)
def greet_user(name: str = "User") -> Dict[str, str]:
    """Greets the user."""
    print(f"Tool: greet_user called with name={name}")
    return {"greeting": f"Hello, {name}!"}


greet_tool = FunctionTool(func=greet_user)

# 4. Instantiate the toolset
math_toolset_instance = SimpleMathToolset(prefix="calculator_")

# 5. Define an agent that uses both the individual tool and the toolset
calculator_agent = LlmAgent(
    name="CalculatorAgent",
    model="gemini-2.0-flash",  # Replace with your desired model
    instruction="You are a helpful calculator and greeter. "
    "Use 'greet_user' for greetings. "
    "Use 'calculator_add_numbers' to add and 'calculator_subtract_numbers' to subtract. "
    "Announce the state of 'last_math_operation' if it's set.",
    tools=[greet_tool, math_toolset_instance],  # Individual tool  # Toolset instance
)
```

```typescript
/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import { LlmAgent, FunctionTool, ToolContext, BaseToolset, InMemoryRunner, isFinalResponse, BaseTool, stringifyContent } from "@google/adk";
import { z } from "zod";
import { Content, createUserContent } from "@google/genai";

function addNumbers(params: { a: number; b: number }, toolContext?: ToolContext): Record<string, any> {
  if (!toolContext) {
    throw new Error("ToolContext is required for this tool.");
  }
  const result = params.a + params.b;
  toolContext.state.set("last_math_result", result);
  return { result: result };
}

function subtractNumbers(params: { a: number; b: number }): Record<string, any> {
  return { result: params.a - params.b };
}

function greetUser(params: { name: string }): Record<string, any> {
  return { greeting: `Hello, ${params.name}!` };
}

class SimpleMathToolset extends BaseToolset {
  private readonly tools: BaseTool[];

  constructor(prefix = "") {
    super([]); // No filter
    this.tools = [
      new FunctionTool({
        name: `${prefix}add_numbers`,
        description: "Adds two numbers and stores the result in the session state.",
        parameters: z.object({ a: z.number(), b: z.number() }),
        execute: addNumbers,
      }),
      new FunctionTool({
        name: `${prefix}subtract_numbers`,
        description: "Subtracts the second number from the first.",
        parameters: z.object({ a: z.number(), b: z.number() }),
        execute: subtractNumbers,
      }),
    ];
  }

  async getTools(): Promise<BaseTool[]> {
    return this.tools;
  }

  async close(): Promise<void> {
    console.log("SimpleMathToolset closed.");
  }
}

async function main() {
  const mathToolset = new SimpleMathToolset("calculator_");
  const greetTool = new FunctionTool({
    name: "greet_user",
    description: "Greets the user.",
    parameters: z.object({ name: z.string() }),
    execute: greetUser,
  });

  const instruction =
    `You are a calculator and a greeter.
    If the user asks for a math operation, use the calculator tools.
    If the user asks for a greeting, use the greet_user tool.
    The result of the last math operation is stored in the 'last_math_result' state variable.`;

  const calculatorAgent = new LlmAgent({
    name: "calculator_agent",
    instruction: instruction,
    tools: [greetTool, mathToolset],
    model: "gemini-2.5-flash",
  });

  const runner = new InMemoryRunner({ agent: calculatorAgent, appName: "toolset_app" });
  await runner.sessionService.createSession({ appName: "toolset_app", userId: "user1", sessionId: "session1" });

  const message: Content = createUserContent("What is 5 + 3?");

  for await (const event of runner.runAsync({ userId: "user1", sessionId: "session1", newMessage: message })) {
    if (isFinalResponse(event) && event.content?.parts?.length) {
      const text = stringifyContent(event).trim();
      if (text) {
        console.log(`Response from agent: ${text}`);
      }
    }
  }

  await mathToolset.close();
}

main();
```

In this example:

- `SimpleMathToolset` implements `BaseToolset` and its `get_tools()` method returns `FunctionTool` instances for `add_numbers` and `subtract_numbers`. It also customizes their names using a prefix.
- The `calculator_agent` is configured with both an individual `greet_tool` and an instance of `SimpleMathToolset`.
- When `calculator_agent` is run, ADK will call `math_toolset_instance.get_tools()`. The agent's LLM will then have access to `greet_user`, `calculator_add_numbers`, and `calculator_subtract_numbers` to handle user requests.
- The `add_numbers` tool demonstrates writing to `tool_context.state`, and the agent's instruction mentions reading this state.
- The `close()` method is called to ensure any resources held by the toolset are released.

Toolsets offer a powerful way to organize, manage, and dynamically provide collections of tools to your ADK agents, leading to more modular, maintainable, and adaptable agentic applications.
