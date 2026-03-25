## Guiding the Agent: Instructions (`instruction`)

The `instruction` parameter is arguably the most critical for shaping an
`LlmAgent`'s behavior. It's a string (or a function returning a string) that
tells the agent:

* Its core task or goal.
* Its personality or persona (e.g., "You are a helpful assistant," "You are a witty pirate").
* Constraints on its behavior (e.g., "Only answer questions about X," "Never reveal Y").
* How and when to use its `tools`. You should explain the purpose of each tool and the circumstances under which it should be called, supplementing any descriptions within the tool itself.
* The desired format for its output (e.g., "Respond in JSON," "Provide a bulleted list").

**Tips for Effective Instructions:**

* **Be Clear and Specific:** Avoid ambiguity. Clearly state the desired actions and outcomes.
* **Use Markdown:** Improve readability for complex instructions using headings, lists, etc.
* **Provide Examples (Few-Shot):** For complex tasks or specific output formats, include examples directly in the instruction.
* **Guide Tool Use:** Don't just list tools; explain *when* and *why* the agent should use them.

**State:**

* The instruction is a string template, you can use the `{var}` syntax to insert dynamic values into the instruction.
* `{var}` is used to insert the value of the state variable named var.
* `{artifact.var}` is used to insert the text content of the artifact named var.
* If the state variable or artifact does not exist, the agent will raise an error. If you want to ignore the error, you can append a `?` to the variable name as in `{var?}`.

=== "Python"

    ```python
    # Example: Adding instructions
    capital_agent = LlmAgent(
        model="gemini-2.5-flash",
        name="capital_agent",
        description="Answers user questions about the capital city of a given country.",
        instruction="""You are an agent that provides the capital city of a country.
    When a user asks for the capital of a country:
    1. Identify the country name from the user's query.
    2. Use the `get_capital_city` tool to find the capital.
    3. Respond clearly to the user, stating the capital city.
    Example Query: "What's the capital of {country}?"
    Example Response: "The capital of France is Paris."
    """,
        # tools will be added next
    )
    ```

    ### Managing Context (`include_contents`)

Control whether the agent receives the prior conversation history.

* **`include_contents` (Optional, Default: `'default'`):** Determines if the `contents` (history) are sent to the LLM.
    * `'default'`: The agent receives the relevant conversation history.
    * `'none'`: The agent receives no prior `contents`. It operates based solely on its current instruction and any input provided in the *current* turn (useful for stateless tasks or enforcing specific contexts).


## The `static_instruction` and `instruction` parameters in `LlmAgent` land in different locations in the `LlmRequest` depending on whether `static_instruction` is set:

**Without `static_instruction`:**
- `instruction` → `system_instruction` (with state injection)

**With `static_instruction`:**
- `static_instruction` → `system_instruction` (position 0, no processing)
- `instruction` → `contents` (as user content, with state injection)

## Details

The behavior is determined by the `_build_instructions()` function in the instruction processing pipeline [1](#3-0) :

### When only `instruction` is set:
```python
if agent.instruction and not agent.static_instruction:
    si = await _process_agent_instruction(agent, invocation_context)
    llm_request.append_instructions([si])
```
The dynamic instruction goes to system instructions with state injection [2](#3-1) .

### When both are set:
```python
if agent.static_instruction:
    static_content = _transformers.t_content(agent.static_instruction)
    llm_request.append_instructions(static_content)

# Later...
if agent.instruction and agent.static_instruction:
    si = await _process_agent_instruction(agent, invocation_context)
    dynamic_content = types.Content(role='user', parts=[types.Part(text=si)])
    llm_request.contents.append(dynamic_content)
```
`static_instruction` goes to system instructions (position 0) while `instruction` becomes user content [3](#3-2) .

### Purpose of this design
This separation enables context caching optimization - the static content can be cached while dynamic content with state injection can vary per invocation [4](#3-3) .

The test suite confirms this behavior with multiple scenarios showing how instructions are routed based on the presence of `static_instruction` [5](#3-4) .

Wiki pages you might want to explore:
- [LlmAgent Configuration (google/adk-python)](/wiki/google/adk-python#3.2)
- [Instructions and Prompts (google/adk-python)](/wiki/google/adk-python#3.7)

### Citations

**File:** src/google/adk/flows/llm_flows/instructions.py (L62-120)
```python
async def _build_instructions(
    invocation_context: 'InvocationContext',
    llm_request: 'LlmRequest',
) -> None:
  """Build and append instructions to the LLM request.

  Handles global instructions (deprecated), static_instruction, and
  dynamic instruction based on agent configuration.

  Args:
    invocation_context: The invocation context.
    llm_request: The LlmRequest to populate with instructions.
  """
  from ...agents.base_agent import BaseAgent

  agent = invocation_context.agent

  root_agent: BaseAgent = agent.root_agent

  # Handle global instructions (DEPRECATED - use GlobalInstructionPlugin instead)
  # TODO: Remove this code block when global_instruction field is removed
  if (
      hasattr(root_agent, 'global_instruction')
      and root_agent.global_instruction
  ):
    raw_si, bypass_state_injection = (
        await root_agent.canonical_global_instruction(
            ReadonlyContext(invocation_context)
        )
    )
    si = raw_si
    if not bypass_state_injection:
      si = await instructions_utils.inject_session_state(
          raw_si, ReadonlyContext(invocation_context)
      )
    llm_request.append_instructions([si])

  # Handle static_instruction - add via append_instructions
  if agent.static_instruction:
    from google.genai import _transformers

    # Convert ContentUnion to Content using genai transformer
    static_content = _transformers.t_content(agent.static_instruction)
    llm_request.append_instructions(static_content)

  # Handle instruction based on whether static_instruction exists
  if agent.instruction and not agent.static_instruction:
    # Only add to system instructions if no static instruction exists
    si = await _process_agent_instruction(agent, invocation_context)
    llm_request.append_instructions([si])
  elif agent.instruction and agent.static_instruction:
    # Static instruction exists, so add dynamic instruction to content
    from google.genai import types

    si = await _process_agent_instruction(agent, invocation_context)
    # Create user content for dynamic instruction
    dynamic_content = types.Content(role='user', parts=[types.Part(text=si)])
    llm_request.contents.append(dynamic_content)

```

**File:** src/google/adk/agents/llm_agent.py (L245-259)
```python
  **Impact on instruction field:**
  - When static_instruction is None: instruction → system_instruction
  - When static_instruction is set: instruction → user content (after static content)

  **Context Caching:**
  - **Implicit Cache**: Automatic caching by model providers (no config needed)
  - **Explicit Cache**: Cache explicitly created by user for instructions, tools and contents

  See below for more information of Implicit Cache and Explicit Cache
  Gemini API: https://ai.google.dev/gemini-api/docs/caching?lang=python
  Vertex API: https://cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview

  Setting static_instruction alone does NOT enable caching automatically.
  For explicit caching control, configure context_cache_config at App level.

```

**File:** tests/unittests/flows/llm_flows/test_instructions.py (L747-824)
```python
async def test_dynamic_instruction_without_static_goes_to_system(llm_backend):
  """Test that dynamic instructions go to system when no static instruction exists."""
  agent = LlmAgent(name="test_agent", instruction="Dynamic instruction content")

  invocation_context = await _create_invocation_context(agent)

  llm_request = LlmRequest()

  # Run the instruction processor
  async for _ in request_processor.run_async(invocation_context, llm_request):
    pass

  # Dynamic instruction should be added to system instructions
  assert llm_request.config.system_instruction == "Dynamic instruction content"
  assert len(llm_request.contents) == 0


@pytest.mark.parametrize("llm_backend", ["GOOGLE_AI", "VERTEX"])
@pytest.mark.asyncio
async def test_dynamic_instruction_with_static_not_in_system(llm_backend):
  """Test that dynamic instructions don't go to system when static instruction exists."""
  static_content = types.Content(
      role="user", parts=[types.Part(text="Static instruction content")]
  )
  agent = LlmAgent(
      name="test_agent",
      instruction="Dynamic instruction content",
      static_instruction=static_content,
  )

  invocation_context = await _create_invocation_context(agent)

  llm_request = LlmRequest()

  # Run the instruction processor
  async for _ in request_processor.run_async(invocation_context, llm_request):
    pass

  # Static instruction should be in system instructions
  # Dynamic instruction should be added as user content by instruction processor
  assert len(llm_request.contents) == 1
  assert llm_request.config.system_instruction == "Static instruction content"

  # Check that dynamic instruction was added as user content
  assert llm_request.contents[0].role == "user"
  assert len(llm_request.contents[0].parts) == 1
  assert llm_request.contents[0].parts[0].text == "Dynamic instruction content"


@pytest.mark.parametrize("llm_backend", ["GOOGLE_AI", "VERTEX"])
@pytest.mark.asyncio
async def test_dynamic_instruction_with_string_static_not_in_system(
    llm_backend,
):
  """Test that dynamic instructions go to user content when string static_instruction exists."""
  agent = LlmAgent(
      name="test_agent",
      instruction="Dynamic instruction content",
      static_instruction="Static instruction as string",
  )

  invocation_context = await _create_invocation_context(agent)

  llm_request = LlmRequest()

  # Run the instruction processor
  async for _ in request_processor.run_async(invocation_context, llm_request):
    pass

  # Static instruction should be in system instructions
  assert llm_request.config.system_instruction == "Static instruction as string"

  # Dynamic instruction should be added as user content
  assert len(llm_request.contents) == 1
  assert llm_request.contents[0].role == "user"
  assert len(llm_request.contents[0].parts) == 1
  assert llm_request.contents[0].parts[0].text == "Dynamic instruction content"

```
