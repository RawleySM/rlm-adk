# Callbacks: Observe, Customize, and Control Agent Behavior

Supported in ADKPython v0.1.0TypeScript v0.2.0Go v0.1.0Java v0.1.0

Callbacks are a cornerstone feature of ADK, providing a powerful mechanism to hook into an agent's execution process. They allow you to observe, customize, and even control the agent's behavior at specific, predefined points without modifying the core ADK framework code.

**What are they?** In essence, callbacks are standard functions that you define. You then associate these functions with an agent when you create it. The ADK framework automatically calls your functions at key stages, letting you observe or intervene. Think of it like checkpoints during the agent's process:

- **Before the agent starts its main work on a request, and after it finishes:** When you ask an agent to do something (e.g., answer a question), it runs its internal logic to figure out the response.
- The `Before Agent` callback executes *right before* this main work begins for that specific request.
- The `After Agent` callback executes *right after* the agent has finished all its steps for that request and has prepared the final result, but just before the result is returned.
- This "main work" encompasses the agent's *entire* process for handling that single request. This might involve deciding to call an LLM, actually calling the LLM, deciding to use a tool, using the tool, processing the results, and finally putting together the answer. These callbacks essentially wrap the whole sequence from receiving the input to producing the final output for that one interaction.
- **Before sending a request to, or after receiving a response from, the Large Language Model (LLM):** These callbacks (`Before Model`, `After Model`) allow you to inspect or modify the data going to and coming from the LLM specifically.
- **Before executing a tool (like a Python function or another agent) or after it finishes:** Similarly, `Before Tool` and `After Tool` callbacks give you control points specifically around the execution of tools invoked by the agent.

**Why use them?** Callbacks unlock significant flexibility and enable advanced agent capabilities:

- **Observe & Debug:** Log detailed information at critical steps for monitoring and troubleshooting.
- **Customize & Control:** Modify data flowing through the agent (like LLM requests or tool results) or even bypass certain steps entirely based on your logic.
- **Implement Guardrails:** Enforce safety rules, validate inputs/outputs, or prevent disallowed operations.
- **Manage State:** Read or dynamically update the agent's session state during execution.
- **Integrate & Enhance:** Trigger external actions (API calls, notifications) or add features like caching.

Tip

When implementing security guardrails and policies, use ADK Plugins for better modularity and flexibility than Callbacks. For more details, see [Callbacks and Plugins for Security Guardrails](/adk-docs/safety/#callbacks-and-plugins-for-security-guardrails).

**How are they added:**

Code

```python
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse, LlmRequest
from typing import Optional

# --- Define your callback function ---
def my_before_model_logic(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    print(f"Callback running before model call for agent: {callback_context.agent_name}")
    # ... your custom logic here ...
    return None # Allow the model call to proceed

# --- Register it during Agent creation ---
my_agent = LlmAgent(
    name="MyCallbackAgent",
    model="gemini-2.0-flash", # Or your desired model
    instruction="Be helpful.",
    # Other agent parameters...
    before_model_callback=my_before_model_logic # Pass the function here
)
```

## The Callback Mechanism: Interception and Control

When the ADK framework encounters a point where a callback can run (e.g., just before calling the LLM), it checks if you provided a corresponding callback function for that agent. If you did, the framework executes your function.

**Context is Key:** Your callback function isn't called in isolation. The framework provides special **context objects** (`CallbackContext` or `ToolContext`) as arguments. These objects contain vital information about the current state of the agent's execution, including the invocation details, session state, and potentially references to services like artifacts or memory. You use these context objects to understand the situation and interact with the framework. (See the dedicated "Context Objects" section for full details).

**Controlling the Flow (The Core Mechanism):** The most powerful aspect of callbacks lies in how their **return value** influences the agent's subsequent actions. This is how you intercept and control the execution flow:

1. **`return None` (Allow Default Behavior):**

   - The specific return type can vary depending on the language. In Java, the equivalent return type is `Optional.empty()`. Refer to the API documentation for language specific guidance.
   - This is the standard way to signal that your callback has finished its work (e.g., logging, inspection, minor modifications to *mutable* input arguments like `llm_request`) and that the ADK agent should **proceed with its normal operation**.
   - For `before_*` callbacks (`before_agent`, `before_model`, `before_tool`), returning `None` means the next step in the sequence (running the agent logic, calling the LLM, executing the tool) will occur.
   - For `after_*` callbacks (`after_agent`, `after_model`, `after_tool`), returning `None` means the result just produced by the preceding step (the agent's output, the LLM's response, the tool's result) will be used as is.

1. **`return <Specific Object>` (Override Default Behavior):**

   - Returning a *specific type of object* (instead of `None`) is how you **override** the ADK agent's default behavior. The framework will use the object you return and *skip* the step that would normally follow or *replace* the result that was just generated.
   - **`before_agent_callback` → `types.Content`**: Skips the agent's main execution logic (`_run_async_impl` / `_run_live_impl`). The returned `Content` object is immediately treated as the agent's final output for this turn. Useful for handling simple requests directly or enforcing access control.
   - **`before_model_callback` → `LlmResponse`**: Skips the call to the external Large Language Model. The returned `LlmResponse` object is processed as if it were the actual response from the LLM. Ideal for implementing input guardrails, prompt validation, or serving cached responses.
   - **`before_tool_callback` → `dict` or `Map`**: Skips the execution of the actual tool function (or sub-agent). The returned `dict` is used as the result of the tool call, which is then typically passed back to the LLM. Perfect for validating tool arguments, applying policy restrictions, or returning mocked/cached tool results.
   - **`after_agent_callback` → `types.Content`**: *Replaces* the `Content` that the agent's run logic just produced.
   - **`after_model_callback` → `LlmResponse`**: *Replaces* the `LlmResponse` received from the LLM. Useful for sanitizing outputs, adding standard disclaimers, or modifying the LLM's response structure.
   - **`after_tool_callback` → `dict` or `Map`**: *Replaces* the `dict` result returned by the tool. Allows for post-processing or standardization of tool outputs before they are sent back to the LLM.

**Conceptual Code Example (Guardrail):**

This example demonstrates the common pattern for a guardrail using `before_model_callback`.

Code

```python
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

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse, LlmRequest
from google.adk.runners import Runner
from typing import Optional
from google.genai import types 
from google.adk.sessions import InMemorySessionService

GEMINI_2_FLASH="gemini-2.0-flash"

# --- Define the Callback Function ---
def simple_before_model_modifier(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """Inspects/modifies the LLM request or skips the call."""
    agent_name = callback_context.agent_name
    print(f"[Callback] Before model call for agent: {agent_name}")

    # Inspect the last user message in the request contents
    last_user_message = ""
    if llm_request.contents and llm_request.contents[-1].role == 'user':
         if llm_request.contents[-1].parts:
            last_user_message = llm_request.contents[-1].parts[0].text
    print(f"[Callback] Inspecting last user message: '{last_user_message}'")

    # --- Modification Example ---
    # Add a prefix to the system instruction
    original_instruction = llm_request.config.system_instruction or types.Content(role="system", parts=[])
    prefix = "[Modified by Callback] "
    # Ensure system_instruction is Content and parts list exists
    if not isinstance(original_instruction, types.Content):
         # Handle case where it might be a string (though config expects Content)
         original_instruction = types.Content(role="system", parts=[types.Part(text=str(original_instruction))])
    if not original_instruction.parts:
        original_instruction.parts.append(types.Part(text="")) # Add an empty part if none exist

    # Modify the text of the first part
    modified_text = prefix + (original_instruction.parts[0].text or "")
    original_instruction.parts[0].text = modified_text
    llm_request.config.system_instruction = original_instruction
    print(f"[Callback] Modified system instruction to: '{modified_text}'")

    # --- Skip Example ---
    # Check if the last user message contains "BLOCK"
    if "BLOCK" in last_user_message.upper():
        print("[Callback] 'BLOCK' keyword found. Skipping LLM call.")
        # Return an LlmResponse to skip the actual LLM call
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="LLM call was blocked by before_model_callback.")],
            )
        )
    else:
        print("[Callback] Proceeding with LLM call.")
        # Return None to allow the (modified) request to go to the LLM
        return None

# Create LlmAgent and Assign Callback
my_llm_agent = LlmAgent(
        name="ModelCallbackAgent",
        model=GEMINI_2_FLASH,
        instruction="You are a helpful assistant.", # Base instruction
        description="An LLM agent demonstrating before_model_callback",
        before_model_callback=simple_before_model_modifier # Assign the function here
)

APP_NAME = "guardrail_app"
USER_ID = "user_1"
SESSION_ID = "session_001"

# Session and Runner
async def setup_session_and_runner():
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    runner = Runner(agent=my_llm_agent, app_name=APP_NAME, session_service=session_service)
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
await call_agent_async("write a joke on BLOCK")
```

By understanding this mechanism of returning `None` versus returning specific objects, you can precisely control the agent's execution path, making callbacks an essential tool for building sophisticated and reliable agents with ADK.

# Types of Callbacks

Supported in ADKPython v0.1.0TypeScript v0.2.0Go v0.1.0Java v0.1.0

The framework provides different types of callbacks that trigger at various stages of an agent's execution. Understanding when each callback fires and what context it receives is key to using them effectively.

## Agent Lifecycle Callbacks

These callbacks are available on *any* agent that inherits from `BaseAgent` (including `LlmAgent`, `SequentialAgent`, `ParallelAgent`, `LoopAgent`, etc).

Note

The specific method names or return types may vary slightly by SDK language (e.g., return `None` in Python, return `Optional.empty()` or `Maybe.empty()` in Java). Refer to the language-specific API documentation for details.

### Before Agent Callback

**When:** Called *immediately before* the agent's `_run_async_impl` (or `_run_live_impl`) method is executed. It runs after the agent's `InvocationContext` is created but *before* its core logic begins.

**Purpose:** Ideal for setting up resources or state needed only for this specific agent's run, performing validation checks on the session state (callback_context.state) before execution starts, logging the entry point of the agent's activity, or potentially modifying the invocation context before the core logic uses it.

Code

```python
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

# # --- Setup Instructions ---
# # 1. Install the ADK package:
# !pip install google-adk
# # Make sure to restart kernel if using colab/jupyter notebooks

# # 2. Set up your Gemini API Key:
# #    - Get a key from Google AI Studio: https://aistudio.google.com/app/apikey
# #    - Set it as an environment variable:
# import os
# os.environ["GOOGLE_API_KEY"] = "YOUR_API_KEY_HERE" # <--- REPLACE with your actual key
# # Or learn about other authentication methods (like Vertex AI):
# # https://google.github.io/adk-docs/agents/models/

# ADK Imports
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.runners import InMemoryRunner # Use InMemoryRunner
from google.genai import types # For types.Content
from typing import Optional

# Define the model - Use the specific model name requested
GEMINI_2_FLASH="gemini-2.0-flash"

# --- 1. Define the Callback Function ---
def check_if_agent_should_run(callback_context: CallbackContext) -> Optional[types.Content]:
    """
    Logs entry and checks 'skip_llm_agent' in session state.
    If True, returns Content to skip the agent's execution.
    If False or not present, returns None to allow execution.
    """
    agent_name = callback_context.agent_name
    invocation_id = callback_context.invocation_id
    current_state = callback_context.state.to_dict()

    print(f"\n[Callback] Entering agent: {agent_name} (Inv: {invocation_id})")
    print(f"[Callback] Current State: {current_state}")

    # Check the condition in session state dictionary
    if current_state.get("skip_llm_agent", False):
        print(f"[Callback] State condition 'skip_llm_agent=True' met: Skipping agent {agent_name}.")
        # Return Content to skip the agent's run
        return types.Content(
            parts=[types.Part(text=f"Agent {agent_name} skipped by before_agent_callback due to state.")],
            role="model" # Assign model role to the overriding response
        )
    else:
        print(f"[Callback] State condition not met: Proceeding with agent {agent_name}.")
        # Return None to allow the LlmAgent's normal execution
        return None

# --- 2. Setup Agent with Callback ---
llm_agent_with_before_cb = LlmAgent(
    name="MyControlledAgent",
    model=GEMINI_2_FLASH,
    instruction="You are a concise assistant.",
    description="An LLM agent demonstrating stateful before_agent_callback",
    before_agent_callback=check_if_agent_should_run # Assign the callback
)

# --- 3. Setup Runner and Sessions using InMemoryRunner ---
async def main():
    app_name = "before_agent_demo"
    user_id = "test_user"
    session_id_run = "session_will_run"
    session_id_skip = "session_will_skip"

    # Use InMemoryRunner - it includes InMemorySessionService
    runner = InMemoryRunner(agent=llm_agent_with_before_cb, app_name=app_name)
    # Get the bundled session service to create sessions
    session_service = runner.session_service

    # Create session 1: Agent will run (default empty state)
    session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id_run
        # No initial state means 'skip_llm_agent' will be False in the callback check
    )

    # Create session 2: Agent will be skipped (state has skip_llm_agent=True)
    session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id_skip,
        state={"skip_llm_agent": True} # Set the state flag here
    )

    # --- Scenario 1: Run where callback allows agent execution ---
    print("\n" + "="*20 + f" SCENARIO 1: Running Agent on Session '{session_id_run}' (Should Proceed) " + "="*20)
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id_run,
        new_message=types.Content(role="user", parts=[types.Part(text="Hello, please respond.")])
    ):
        # Print final output (either from LLM or callback override)
        if event.is_final_response() and event.content:
            print(f"Final Output: [{event.author}] {event.content.parts[0].text.strip()}")
        elif event.is_error():
             print(f"Error Event: {event.error_details}")

    # --- Scenario 2: Run where callback intercepts and skips agent ---
    print("\n" + "="*20 + f" SCENARIO 2: Running Agent on Session '{session_id_skip}' (Should Skip) " + "="*20)
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id_skip,
        new_message=types.Content(role="user", parts=[types.Part(text="This message won't reach the LLM.")])
    ):
         # Print final output (either from LLM or callback override)
         if event.is_final_response() and event.content:
            print(f"Final Output: [{event.author}] {event.content.parts[0].text.strip()}")
         elif event.is_error():
             print(f"Error Event: {event.error_details}")

# --- 4. Execute ---
# In a Python script:
# import asyncio
# if __name__ == "__main__":
#     # Make sure GOOGLE_API_KEY environment variable is set if not using Vertex AI auth
#     # Or ensure Application Default Credentials (ADC) are configured for Vertex AI
#     asyncio.run(main())

# In a Jupyter Notebook or similar environment:
await main()
```

**Note on the `before_agent_callback` Example:**

- **What it Shows:** This example demonstrates the `before_agent_callback`. This callback runs *right before* the agent's main processing logic starts for a given request.
- **How it Works:** The callback function (`check_if_agent_should_run`) looks at a flag (`skip_llm_agent`) in the session's state.
  - If the flag is `True`, the callback returns a `types.Content` object. This tells the ADK framework to **skip** the agent's main execution entirely and use the callback's returned content as the final response.
  - If the flag is `False` (or not set), the callback returns `None` or an empty object. This tells the ADK framework to **proceed** with the agent's normal execution (calling the LLM in this case).
- **Expected Outcome:** You'll see two scenarios:
  1. In the session *with* the `skip_llm_agent: True` state, the agent's LLM call is bypassed, and the output comes directly from the callback ("Agent... skipped...").
  1. In the session *without* that state flag, the callback allows the agent to run, and you see the actual response from the LLM (e.g., "Hello!").
- **Understanding Callbacks:** This highlights how `before_` callbacks act as **gatekeepers**, allowing you to intercept execution *before* a major step and potentially prevent it based on checks (like state, input validation, permissions).

### After Agent Callback

**When:** Called *immediately after* the agent's `_run_async_impl` (or `_run_live_impl`) method successfully completes. It does *not* run if the agent was skipped due to `before_agent_callback` returning content or if `end_invocation` was set during the agent's run.

**Purpose:** Useful for cleanup tasks, post-execution validation, logging the completion of an agent's activity, modifying final state, or augmenting the agent's final output.

Code

```python
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

# # --- Setup Instructions ---
# # 1. Install the ADK package:
# !pip install google-adk
# # Make sure to restart kernel if using colab/jupyter notebooks

# # 2. Set up your Gemini API Key:
# #    - Get a key from Google AI Studio: https://aistudio.google.com/app/apikey
# #    - Set it as an environment variable:
# import os
# os.environ["GOOGLE_API_KEY"] = "YOUR_API_KEY_HERE" # <--- REPLACE with your actual key
# # Or learn about other authentication methods (like Vertex AI):
# # https://google.github.io/adk-docs/agents/models/

# ADK Imports
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.runners import InMemoryRunner # Use InMemoryRunner
from google.genai import types # For types.Content
from typing import Optional

# Define the model - Use the specific model name requested
GEMINI_2_FLASH="gemini-2.0-flash"

# --- 1. Define the Callback Function ---
def modify_output_after_agent(callback_context: CallbackContext) -> Optional[types.Content]:
    """
    Logs exit from an agent and checks 'add_concluding_note' in session state.
    If True, returns new Content to *replace* the agent's original output.
    If False or not present, returns None, allowing the agent's original output to be used.
    """
    agent_name = callback_context.agent_name
    invocation_id = callback_context.invocation_id
    current_state = callback_context.state.to_dict()

    print(f"\n[Callback] Exiting agent: {agent_name} (Inv: {invocation_id})")
    print(f"[Callback] Current State: {current_state}")

    # Example: Check state to decide whether to modify the final output
    if current_state.get("add_concluding_note", False):
        print(f"[Callback] State condition 'add_concluding_note=True' met: Replacing agent {agent_name}'s output.")
        # Return Content to *replace* the agent's own output
        return types.Content(
            parts=[types.Part(text=f"Concluding note added by after_agent_callback, replacing original output.")],
            role="model" # Assign model role to the overriding response
        )
    else:
        print(f"[Callback] State condition not met: Using agent {agent_name}'s original output.")
        # Return None - the agent's output produced just before this callback will be used.
        return None

# --- 2. Setup Agent with Callback ---
llm_agent_with_after_cb = LlmAgent(
    name="MySimpleAgentWithAfter",
    model=GEMINI_2_FLASH,
    instruction="You are a simple agent. Just say 'Processing complete!'",
    description="An LLM agent demonstrating after_agent_callback for output modification",
    after_agent_callback=modify_output_after_agent # Assign the callback here
)

# --- 3. Setup Runner and Sessions using InMemoryRunner ---
async def main():
    app_name = "after_agent_demo"
    user_id = "test_user_after"
    session_id_normal = "session_run_normally"
    session_id_modify = "session_modify_output"

    # Use InMemoryRunner - it includes InMemorySessionService
    runner = InMemoryRunner(agent=llm_agent_with_after_cb, app_name=app_name)
    # Get the bundled session service to create sessions
    session_service = runner.session_service

    # Create session 1: Agent output will be used as is (default empty state)
    session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id_normal
        # No initial state means 'add_concluding_note' will be False in the callback check
    )
    # print(f"Session '{session_id_normal}' created with default state.")

    # Create session 2: Agent output will be replaced by the callback
    session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id_modify,
        state={"add_concluding_note": True} # Set the state flag here
    )
    # print(f"Session '{session_id_modify}' created with state={{'add_concluding_note': True}}.")

    # --- Scenario 1: Run where callback allows agent's original output ---
    print("\n" + "="*20 + f" SCENARIO 1: Running Agent on Session '{session_id_normal}' (Should Use Original Output) " + "="*20)
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id_normal,
        new_message=types.Content(role="user", parts=[types.Part(text="Process this please.")])
    ):
        # Print final output (either from LLM or callback override)
        if event.is_final_response() and event.content:
            print(f"Final Output: [{event.author}] {event.content.parts[0].text.strip()}")
        elif event.is_error():
             print(f"Error Event: {event.error_details}")

    # --- Scenario 2: Run where callback replaces the agent's output ---
    print("\n" + "="*20 + f" SCENARIO 2: Running Agent on Session '{session_id_modify}' (Should Replace Output) " + "="*20)
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id_modify,
        new_message=types.Content(role="user", parts=[types.Part(text="Process this and add note.")])
    ):
         # Print final output (either from LLM or callback override)
         if event.is_final_response() and event.content:
            print(f"Final Output: [{event.author}] {event.content.parts[0].text.strip()}")
         elif event.is_error():
             print(f"Error Event: {event.error_details}")

# --- 4. Execute ---
# In a Python script:
# import asyncio
# if __name__ == "__main__":
#     # Make sure GOOGLE_API_KEY environment variable is set if not using Vertex AI auth
#     # Or ensure Application Default Credentials (ADC) are configured for Vertex AI
#     asyncio.run(main())

# In a Jupyter Notebook or similar environment:
await main()
```

**Note on the `after_agent_callback` Example:**

- **What it Shows:** This example demonstrates the `after_agent_callback`. This callback runs *right after* the agent's main processing logic has finished and produced its result, but *before* that result is finalized and returned.
- **How it Works:** The callback function (`modify_output_after_agent`) checks a flag (`add_concluding_note`) in the session's state.
  - If the flag is `True`, the callback returns a *new* `types.Content` object. This tells the ADK framework to **append** the agent's original output with the content returned by the callback.
  - If the flag is `False` (or not set), the callback returns `None` or an empty object. This tells the ADK framework to **use** the original output generated by the agent.
- **Expected Outcome:** You'll see two scenarios:
  1. In the session *without* the `add_concluding_note: True` state, the callback allows the agent's original output ("Processing complete!") to be used.
  1. In the session *with* that state flag, the callback intercepts the agent's original output and appends it with its own message ("Concluding note added...").
- **Understanding Callbacks:** This highlights how `after_` callbacks allow **post-processing** or **modification**. You can inspect the result of a step (the agent's run) and decide whether to let it pass through, change it, or completely replace it based on your logic.

## LLM Interaction Callbacks

These callbacks are specific to `LlmAgent` and provide hooks around the interaction with the Large Language Model.

### Before Model Callback

**When:** Called just before the `generate_content_async` (or equivalent) request is sent to the LLM within an `LlmAgent`'s flow.

**Purpose:** Allows inspection and modification of the request going to the LLM. Use cases include adding dynamic instructions, injecting few-shot examples based on state, modifying model config, implementing guardrails (like profanity filters), or implementing request-level caching.

**Return Value Effect:** If the callback returns `None` (or a `Maybe.empty()` object in Java), the LLM continues its normal workflow. If the callback returns an `LlmResponse` object, then the call to the LLM is **skipped**. The returned `LlmResponse` is used directly as if it came from the model. This is powerful for implementing guardrails or caching.

Code

```python
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

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse, LlmRequest
from google.adk.runners import Runner
from typing import Optional
from google.genai import types 
from google.adk.sessions import InMemorySessionService

GEMINI_2_FLASH="gemini-2.0-flash"

# --- Define the Callback Function ---
def simple_before_model_modifier(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """Inspects/modifies the LLM request or skips the call."""
    agent_name = callback_context.agent_name
    print(f"[Callback] Before model call for agent: {agent_name}")

    # Inspect the last user message in the request contents
    last_user_message = ""
    if llm_request.contents and llm_request.contents[-1].role == 'user':
         if llm_request.contents[-1].parts:
            last_user_message = llm_request.contents[-1].parts[0].text
    print(f"[Callback] Inspecting last user message: '{last_user_message}'")

    # --- Modification Example ---
    # Add a prefix to the system instruction
    original_instruction = llm_request.config.system_instruction or types.Content(role="system", parts=[])
    prefix = "[Modified by Callback] "
    # Ensure system_instruction is Content and parts list exists
    if not isinstance(original_instruction, types.Content):
         # Handle case where it might be a string (though config expects Content)
         original_instruction = types.Content(role="system", parts=[types.Part(text=str(original_instruction))])
    if not original_instruction.parts:
        original_instruction.parts.append(types.Part(text="")) # Add an empty part if none exist

    # Modify the text of the first part
    modified_text = prefix + (original_instruction.parts[0].text or "")
    original_instruction.parts[0].text = modified_text
    llm_request.config.system_instruction = original_instruction
    print(f"[Callback] Modified system instruction to: '{modified_text}'")

    # --- Skip Example ---
    # Check if the last user message contains "BLOCK"
    if "BLOCK" in last_user_message.upper():
        print("[Callback] 'BLOCK' keyword found. Skipping LLM call.")
        # Return an LlmResponse to skip the actual LLM call
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="LLM call was blocked by before_model_callback.")],
            )
        )
    else:
        print("[Callback] Proceeding with LLM call.")
        # Return None to allow the (modified) request to go to the LLM
        return None

# Create LlmAgent and Assign Callback
my_llm_agent = LlmAgent(
        name="ModelCallbackAgent",
        model=GEMINI_2_FLASH,
        instruction="You are a helpful assistant.", # Base instruction
        description="An LLM agent demonstrating before_model_callback",
        before_model_callback=simple_before_model_modifier # Assign the function here
)

APP_NAME = "guardrail_app"
USER_ID = "user_1"
SESSION_ID = "session_001"

# Session and Runner
async def setup_session_and_runner():
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    runner = Runner(agent=my_llm_agent, app_name=APP_NAME, session_service=session_service)
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
await call_agent_async("write a joke on BLOCK")
```

### After Model Callback

**When:** Called just after a response (`LlmResponse`) is received from the LLM, before it's processed further by the invoking agent.

**Purpose:** Allows inspection or modification of the raw LLM response. Use cases include

- logging model outputs,
- reformatting responses,
- censoring sensitive information generated by the model,
- parsing structured data from the LLM response and storing it in `callback_context.state`
- or handling specific error codes.

Code

```python
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

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.runners import Runner
from typing import Optional
from google.genai import types 
from google.adk.sessions import InMemorySessionService
from google.adk.models import LlmResponse
from copy import deepcopy

GEMINI_2_FLASH="gemini-2.0-flash"

# --- Define the Callback Function ---
def simple_after_model_modifier(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Inspects/modifies the LLM response after it's received."""
    agent_name = callback_context.agent_name
    print(f"[Callback] After model call for agent: {agent_name}")

    # --- Inspection ---
    original_text = ""
    if llm_response.content and llm_response.content.parts:
        # Assuming simple text response for this example
        if llm_response.content.parts[0].text:
            original_text = llm_response.content.parts[0].text
            print(f"[Callback] Inspected original response text: '{original_text[:100]}...'") # Log snippet
        elif llm_response.content.parts[0].function_call:
             print(f"[Callback] Inspected response: Contains function call '{llm_response.content.parts[0].function_call.name}'. No text modification.")
             return None # Don't modify tool calls in this example
        else:
             print("[Callback] Inspected response: No text content found.")
             return None
    elif llm_response.error_message:
        print(f"[Callback] Inspected response: Contains error '{llm_response.error_message}'. No modification.")
        return None
    else:
        print("[Callback] Inspected response: Empty LlmResponse.")
        return None # Nothing to modify

    # --- Modification Example ---
    # Replace "joke" with "funny story" (case-insensitive)
    search_term = "joke"
    replace_term = "funny story"
    if search_term in original_text.lower():
        print(f"[Callback] Found '{search_term}'. Modifying response.")
        modified_text = original_text.replace(search_term, replace_term)
        modified_text = modified_text.replace(search_term.capitalize(), replace_term.capitalize()) # Handle capitalization

        # Create a NEW LlmResponse with the modified content
        # Deep copy parts to avoid modifying original if other callbacks exist
        modified_parts = [deepcopy(part) for part in llm_response.content.parts]
        modified_parts[0].text = modified_text # Update the text in the copied part

        new_response = LlmResponse(
             content=types.Content(role="model", parts=modified_parts),
             # Copy other relevant fields if necessary, e.g., grounding_metadata
             grounding_metadata=llm_response.grounding_metadata
             )
        print(f"[Callback] Returning modified response.")
        return new_response # Return the modified response
    else:
        print(f"[Callback] '{search_term}' not found. Passing original response through.")
        # Return None to use the original llm_response
        return None

# Create LlmAgent and Assign Callback
my_llm_agent = LlmAgent(
        name="AfterModelCallbackAgent",
        model=GEMINI_2_FLASH,
        instruction="You are a helpful assistant.",
        description="An LLM agent demonstrating after_model_callback",
        after_model_callback=simple_after_model_modifier # Assign the function here
)

APP_NAME = "guardrail_app"
USER_ID = "user_1"
SESSION_ID = "session_001"

# Session and Runner
async def setup_session_and_runner():
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    runner = Runner(agent=my_llm_agent, app_name=APP_NAME, session_service=session_service)
    return session, runner

# Agent Interaction
async def call_agent_async(query):
  session, runner = await setup_session_and_runner()

  content = types.Content(role='user', parts=[types.Part(text=query)])
  events = runner.run_async(user_id=USER_ID, session_id=SESSION_ID, new_message=content)

  async for event in events:
      if event.is_final_response():
          final_response = event.content.parts[0].text
          print("Agent Response: ", final_response)

# Note: In Colab, you can directly use 'await' at the top level.
# If running this code as a standalone Python script, you'll need to use asyncio.run() or manage the event loop.
await call_agent_async("""write multiple time the word "joke" """)
```

## Tool Execution Callbacks

These callbacks are also specific to `LlmAgent` and trigger around the execution of tools (including `FunctionTool`, `AgentTool`, etc.) that the LLM might request.

### Before Tool Callback

**When:** Called just before a specific tool's `run_async` method is invoked, after the LLM has generated a function call for it.

**Purpose:** Allows inspection and modification of tool arguments, performing authorization checks before execution, logging tool usage attempts, or implementing tool-level caching.

**Return Value Effect:**

1. If the callback returns `None` (or a `Maybe.empty()` object in Java), the tool's `run_async` method is executed with the (potentially modified) `args`.
1. If a dictionary (or `Map` in Java) is returned, the tool's `run_async` method is **skipped**. The returned dictionary is used directly as the result of the tool call. This is useful for caching or overriding tool behavior.

Code

```python
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

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from typing import Optional
from google.genai import types 
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.adk.tools.base_tool import BaseTool
from typing import Dict, Any

GEMINI_2_FLASH="gemini-2.0-flash"

def get_capital_city(country: str) -> str:
    """Retrieves the capital city of a given country."""
    print(f"--- Tool 'get_capital_city' executing with country: {country} ---")
    country_capitals = {
        "united states": "Washington, D.C.",
        "canada": "Ottawa",
        "france": "Paris",
        "germany": "Berlin",
    }
    return country_capitals.get(country.lower(), f"Capital not found for {country}")

capital_tool = FunctionTool(func=get_capital_city)

def simple_before_tool_modifier(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext
) -> Optional[Dict]:
    """Inspects/modifies tool args or skips the tool call."""
    agent_name = tool_context.agent_name
    tool_name = tool.name
    print(f"[Callback] Before tool call for tool '{tool_name}' in agent '{agent_name}'")
    print(f"[Callback] Original args: {args}")

    if tool_name == 'get_capital_city' and args.get('country', '').lower() == 'canada':
        print("[Callback] Detected 'Canada'. Modifying args to 'France'.")
        args['country'] = 'France'
        print(f"[Callback] Modified args: {args}")
        return None

    # If the tool is 'get_capital_city' and country is 'BLOCK'
    if tool_name == 'get_capital_city' and args.get('country', '').upper() == 'BLOCK':
        print("[Callback] Detected 'BLOCK'. Skipping tool execution.")
        return {"result": "Tool execution was blocked by before_tool_callback."}

    print("[Callback] Proceeding with original or previously modified args.")
    return None

my_llm_agent = LlmAgent(
        name="ToolCallbackAgent",
        model=GEMINI_2_FLASH,
        instruction="You are an agent that can find capital cities. Use the get_capital_city tool.",
        description="An LLM agent demonstrating before_tool_callback",
        tools=[capital_tool],
        before_tool_callback=simple_before_tool_modifier
)

APP_NAME = "guardrail_app"
USER_ID = "user_1"
SESSION_ID = "session_001"

# Session and Runner
async def setup_session_and_runner():
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    runner = Runner(agent=my_llm_agent, app_name=APP_NAME, session_service=session_service)
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
await call_agent_async("Canada")
```

### After Tool Callback

**When:** Called just after the tool's `run_async` method completes successfully.

**Purpose:** Allows inspection and modification of the tool's result before it's sent back to the LLM (potentially after summarization). Useful for logging tool results, post-processing or formatting results, or saving specific parts of the result to the session state.

**Return Value Effect:**

1. If the callback returns `None` (or a `Maybe.empty()` object in Java), the original `tool_response` is used.
1. If a new dictionary is returned, it **replaces** the original `tool_response`. This allows modifying or filtering the result seen by the LLM.

Code

```python
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

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from typing import Optional
from google.genai import types 
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext
from google.adk.tools.base_tool import BaseTool
from typing import Dict, Any
from copy import deepcopy

GEMINI_2_FLASH="gemini-2.0-flash"

# --- Define a Simple Tool Function (Same as before) ---
def get_capital_city(country: str) -> str:
    """Retrieves the capital city of a given country."""
    print(f"--- Tool 'get_capital_city' executing with country: {country} ---")
    country_capitals = {
        "united states": "Washington, D.C.",
        "canada": "Ottawa",
        "france": "Paris",
        "germany": "Berlin",
    }
    return {"result": country_capitals.get(country.lower(), f"Capital not found for {country}")}

# --- Wrap the function into a Tool ---
capital_tool = FunctionTool(func=get_capital_city)

# --- Define the Callback Function ---
def simple_after_tool_modifier(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, tool_response: Dict
) -> Optional[Dict]:
    """Inspects/modifies the tool result after execution."""
    agent_name = tool_context.agent_name
    tool_name = tool.name
    print(f"[Callback] After tool call for tool '{tool_name}' in agent '{agent_name}'")
    print(f"[Callback] Args used: {args}")
    print(f"[Callback] Original tool_response: {tool_response}")

    # Default structure for function tool results is {"result": <return_value>}
    original_result_value = tool_response.get("result", "")
    # original_result_value = tool_response

    # --- Modification Example ---
    # If the tool was 'get_capital_city' and result is 'Washington, D.C.'
    if tool_name == 'get_capital_city' and original_result_value == "Washington, D.C.":
        print("[Callback] Detected 'Washington, D.C.'. Modifying tool response.")

        # IMPORTANT: Create a new dictionary or modify a copy
        modified_response = deepcopy(tool_response)
        modified_response["result"] = f"{original_result_value} (Note: This is the capital of the USA)."
        modified_response["note_added_by_callback"] = True # Add extra info if needed

        print(f"[Callback] Modified tool_response: {modified_response}")
        return modified_response # Return the modified dictionary

    print("[Callback] Passing original tool response through.")
    # Return None to use the original tool_response
    return None

# Create LlmAgent and Assign Callback
my_llm_agent = LlmAgent(
        name="AfterToolCallbackAgent",
        model=GEMINI_2_FLASH,
        instruction="You are an agent that finds capital cities using the get_capital_city tool. Report the result clearly.",
        description="An LLM agent demonstrating after_tool_callback",
        tools=[capital_tool], # Add the tool
        after_tool_callback=simple_after_tool_modifier # Assign the callback
    )

APP_NAME = "guardrail_app"
USER_ID = "user_1"
SESSION_ID = "session_001"

# Session and Runner
async def setup_session_and_runner():
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
    runner = Runner(agent=my_llm_agent, app_name=APP_NAME, session_service=session_service)
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
await call_agent_async("united states")
```

# Design Patterns and Best Practices for Callbacks

Callbacks offer powerful hooks into the agent lifecycle. Here are common design patterns illustrating how to leverage them effectively in ADK, followed by best practices for implementation.

## Design Patterns

These patterns demonstrate typical ways to enhance or control agent behavior using callbacks:

### 1. Guardrails & Policy Enforcement

**Pattern Overview:** Intercept requests before they reach the LLM or tools to enforce rules.

**Implementation:**

- Use `before_model_callback` to inspect the `LlmRequest` prompt
- Use `before_tool_callback` to inspect tool arguments
- If a policy violation is detected (e.g., forbidden topics, profanity):
- Return a predefined response (`LlmResponse` or `dict`/`Map`) to block the operation
- Optionally update `context.state` to log the violation

**Example Use Case:** A `before_model_callback` checks `llm_request.contents` for sensitive keywords and returns a standard "Cannot process this request" `LlmResponse` if found, preventing the LLM call.

### 2. Dynamic State Management

**Pattern Overview:** Read from and write to session state within callbacks to make agent behavior context-aware and pass data between steps.

**Implementation:**

- Access `callback_context.state` or `tool_context.state`
- Modifications (`state['key'] = value`) are automatically tracked in the subsequent `Event.actions.state_delta`
- Changes are persisted by the `SessionService`

**Example Use Case:** An `after_tool_callback` saves a `transaction_id` from the tool's result to `tool_context.state['last_transaction_id']`. A later `before_agent_callback` might read `state['user_tier']` to customize the agent's greeting.

### 3. Logging and Monitoring

**Pattern Overview:** Add detailed logging at specific lifecycle points for observability and debugging.

**Implementation:**

- Implement callbacks (e.g., `before_agent_callback`, `after_tool_callback`, `after_model_callback`)
- Print or send structured logs containing:
- Agent name
- Tool name
- Invocation ID
- Relevant data from the context or arguments

**Example Use Case:** Log messages like `INFO: [Invocation: e-123] Before Tool: search_api - Args: {'query': 'ADK'}`.

### 4. Caching

**Pattern Overview:** Avoid redundant LLM calls or tool executions by caching results.

**Implementation Steps:**

1. **Before Operation:** In `before_model_callback` or `before_tool_callback`:

- Generate a cache key based on the request/arguments
- Check `context.state` (or an external cache) for this key
- If found, return the cached `LlmResponse` or result directly

1. **After Operation:** If cache miss occurred:
1. Use the corresponding `after_` callback to store the new result in the cache using the key

**Example Use Case:** `before_tool_callback` for `get_stock_price(symbol)` checks `state[f"cache:stock:{symbol}"]`. If present, returns the cached price; otherwise, allows the API call and `after_tool_callback` saves the result to the state key.

### 5. Request/Response Modification

**Pattern Overview:** Alter data just before it's sent to the LLM/tool or just after it's received.

**Implementation Options:**

- **`before_model_callback`:** Modify `llm_request` (e.g., add system instructions based on `state`)
- **`after_model_callback`:** Modify the returned `LlmResponse` (e.g., format text, filter content)
- **`before_tool_callback`:** Modify the tool `args` dictionary (or Map in Java)
- **`after_tool_callback`:** Modify the `tool_response` dictionary (or Map in Java)

**Example Use Case:** `before_model_callback` appends "User language preference: Spanish" to `llm_request.config.system_instruction` if `context.state['lang'] == 'es'`.

### 6. Conditional Skipping of Steps

**Pattern Overview:** Prevent standard operations (agent run, LLM call, tool execution) based on certain conditions.

**Implementation:**

- Return a value from a `before_` callback to skip the normal execution:
- `Content` from `before_agent_callback`
- `LlmResponse` from `before_model_callback`
- `dict` from `before_tool_callback`
- The framework interprets this returned value as the result for that step

**Example Use Case:** `before_tool_callback` checks `tool_context.state['api_quota_exceeded']`. If `True`, it returns `{'error': 'API quota exceeded'}`, preventing the actual tool function from running.

### 7. Tool-Specific Actions (Authentication & Summarization Control)

**Pattern Overview:** Handle actions specific to the tool lifecycle, primarily authentication and controlling LLM summarization of tool results.

**Implementation:** Use `ToolContext` within tool callbacks (`before_tool_callback`, `after_tool_callback`):

- **Authentication:** Call `tool_context.request_credential(auth_config)` in `before_tool_callback` if credentials are required but not found (e.g., via `tool_context.get_auth_response` or state check). This initiates the auth flow.
- **Summarization:** Set `tool_context.actions.skip_summarization = True` if the raw dictionary output of the tool should be passed back to the LLM or potentially displayed directly, bypassing the default LLM summarization step.

**Example Use Case:** A `before_tool_callback` for a secure API checks for an auth token in state; if missing, it calls `request_credential`. An `after_tool_callback` for a tool returning structured JSON might set `skip_summarization = True`.

### 8. Artifact Handling

**Pattern Overview:** Save or load session-related files or large data blobs during the agent lifecycle.

**Implementation:**

- **Saving:** Use `callback_context.save_artifact` / `await tool_context.save_artifact` to store data:
- Generated reports
- Logs
- Intermediate data
- **Loading:** Use `load_artifact` to retrieve previously stored artifacts
- **Tracking:** Changes are tracked via `Event.actions.artifact_delta`

**Example Use Case:** An `after_tool_callback` for a "generate_report" tool saves the output file using `await tool_context.save_artifact("report.pdf", report_part)`. A `before_agent_callback` might load a configuration artifact using `callback_context.load_artifact("agent_config.json")`.

## Best Practices for Callbacks

### Design Principles

**Keep Focused:** Design each callback for a single, well-defined purpose (e.g., just logging, just validation). Avoid monolithic callbacks.

**Mind Performance:** Callbacks execute synchronously within the agent's processing loop. Avoid long-running or blocking operations (network calls, heavy computation). Offload if necessary, but be aware this adds complexity.

### Error Handling

**Handle Errors Gracefully:**

- Use `try...except/catch` blocks within your callback functions
- Log errors appropriately
- Decide if the agent invocation should halt or attempt recovery
- Don't let callback errors crash the entire process

### State Management

**Manage State Carefully:**

- Be deliberate about reading from and writing to `context.state`
- Changes are immediately visible within the *current* invocation and persisted at the end of the event processing
- Use specific state keys rather than modifying broad structures to avoid unintended side effects
- Consider using state prefixes (`State.APP_PREFIX`, `State.USER_PREFIX`, `State.TEMP_PREFIX`) for clarity, especially with persistent `SessionService` implementations

### Reliability

**Consider Idempotency:** If a callback performs actions with external side effects (e.g., incrementing an external counter), design it to be idempotent (safe to run multiple times with the same input) if possible, to handle potential retries in the framework or your application.

### Testing & Documentation

**Test Thoroughly:**

- Unit test your callback functions using mock context objects
- Perform integration tests to ensure callbacks function correctly within the full agent flow

**Ensure Clarity:**

- Use descriptive names for your callback functions
- Add clear docstrings explaining their purpose, when they run, and any side effects (especially state modifications)

**Use Correct Context Type:** Always use the specific context type provided (`CallbackContext` for agent/model, `ToolContext` for tools) to ensure access to the appropriate methods and properties.

By applying these patterns and best practices, you can effectively use callbacks to create more robust, observable, and customized agent behaviors in ADK.
