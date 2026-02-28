from rlm_adk.agent import create_reasoning_agent
from rlm_adk.types import ReasoningOutput

# 1. Backward compat: no tools, no output_schema
agent_basic = create_reasoning_agent(model="gemini-fake")
assert agent_basic.tools == []
assert agent_basic.output_schema is None
assert agent_basic.name == "reasoning_agent"
print("Backward compat: tools=[], output_schema=None, name='reasoning_agent'")

# 2. With output_schema
agent_schema = create_reasoning_agent(model="gemini-fake", output_schema=ReasoningOutput)
assert agent_schema.output_schema == ReasoningOutput
print("With output_schema:", agent_schema.output_schema.__name__)

# 3. With a tool
def dummy_tool(x: str) -> str:
    """A dummy tool."""
    return x

agent_tools = create_reasoning_agent(model="gemini-fake", tools=[dummy_tool])
assert len(agent_tools.tools) == 1
print("With tools: len(tools)=%d" % len(agent_tools.tools))

# 4. Both together
agent_both = create_reasoning_agent(
    model="gemini-fake",
    tools=[dummy_tool],
    output_schema=ReasoningOutput,
)
assert len(agent_both.tools) == 1
assert agent_both.output_schema == ReasoningOutput
print("Both: tools=%d, output_schema=%s" % (len(agent_both.tools), agent_both.output_schema.__name__))

# 5. Transfer disallowed (safety)
assert agent_basic.disallow_transfer_to_parent is True
assert agent_basic.disallow_transfer_to_peers is True
print("Transfers disallowed: parent=%s, peers=%s" % (
    agent_basic.disallow_transfer_to_parent,
    agent_basic.disallow_transfer_to_peers,
))

# 6. include_contents changes with tools
assert agent_basic.include_contents == "none"  # no tools -> manual history
assert agent_tools.include_contents == "default"  # tools -> ADK manages
print("include_contents: no-tools=%r, with-tools=%r" % (
    agent_basic.include_contents, agent_tools.include_contents,
))

print()
print("PASS: agent factory backward-compatible and accepts tools+output_schema")
