"""Phase 2 tests: child orchestrator factory (create_child_orchestrator)."""

from rlm_adk.agent import create_child_orchestrator, create_reasoning_agent


class TestChildOrchestratorFactory:
    """Tests for create_child_orchestrator()."""

    def test_child_has_correct_depth(self):
        child = create_child_orchestrator(
            model="gemini-test", depth=2, prompt="test query"
        )
        assert child.depth == 2

    def test_child_output_key_depth_suffixed(self):
        child = create_child_orchestrator(
            model="gemini-test", depth=2, prompt="test query"
        )
        assert child.reasoning_agent.output_key == "reasoning_output@d2"

    def test_child_not_persistent(self):
        child = create_child_orchestrator(
            model="gemini-test", depth=1, prompt="test query"
        )
        assert child.persistent is False

    def test_child_uses_child_instruction(self):
        child = create_child_orchestrator(
            model="gemini-test", depth=1, prompt="test query"
        )
        si = child.reasoning_agent.static_instruction
        # Should NOT contain repo processing or repomix-specific content
        assert "Repository Processing" not in si
        assert "probe_repo" not in si
        assert "pack_repo" not in si
        assert "shard_repo" not in si
        assert "repomix" not in si.lower()
        # Should still contain core tool descriptions
        assert "execute_code" in si
        assert "set_model_response" in si
        assert "llm_query" in si
        assert "llm_query_batched" in si

    def test_child_name_includes_depth(self):
        child = create_child_orchestrator(
            model="gemini-test", depth=3, prompt="test query"
        )
        assert "d3" in child.name
        assert "child_orchestrator" in child.name

    def test_child_output_schema_passthrough(self):
        from pydantic import BaseModel

        class MySchema(BaseModel):
            answer: str

        child = create_child_orchestrator(
            model="gemini-test", depth=1, prompt="test", output_schema=MySchema
        )
        assert child.output_schema is MySchema

    def test_parent_reasoning_agent_has_repomix(self):
        """Default create_reasoning_agent() includes repomix skill instructions."""
        agent = create_reasoning_agent(model="gemini-test")
        si = agent.static_instruction
        assert "repomix" in si.lower() or "probe_repo" in si

    def test_parent_reasoning_agent_can_limit_prompt_visible_skills(self):
        agent = create_reasoning_agent(
            model="gemini-test",
            enabled_skills=["polya-narrative"],
        )
        si = agent.static_instruction
        assert "polya-narrative" in si
        assert "## repomix-repl-helpers" not in si
        assert "## polya-understand" not in si

    def test_child_reasoning_agent_include_contents_none(self):
        """Child agents (depth > 0) must use include_contents='none' so they
        only see the current turn's prompt, not the parent's full history."""
        child = create_child_orchestrator(
            model="gemini-test", depth=1, prompt="child query"
        )
        assert child.reasoning_agent.include_contents == "none"

    def test_child_reasoning_agent_include_contents_none_deep(self):
        """Deeper children (depth > 1) also get include_contents='none'."""
        child = create_child_orchestrator(
            model="gemini-test", depth=3, prompt="deep child query"
        )
        assert child.reasoning_agent.include_contents == "none"

    def test_root_reasoning_agent_include_contents_default(self):
        """Root agents (depth 0) must keep include_contents='default'."""
        agent = create_reasoning_agent(model="gemini-test")
        assert agent.include_contents == "default"

    def test_create_rlm_orchestrator_persists_enabled_skills(self):
        from rlm_adk.agent import create_rlm_orchestrator

        orchestrator = create_rlm_orchestrator(
            model="gemini-test",
            enabled_skills=["polya-understand"],
        )
        assert orchestrator.enabled_skills == ("polya-understand",)
