from datetime import datetime, timedelta, timezone

import pytest

from worldstate import (
    Claim,
    Conflict,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    Provenance,
    Source,
    SpatialScope,
    StateAssertion,
    TemporalScope,
    Unknown,
    UnknownReason,
    Validity,
    WorldStateProvider,
    build_transition,
)

UTC = timezone.utc
AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
ENTITY = EntityRef("thing-1")
SOURCE = Source(
    source_id="source-1",
    source_type="example",
    version="v1",
)


def evidence(evidence_id: str, *, recorded_at: datetime = AT - timedelta(minutes=2)) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source=SOURCE,
        recorded_at=recorded_at,
    )


def claim(
    claim_id: str,
    value: str,
    evidence_id: str,
    *,
    spatial_scope: SpatialScope | None = None,
    temporal_scope: TemporalScope | None = None,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        entity=ENTITY,
        property_key="status",
        value=value,
        epistemic_mode=EpistemicMode.OBSERVED,
        provenance=Provenance(
            evidence_refs=(evidence_id,),
            source_refs=(SOURCE.source_id,),
            method="direct-observation",
        ),
        created_at=AT - timedelta(minutes=1),
        spatial_scope=spatial_scope,
        temporal_scope=temporal_scope,
    )


def assertion(assertion_id: str, value: str, evidence_id: str) -> StateAssertion:
    return StateAssertion(
        assertion_id=assertion_id,
        entity=ENTITY,
        property_key="status",
        value=value,
        epistemic_mode=EpistemicMode.OBSERVED,
        validity=Validity(resolved_at=AT),
        provenance=Provenance(
            evidence_refs=(evidence_id,),
            source_refs=(SOURCE.source_id,),
            method="reference-resolution",
        ),
        version="0.1",
    )


def test_in_memory_reference_engine_satisfies_provider_protocol() -> None:
    provider = InMemoryWorldState()
    assert isinstance(provider, WorldStateProvider)


def test_query_state_and_evidence_lookup() -> None:
    provider = InMemoryWorldState()
    provider.add_evidence(evidence("ev-a"))
    provider.add_claim(claim("claim-a", "ok", "ev-a"))

    result = provider.query_state(ENTITY, "status", AT)

    assert isinstance(result, StateAssertion)
    assert tuple(item.evidence_id for item in provider.get_evidence(result.assertion_id)) == (
        "ev-a",
    )


def test_future_evidence_is_not_visible_to_past_query() -> None:
    provider = InMemoryWorldState()
    provider.add_evidence(evidence("ev-a", recorded_at=AT + timedelta(minutes=1)))
    provider.add_claim(claim("claim-a", "ok", "ev-a"))

    result = provider.query_state(ENTITY, "status", AT)

    assert isinstance(result, Unknown)
    assert result.reason is UnknownReason.INSUFFICIENT_EVIDENCE


def test_snapshot_is_stable_across_ingest_order() -> None:
    left = InMemoryWorldState()
    right = InMemoryWorldState()

    ev_a = evidence("ev-a")
    ev_b = evidence("ev-b")
    claim_a = claim("claim-a", "ok", "ev-a")
    claim_b = claim("claim-b", "ok", "ev-b")

    for item in (ev_a, ev_b):
        left.add_evidence(item)
    for item in (claim_a, claim_b):
        left.add_claim(item)

    for item in (ev_b, ev_a):
        right.add_evidence(item)
    for item in (claim_b, claim_a):
        right.add_claim(item)

    first = left.get_snapshot(None, AT)
    replay = right.get_snapshot(None, AT)

    assert first.snapshot_id == replay.snapshot_id
    assert first.assertions[0].assertion_id == replay.assertions[0].assertion_id
    assert dict(first.source_versions) == {"source-1": "v1"}


def test_snapshot_exact_scope_does_not_assume_spatial_containment() -> None:
    provider = InMemoryWorldState()
    scope_a = SpatialScope(kind="reference", reference="scope-a")
    scope_b = SpatialScope(kind="reference", reference="scope-b")
    provider.add_evidence(evidence("ev-a"))
    provider.add_claim(
        claim("claim-a", "ok", "ev-a", spatial_scope=scope_a)
    )

    matching = provider.get_snapshot(scope_a, AT)
    non_matching = provider.get_snapshot(scope_b, AT)

    assert len(matching.assertions) == 1
    assert non_matching.assertions == ()
    assert non_matching.unknowns == ()
    assert non_matching.conflicts == ()


def test_conflict_is_cached_as_first_class_provider_result() -> None:
    provider = InMemoryWorldState()
    provider.add_evidence(evidence("ev-a"))
    provider.add_evidence(evidence("ev-b"))
    provider.add_claim(claim("claim-a", "open", "ev-a"))
    provider.add_claim(claim("claim-b", "closed", "ev-b"))

    result = provider.query_state(ENTITY, "status", AT)

    assert isinstance(result, Conflict)
    assert provider.get_conflicts(None) == (result,)
    assert tuple(item.evidence_id for item in provider.get_evidence(result.conflict_id)) == (
        "ev-a",
        "ev-b",
    )


def test_unknown_is_cached_as_first_class_provider_result() -> None:
    provider = InMemoryWorldState()

    result = provider.query_state(ENTITY, "status", AT)

    assert isinstance(result, Unknown)
    assert provider.get_unknowns(None) == (result,)


def test_relation_query_fails_closed_until_relation_claim_contract_is_normative() -> None:
    provider = InMemoryWorldState()

    result = provider.query_relation(
        ENTITY,
        "related_to",
        EntityRef("thing-2"),
        AT,
    )

    assert isinstance(result, Unknown)
    assert result.reason is UnknownReason.UNSUPPORTED_QUERY


def test_transition_history_is_deterministic_and_preserves_evidence() -> None:
    provider = InMemoryWorldState()
    provider.add_evidence(evidence("ev-a"))
    provider.add_evidence(evidence("ev-b"))
    before = assertion("state-a", "open", "ev-a")
    after = assertion("state-b", "closed", "ev-b")
    transition = build_transition(
        before,
        after,
        transition_time=AT + timedelta(minutes=5),
        reason="changed",
    )
    provider.add_transition(transition)

    history = provider.get_history(
        ENTITY,
        TemporalScope(
            start=AT,
            end=AT + timedelta(minutes=10),
        ),
    )

    assert history == (transition,)
    assert transition.provenance.evidence_refs == ("ev-a", "ev-b")
    assert tuple(item.evidence_id for item in provider.get_evidence(transition.transition_id)) == (
        "ev-a",
        "ev-b",
    )


def test_same_semantic_id_with_different_payload_is_rejected() -> None:
    provider = InMemoryWorldState()
    provider.add_evidence(evidence("ev-a"))

    with pytest.raises(ValueError, match="semantic ID collision"):
        provider.add_evidence(
            Evidence(
                evidence_id="ev-a",
                source=Source(source_id="source-2", source_type="example"),
                recorded_at=AT - timedelta(minutes=2),
            )
        )
