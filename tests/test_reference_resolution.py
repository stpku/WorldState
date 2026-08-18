from datetime import datetime, timedelta, timezone

from worldstate import (
    Claim,
    Conflict,
    EntityRef,
    EpistemicMode,
    Provenance,
    StateAssertion,
    TemporalScope,
    Uncertainty,
    Unknown,
    UnknownReason,
)
from worldstate.resolution import ReferenceResolver, ResolutionInputs

UTC = timezone.utc
AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
ENTITY = EntityRef("thing-1")


def claim(
    claim_id: str,
    value: object,
    *,
    evidence_ref: str,
    source_ref: str = "source-1",
    mode: EpistemicMode = EpistemicMode.OBSERVED,
    temporal_scope: TemporalScope | None = None,
    uncertainty: Uncertainty | None = None,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        entity=ENTITY,
        property_key="status",
        value=value,  # type: ignore[arg-type]
        epistemic_mode=mode,
        provenance=Provenance(
            evidence_refs=(evidence_ref,),
            source_refs=(source_ref,),
            method="direct-observation",
        ),
        created_at=AT - timedelta(minutes=1),
        temporal_scope=temporal_scope,
        uncertainty=uncertainty,
    )


def available(*evidence_refs: str) -> ResolutionInputs:
    return ResolutionInputs(
        evidence_refs=frozenset(evidence_refs),
        source_refs=frozenset({"source-1"}),
    )


def test_no_claims_resolves_to_stable_unknown() -> None:
    resolver = ReferenceResolver()

    first = resolver.resolve_state((), ENTITY, "status", AT)
    second = resolver.resolve_state((), ENTITY, "status", AT)

    assert isinstance(first, Unknown)
    assert first.reason is UnknownReason.NO_EVIDENCE
    assert first.unknown_id == second.unknown_id  # type: ignore[union-attr]


def test_missing_referenced_evidence_fails_closed() -> None:
    resolver = ReferenceResolver()
    unsupported = claim("claim-a", "ok", evidence_ref="ev-missing")

    result = resolver.resolve_state(
        (unsupported,),
        ENTITY,
        "status",
        AT,
        available=available(),
    )

    assert isinstance(result, Unknown)
    assert result.reason is UnknownReason.INSUFFICIENT_EVIDENCE
    assert result.missing == ("ev-missing",)


def test_one_supported_claim_resolves_to_assertion() -> None:
    resolver = ReferenceResolver()
    supported = claim("claim-a", "ok", evidence_ref="ev-a")

    result = resolver.resolve_state(
        (supported,),
        ENTITY,
        "status",
        AT,
        available=available("ev-a"),
    )

    assert isinstance(result, StateAssertion)
    assert result.value == "ok"
    assert result.epistemic_mode is EpistemicMode.OBSERVED
    assert result.provenance.evidence_refs == ("ev-a",)


def test_agreeing_claims_aggregate_provenance_deterministically() -> None:
    resolver = ReferenceResolver()
    left = claim("claim-b", "ok", evidence_ref="ev-b")
    right = claim("claim-a", "ok", evidence_ref="ev-a")
    inputs = available("ev-a", "ev-b")

    first = resolver.resolve_state(
        (left, right),
        ENTITY,
        "status",
        AT,
        available=inputs,
    )
    replay = resolver.resolve_state(
        (right, left),
        ENTITY,
        "status",
        AT,
        available=inputs,
    )

    assert isinstance(first, StateAssertion)
    assert isinstance(replay, StateAssertion)
    assert first.provenance.evidence_refs == ("ev-a", "ev-b")
    assert first.assertion_id == replay.assertion_id


def test_incompatible_values_are_preserved_as_conflict() -> None:
    resolver = ReferenceResolver()
    left = claim("claim-a", "open", evidence_ref="ev-a")
    right = claim("claim-b", "closed", evidence_ref="ev-b")

    result = resolver.resolve_state(
        (right, left),
        ENTITY,
        "status",
        AT,
        available=available("ev-a", "ev-b"),
    )

    assert isinstance(result, Conflict)
    assert result.candidate_refs == ("claim-a", "claim-b")
    assert result.evidence_refs == ("ev-a", "ev-b")


def test_epistemic_mode_disagreement_is_conflict() -> None:
    resolver = ReferenceResolver()
    observed = claim("claim-a", "ok", evidence_ref="ev-a")
    predicted = claim(
        "claim-b",
        "ok",
        evidence_ref="ev-b",
        mode=EpistemicMode.PREDICTED,
    )

    result = resolver.resolve_state(
        (observed, predicted),
        ENTITY,
        "status",
        AT,
        available=available("ev-a", "ev-b"),
    )

    assert isinstance(result, Conflict)


def test_expired_claim_resolves_to_outside_validity_unknown() -> None:
    resolver = ReferenceResolver()
    expired = claim(
        "claim-a",
        "ok",
        evidence_ref="ev-a",
        temporal_scope=TemporalScope(end=AT - timedelta(seconds=1)),
    )

    result = resolver.resolve_state(
        (expired,),
        ENTITY,
        "status",
        AT,
        available=available("ev-a"),
    )

    assert isinstance(result, Unknown)
    assert result.reason is UnknownReason.OUTSIDE_VALIDITY


def test_confidence_is_not_used_as_implicit_ranking_policy() -> None:
    resolver = ReferenceResolver()
    low = claim(
        "claim-a",
        "ok",
        evidence_ref="ev-a",
        uncertainty=Uncertainty(confidence=0.4, method="method-a"),
    )
    high = claim(
        "claim-b",
        "ok",
        evidence_ref="ev-b",
        uncertainty=Uncertainty(confidence=0.9, method="method-b"),
    )

    result = resolver.resolve_state(
        (low, high),
        ENTITY,
        "status",
        AT,
        available=available("ev-a", "ev-b"),
    )

    assert isinstance(result, StateAssertion)
    assert result.value == "ok"
    assert result.uncertainty is None
