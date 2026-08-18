from datetime import datetime, timedelta, timezone
from pathlib import Path

from examples.integrations.agentreality_wire import (
    AGENTREALITY_WORLDSTATE_PROJECTION_REVISION,
    project_query_result_for_agentreality,
    snapshot_ref,
)
from examples.providers.external import (
    DirectExternalSource,
    DirectExternalWorldStateProvider,
)
from worldstate import (
    Claim,
    Conflict,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    Provenance,
    Source,
    StateAssertion,
    TemporalScope,
    Unknown,
)

UTC = timezone.utc
AT = datetime(2026, 8, 18, 15, 0, tzinfo=UTC)
ENTITY = EntityRef(
    "thing-1",
    entity_type="example",
    namespace="compatibility-test",
)


def _provider(*, conflict: bool = False) -> InMemoryWorldState:
    provider = InMemoryWorldState()
    source_a = Source(source_id="source-a", source_type="example", version="v1")
    evidence_a = Evidence(
        evidence_id="evidence-a",
        source=source_a,
        recorded_at=AT - timedelta(minutes=2),
    )
    provider.add_evidence(evidence_a)
    provider.add_claim(
        Claim(
            claim_id="claim-a",
            entity=ENTITY,
            property_key="status",
            value={"state": "open", "sequence": [1, 2]},
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=(evidence_a.evidence_id,),
                source_refs=(source_a.source_id,),
                method="direct-observation",
            ),
            created_at=AT - timedelta(minutes=1),
            temporal_scope=TemporalScope(
                start=AT - timedelta(minutes=10),
                end=AT + timedelta(minutes=10),
            ),
        )
    )
    if conflict:
        source_b = Source(source_id="source-b", source_type="example", version="v1")
        evidence_b = Evidence(
            evidence_id="evidence-b",
            source=source_b,
            recorded_at=AT - timedelta(minutes=2),
        )
        provider.add_evidence(evidence_b)
        provider.add_claim(
            Claim(
                claim_id="claim-b",
                entity=ENTITY,
                property_key="status",
                value={"state": "closed", "sequence": [1, 2]},
                epistemic_mode=EpistemicMode.OBSERVED,
                provenance=Provenance(
                    evidence_refs=(evidence_b.evidence_id,),
                    source_refs=(source_b.source_id,),
                    method="direct-observation",
                ),
                created_at=AT - timedelta(minutes=1),
                temporal_scope=TemporalScope(
                    start=AT - timedelta(minutes=10),
                    end=AT + timedelta(minutes=10),
                ),
            )
        )
    return provider


def test_assertion_wire_matches_current_agentreality_projection_contract() -> None:
    provider = _provider()
    result = provider.query_state(ENTITY, "status", AT)

    assert isinstance(result, StateAssertion)
    wire = project_query_result_for_agentreality(result)

    assert set(wire) == {
        "kind",
        "assertionId",
        "entityId",
        "propertyKey",
        "value",
        "epistemicMode",
        "validity",
        "version",
        "evidenceRefs",
        "sourceRefs",
    }
    assert wire["kind"] == "assertion"
    assert wire["assertionId"] == result.assertion_id
    assert wire["entityId"] == "thing-1"
    assert wire["propertyKey"] == "status"
    assert wire["value"] == {"state": "open", "sequence": [1, 2]}
    assert wire["epistemicMode"] == "observed"
    assert wire["validity"] == {
        "resolvedAt": "2026-08-18T15:00:00.000Z",
        "validFrom": "2026-08-18T14:50:00.000Z",
        "validUntil": "2026-08-18T15:10:00.000Z",
    }
    assert wire["evidenceRefs"] == ["worldstate://evidence/evidence-a"]
    assert wire["sourceRefs"] == ["worldstate://source/source-a"]
    assert snapshot_ref("snap-1") == "worldstate://snapshot/snap-1"


def test_unknown_wire_preserves_unknown_semantics_and_missing_refs() -> None:
    provider = InMemoryWorldState()
    source = Source(source_id="source-a", source_type="example")
    provider.add_claim(
        Claim(
            claim_id="claim-unsupported",
            entity=ENTITY,
            property_key="status",
            value="open",
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=("missing-evidence",),
                source_refs=(source.source_id,),
                method="direct-observation",
            ),
            created_at=AT - timedelta(minutes=1),
        )
    )

    result = provider.query_state(ENTITY, "status", AT)
    assert isinstance(result, Unknown)

    wire = project_query_result_for_agentreality(result)
    assert wire == {
        "kind": "unknown",
        "unknownId": result.unknown_id,
        "reason": "insufficient_evidence",
        "asOf": "2026-08-18T15:00:00.000Z",
        "missing": ["missing-evidence", "source-a"],
    }


def test_conflict_wire_preserves_candidates_and_evidence_without_policy() -> None:
    provider = _provider(conflict=True)
    result = provider.query_state(ENTITY, "status", AT)

    assert isinstance(result, Conflict)
    wire = project_query_result_for_agentreality(result)

    assert wire["kind"] == "conflict"
    assert wire["conflictId"] == result.conflict_id
    assert wire["candidateRefs"] == ["claim-a", "claim-b"]
    assert wire["evidenceRefs"] == [
        "worldstate://evidence/evidence-a",
        "worldstate://evidence/evidence-b",
    ]
    assert "disposition" not in wire
    assert "blocked" not in wire


def test_provider_unavailability_projects_as_unknown_not_positive_state() -> None:
    source = DirectExternalSource(source_version="v1")
    provider = DirectExternalWorldStateProvider(source)
    source.available = False

    result = provider.query_state(ENTITY, "status", AT)
    assert isinstance(result, Unknown)

    wire = project_query_result_for_agentreality(result)
    assert wire["kind"] == "unknown"
    assert wire["reason"] == "provider_unavailable"


def test_m4_fixture_is_outside_core_and_has_point_in_time_revision_pin() -> None:
    core_root = Path(__file__).parents[1] / "src" / "worldstate"
    core_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted(core_root.glob("*.py"))
    )

    assert "agentreality" not in core_text
    assert AGENTREALITY_WORLDSTATE_PROJECTION_REVISION.startswith("sha256:")
    assert len(AGENTREALITY_WORLDSTATE_PROJECTION_REVISION) == len("sha256:") + 64
