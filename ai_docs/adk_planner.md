### Planner

<div class="language-support-tag" title="">
   <span class="lst-supported">Supported in ADK</span><span class="lst-python">Python v0.1.0</span>
</div>

**`planner` (Optional):** Assign a `BasePlanner` instance to enable multi-step reasoning and planning before execution. There are two main planners:

* **`BuiltInPlanner`:** Leverages the model's built-in planning capabilities (e.g., Gemini's thinking feature). See [Gemini Thinking](https://ai.google.dev/gemini-api/docs/thinking) for details and examples.

    Here, the `thinking_budget` parameter guides the model on the number of thinking tokens to use when generating a response. The `include_thoughts` parameter controls whether the model should include its raw thoughts and internal reasoning process in the response.

    ```python
    from google.adk import Agent
    from google.adk.planners import BuiltInPlanner
    from google.genai import types

    my_agent = Agent(
        model="gemini-2.5-flash",
        planner=BuiltInPlanner(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=1024,
            )
        ),
        # ... your tools here
    )
    ```

* **`PlanReActPlanner`:** This planner instructs the model to follow a specific structure in its output: first create a plan, then execute actions (like calling tools), and provide reasoning for its steps. *It's particularly useful for models that don't have a built-in "thinking" feature*.

    ```python
    from google.adk import Agent
    from google.adk.planners import PlanReActPlanner

    my_agent = Agent(
        model="gemini-2.5-flash",
        planner=PlanReActPlanner(),
        # ... your tools here
    )
    ```

    The agent's response will follow a structured format:

    ```
    [user]: ai news
    [google_search_agent]: /*PLANNING*/
    1. Perform a Google search for "latest AI news" to get current updates and headlines related to artificial intelligence.
    2. Synthesize the information from the search results to provide a summary of recent AI news.

    /*ACTION*/
    /*REASONING*/
    The search results provide a comprehensive overview of recent AI news, covering various aspects like company developments, research breakthroughs, and applications. I have enough information to answer the user's request.

    /*FINAL_ANSWER*/
    Here's a summary of recent AI news:
    ....
    ```

Example for using built-in-planner:

```python
from dotenv import load_dotenv


import asyncio
import os

from google.genai import types
from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService # Optional
from google.adk.planners import BasePlanner, BuiltInPlanner, PlanReActPlanner
from google.adk.models import LlmRequest

from google.genai.types import ThinkingConfig
from google.genai.types import GenerateContentConfig

import datetime
from zoneinfo import ZoneInfo

APP_NAME = "weather_app"
USER_ID = "1234"
SESSION_ID = "session1234"

def get_weather(city: str) -> dict:
    """Retrieves the current weather report for a specified city.

    Args:
        city (str): The name of the city for which to retrieve the weather report.

    Returns:
        dict: status and result or error msg.
    """
    if city.lower() == "new york":
        return {
            "status": "success",
            "report": (
                "The weather in New York is sunny with a temperature of 25 degrees"
                " Celsius (77 degrees Fahrenheit)."
            ),
        }
    else:
        return {
            "status": "error",
            "error_message": f"Weather information for '{city}' is not available.",
        }


def get_current_time(city: str) -> dict:
    """Returns the current time in a specified city.

    Args:
        city (str): The name of the city for which to retrieve the current time.

    Returns:
        dict: status and result or error msg.
    """

    if city.lower() == "new york":
        tz_identifier = "America/New_York"
    else:
        return {
            "status": "error",
            "error_message": (
                f"Sorry, I don't have timezone information for {city}."
            ),
        }

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    report = (
        f'The current time in {city} is {now.strftime("%Y-%m-%d %H:%M:%S %Z%z")}'
    )
    return {"status": "success", "report": report}

# Step 1: Create a ThinkingConfig
thinking_config = ThinkingConfig(
    include_thoughts=True,   # Ask the model to include its thoughts in the response
    thinking_budget=256      # Limit the 'thinking' to 256 tokens (adjust as needed)
)
print("ThinkingConfig:", thinking_config)

# Step 2: Instantiate BuiltInPlanner
planner = BuiltInPlanner(
    thinking_config=thinking_config
)
print("BuiltInPlanner created.")

# Step 3: Wrap the planner in an LlmAgent
agent = LlmAgent(
    model="gemini-2.5-pro-preview-03-25",  # Set your model name
    name="weather_and_time_agent",
    instruction="You are an agent that returns time and weather",
    planner=planner,
    tools=[get_weather, get_current_time]
)

# Session and Runner
session_service = InMemorySessionService()
session = session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

# Agent Interaction
def call_agent(query):
    content = types.Content(role='user', parts=[types.Part(text=query)])
    events = runner.run(user_id=USER_ID, session_id=SESSION_ID, new_message=content)

    for event in events:
        print(f"\nDEBUG EVENT: {event}\n")
        if event.is_final_response() and event.content:
            final_answer = event.content.parts[0].text.strip()
            print("\n🟢 FINAL ANSWER\n", final_answer, "\n")

call_agent("If it's raining in New York right now, what is the current temperature?")

```

### Code Execution

<div class="language-support-tag">
   <span class="lst-supported">Supported in ADK</span><span class="lst-python">Python v0.1.0</span><span class="lst-java">Java v0.1.0</span>
</div>

- **`code_executor` (Optional):** Provide a `BaseCodeExecutor` instance to allow
  the agent to execute code blocks found in the LLM's response. For more
  information, see [Code Execution with Gemini API](/adk-docs/tools/gemini-api/code-execution/).

=== "Python"

    ```python
    --8<-- "examples/python/snippets/tools/built-in-tools/code_execution.py"
    ```

=== "Java"

    ```java
    --8<-- "examples/java/snippets/src/main/java/tools/CodeExecutionAgentApp.java:full_code"
    ```

## Putting It Together: Example

??? "Code"
    Here's the complete basic `capital_agent`:

    === "Python"

        ```python
        --8<-- "examples/python/snippets/agents/llm-agent/capital_agent.py"
        ```

    === "Typescript"

        ```javascript
        --8<-- "examples/typescript/snippets/agents/llm-agent/capital_agent.ts"
        ```

    === "Go"

        ```go
        --8<-- "examples/go/snippets/agents/llm-agents/main.go:full_code"
        ```

    === "Java"

        ```java
        --8<-- "examples/java/snippets/src/main/java/agents/LlmAgentExample.java:full_code"
        ```

_(This example demonstrates the core concepts. More complex agents might incorporate schemas, context control, planning, etc.)_
