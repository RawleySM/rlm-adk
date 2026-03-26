"""Tests for LineageEnvelope split into LineageEdge + ProvenanceRecord.

Phase 2 of Telemetry Schema Refactor: the monolithic LineageEnvelope is
decomposed into two focused models (LineageEdge for tree-structure,
ProvenanceRecord for identity/context) while keeping LineageEnvelope as
a backward-compatible composite with .lineage and .provenance properties.

TDD Cycles:
  Cycle 1: LineageEdge and ProvenanceRecord importable from rlm_adk.types
  Cycle 2: LineageEnvelope.lineage / .provenance properties
  Cycle 3: LineageEnvelope.model_dump() backward compat (same keys)
  Cycle 4: _build_lineage() contract boundary
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cycle 1 -- LineageEdge and ProvenanceRecord are importable
# ---------------------------------------------------------------------------


class TestLineageEdgeImport:
    """LineageEdge can be imported from rlm_adk.types."""

    def test_lineage_edge_importable(self):
        from rlm_adk.types import LineageEdge

        assert LineageEdge is not None

    def test_provenance_record_importable(self):
        from rlm_adk.types import ProvenanceRecord

        assert ProvenanceRecord is not None

    def test_lineage_edge_is_base_model(self):
        from pydantic import BaseModel

        from rlm_adk.types import LineageEdge

        assert issubclass(LineageEdge, BaseModel)

    def test_provenance_record_is_base_model(self):
        from pydantic import BaseModel

        from rlm_adk.types import ProvenanceRecord

        assert issubclass(ProvenanceRecord, BaseModel)


# ---------------------------------------------------------------------------
# Cycle 2 -- LineageEnvelope.lineage / .provenance properties
# ---------------------------------------------------------------------------


class TestLineageEnvelopeProperties:
    """LineageEnvelope exposes .lineage -> LineageEdge and .provenance -> ProvenanceRecord."""

    def test_lineage_property_returns_lineage_edge(self):
        from rlm_adk.types import LineageEdge, LineageEnvelope

        env = LineageEnvelope(agent_name="test", depth=2, fanout_idx=1)
        edge = env.lineage
        assert isinstance(edge, LineageEdge)
        assert edge.depth == 2
        assert edge.fanout_idx == 1

    def test_provenance_property_returns_provenance_record(self):
        from rlm_adk.types import LineageEnvelope, ProvenanceRecord

        env = LineageEnvelope(
            agent_name="test_agent",
            depth=0,
            invocation_id="inv-123",
            session_id="sess-456",
        )
        prov = env.provenance
        assert isinstance(prov, ProvenanceRecord)
        assert prov.agent_name == "test_agent"
        assert prov.invocation_id == "inv-123"
        assert prov.session_id == "sess-456"

    def test_lineage_edge_contains_tree_fields(self):
        from rlm_adk.types import LineageEnvelope

        env = LineageEnvelope(
            agent_name="a",
            depth=3,
            fanout_idx=2,
            parent_depth=2,
            parent_fanout_idx=0,
            branch="left",
            terminal=True,
            decision_mode="execute_code",
            structured_outcome="validated",
        )
        edge = env.lineage
        assert edge.depth == 3
        assert edge.fanout_idx == 2
        assert edge.parent_depth == 2
        assert edge.parent_fanout_idx == 0
        assert edge.branch == "left"
        assert edge.terminal is True
        assert edge.decision_mode == "execute_code"
        assert edge.structured_outcome == "validated"

    def test_provenance_record_contains_identity_fields(self):
        from rlm_adk.types import LineageEnvelope

        env = LineageEnvelope(
            agent_name="test",
            depth=0,
            version="v1",
            invocation_id="inv-1",
            session_id="sess-1",
            output_schema_name="ReasoningOutput",
        )
        prov = env.provenance
        assert prov.version == "v1"
        assert prov.agent_name == "test"
        assert prov.invocation_id == "inv-1"
        assert prov.session_id == "sess-1"
        assert prov.output_schema_name == "ReasoningOutput"


# ---------------------------------------------------------------------------
# Cycle 3 -- LineageEnvelope.model_dump() backward compat
# ---------------------------------------------------------------------------

# The pre-split keys that LineageEnvelope.model_dump() MUST produce.
_PRE_SPLIT_KEYS = {
    "version",
    "agent_name",
    "depth",
    "fanout_idx",
    "parent_depth",
    "parent_fanout_idx",
    "branch",
    "invocation_id",
    "session_id",
    "output_schema_name",
    "decision_mode",
    "structured_outcome",
    "terminal",
}


class TestLineageEnvelopeModelDumpCompat:
    """model_dump() output shape is unchanged from the pre-split shape."""

    def test_model_dump_keys_match_pre_split(self):
        from rlm_adk.types import LineageEnvelope

        env = LineageEnvelope(agent_name="a", depth=0)
        dumped = env.model_dump()
        assert set(dumped.keys()) == _PRE_SPLIT_KEYS, (
            f"model_dump() keys changed. Extra: {set(dumped.keys()) - _PRE_SPLIT_KEYS}, "
            f"Missing: {_PRE_SPLIT_KEYS - set(dumped.keys())}"
        )

    def test_model_dump_values_match_pre_split(self):
        from rlm_adk.types import LineageEnvelope

        env = LineageEnvelope(
            agent_name="test",
            depth=2,
            fanout_idx=1,
            parent_depth=1,
            parent_fanout_idx=0,
            branch="main",
            invocation_id="inv-x",
            session_id="sess-y",
            output_schema_name="ReasoningOutput",
            decision_mode="execute_code",
            structured_outcome="validated",
            terminal=True,
        )
        dumped = env.model_dump()
        assert dumped == {
            "version": "v1",
            "agent_name": "test",
            "depth": 2,
            "fanout_idx": 1,
            "parent_depth": 1,
            "parent_fanout_idx": 0,
            "branch": "main",
            "invocation_id": "inv-x",
            "session_id": "sess-y",
            "output_schema_name": "ReasoningOutput",
            "decision_mode": "execute_code",
            "structured_outcome": "validated",
            "terminal": True,
        }

    def test_model_dump_no_new_keys(self):
        """Ensure no new keys are added by the split."""
        from rlm_adk.types import LineageEnvelope

        env = LineageEnvelope(agent_name="a", depth=0)
        dumped = env.model_dump()
        extra = set(dumped.keys()) - _PRE_SPLIT_KEYS
        assert not extra, f"New keys found in model_dump(): {extra}"

    def test_model_dump_no_missing_keys(self):
        """Ensure no keys are lost by the split."""
        from rlm_adk.types import LineageEnvelope

        env = LineageEnvelope(agent_name="a", depth=0)
        dumped = env.model_dump()
        missing = _PRE_SPLIT_KEYS - set(dumped.keys())
        assert not missing, f"Missing keys in model_dump(): {missing}"


# ---------------------------------------------------------------------------
# Cycle 4 -- _build_lineage() contract boundary at reasoning.py:79
# ---------------------------------------------------------------------------


def _make_mock_callback_context(
    *,
    agent_name: str = "reasoning_agent",
    depth: int = 0,
    fanout_idx: int | None = None,
    parent_depth: int | None = None,
    parent_fanout_idx: int | None = None,
    output_schema_name: str | None = None,
    branch: str | None = None,
    invocation_id: str | None = "inv-test-001",
    session_id: str | None = "sess-test-001",
):
    """Build a mock CallbackContext for _build_lineage() testing."""
    from types import SimpleNamespace

    agent = SimpleNamespace(
        name=agent_name,
        _rlm_depth=depth,
        _rlm_fanout_idx=fanout_idx,
        _rlm_parent_depth=parent_depth,
        _rlm_parent_fanout_idx=parent_fanout_idx,
        _rlm_output_schema_name=output_schema_name,
    )
    session = SimpleNamespace(id=session_id)
    inv = SimpleNamespace(
        agent=agent,
        branch=branch,
        invocation_id=invocation_id,
        session=session,
    )
    ctx = SimpleNamespace(_invocation_context=inv)
    return ctx


class TestBuildLineageContract:
    """_build_lineage() returns a LineageEnvelope whose model_dump() matches pre-split shape."""

    def test_build_lineage_returns_lineage_envelope(self):
        from rlm_adk.callbacks.reasoning import _build_lineage
        from rlm_adk.types import LineageEnvelope

        ctx = _make_mock_callback_context()
        result = _build_lineage(ctx)
        assert isinstance(result, LineageEnvelope)

    def test_build_lineage_model_dump_has_pre_split_keys(self):
        from rlm_adk.callbacks.reasoning import _build_lineage

        ctx = _make_mock_callback_context(
            agent_name="test_agent",
            depth=1,
            fanout_idx=2,
            parent_depth=0,
            parent_fanout_idx=None,
            output_schema_name="ReasoningOutput",
            branch="main",
            invocation_id="inv-abc",
            session_id="sess-def",
        )
        result = _build_lineage(ctx)
        dumped = result.model_dump()
        assert set(dumped.keys()) == _PRE_SPLIT_KEYS

    def test_build_lineage_model_dump_values(self):
        from rlm_adk.callbacks.reasoning import _build_lineage

        ctx = _make_mock_callback_context(
            agent_name="test_agent",
            depth=1,
            fanout_idx=2,
            parent_depth=0,
            parent_fanout_idx=None,
            output_schema_name="ReasoningOutput",
            branch="main",
            invocation_id="inv-abc",
            session_id="sess-def",
        )
        result = _build_lineage(ctx)
        dumped = result.model_dump()
        assert dumped["agent_name"] == "test_agent"
        assert dumped["depth"] == 1
        assert dumped["fanout_idx"] == 2
        assert dumped["parent_depth"] == 0
        assert dumped["parent_fanout_idx"] is None
        assert dumped["output_schema_name"] == "ReasoningOutput"
        assert dumped["branch"] == "main"
        assert dumped["invocation_id"] == "inv-abc"
        assert dumped["session_id"] == "sess-def"
        assert dumped["version"] == "v1"
        assert dumped["decision_mode"] == "unknown"
        assert dumped["structured_outcome"] == "not_applicable"
        assert dumped["terminal"] is False

    def test_build_lineage_has_lineage_property(self):
        """After split, _build_lineage().lineage returns a LineageEdge."""
        from rlm_adk.callbacks.reasoning import _build_lineage
        from rlm_adk.types import LineageEdge

        ctx = _make_mock_callback_context(depth=3, fanout_idx=1)
        result = _build_lineage(ctx)
        edge = result.lineage
        assert isinstance(edge, LineageEdge)
        assert edge.depth == 3
        assert edge.fanout_idx == 1

    def test_build_lineage_has_provenance_property(self):
        """After split, _build_lineage().provenance returns a ProvenanceRecord."""
        from rlm_adk.callbacks.reasoning import _build_lineage
        from rlm_adk.types import ProvenanceRecord

        ctx = _make_mock_callback_context(
            agent_name="test", invocation_id="inv-1", session_id="sess-1"
        )
        result = _build_lineage(ctx)
        prov = result.provenance
        assert isinstance(prov, ProvenanceRecord)
        assert prov.agent_name == "test"
        assert prov.invocation_id == "inv-1"
