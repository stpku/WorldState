from datetime import datetime, timedelta, timezone

from worldstate import (
    Claim,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    Provenance,
    Source,
    UnknownReason,
)
from worldstate.conformance import (
    ExpectedResultKind,
    ProviderProbe,
    check_provider_conformance,
)

UTC = timezone.utc
AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
SOURCE = Source(source_id="source-1", source_type="example", version="v1")


def add_supported_claim(
    provider: InMemoryWorldState,
    *,
    entity: EntityRef,
    property_key: str,
    claim_id: str,
    evidence_id: str,
    value: str,
) -> None:
    provider.add_evidence(
        Evidence(
            evidence_id=evidence_id,
            source=SOURCE,
            recorded_at=AT - timedelta(minutes=2),
        )
    )
    provider.add_claim(
        Claim(
            claim_id=claim_id,
            entity=entity,
            property_key=property_key,
            value=value,
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=(evidence_id,),
                source_refs=(SOURCE.source_id,),
                method="direct-observation",
            ),
            created_at=AT - timedelta(minutes=1),
        )
    )


def test_reference_provider_passes_reusable_conformance_suite() -> None:
    provider = InMemoryWorldState()
    asserted_entity = EntityRef("thing-asserted")
    conflict_entity = EntityRef("thing-conflict")
    unknown_entity = EntityRef("thing-unknown")

    add_supported_claim(
        provider,
        entity=asserted_entity,
        property_key="status",
        claim_id="claim-a",
        evidence_id="ev-a",
        value="ok",
    )
    add_supported_claim(
        provider,
        entity=conflict_entity,
        property_key="status",
        claim_id="claim-b",
        evidence_id="ev-b",
        value="open",
    )
    add_supported_claim(
        provider,
        entity=conflict_entity,
        property_key="status",
        claim_id="claim-c",
        evidence_id="ev-c",
        value="closed",
    )

    report = check_provider_conformance(
        provider,
        (
            ProviderProbe(
                entity=asserted_entity,
                property_key="status",
                at=AT,
                expected_kind=ExpectedResultKind.ASSERTION,
                expected_value="ok",
            ),
            ProviderProbe(
                entity=conflict_entity,
                property_key="status",
                at=AT,
                expected_kind=ExpectedResultKind.CONFLICT,
            ),
            ProviderProbe(
                entity=unknown_entity,
                property_key="status",
                at=AT,
                expected_kind=ExpectedResultKind.UNKNOWN,
                expected_unknown_reason=UnknownReason.NO_EVIDENCE,
            ),
        ),
    )

    assert report.passed, report.violations
    assert report.checks > 0
