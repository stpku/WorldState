from datetime import datetime, timedelta, timezone
from pathlib import Path

from examples.providers.external import (
    DirectExternalSource,
    DirectExternalWorldStateProvider,
    ExternalStateRecord,
)
from examples.providers.projection import (
    ExternalRecordStore,
    ProjectionWorldStateProvider,
    SoRRecord,
)
from worldstate import (
    Claim,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    Provenance,
    Source,
    StateAssertion,
    Unknown,
    UnknownReason,
)
from worldstate.conformance import (
    ExpectedResultKind,
    ProviderProbe,
    check_provider_conformance,
)

UTC = timezone.utc
AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
ENTITY = EntityRef("thing-1")
UNKNOWN_ENTITY = EntityRef("thing-missing")


def native_provider() -> InMemoryWorldState:
    provider = InMemoryWorldState()
    source = Source(source_id="native-source", source_type="example", version="v1")
    provider.add_evidence(
        Evidence(
            evidence_id="ev-native",
            source=source,
            recorded_at=AT - timedelta(minutes=2),
        )
    )
    provider.add_claim(
        Claim(
            claim_id="claim-native",
            entity=ENTITY,
            property_key="status",
            value="ok",
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=("ev-native",),
                source_refs=(source.source_id,),
                method="direct-observation",
            ),
            created_at=AT - timedelta(minutes=1),
        )
    )
    return provider


def projection_provider() -> tuple[ExternalRecordStore, ProjectionWorldStateProvider]:
    store = ExternalRecordStore()
    store.put(
        SoRRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="ok",
            updated_at=AT - timedelta(minutes=1),
            version="v1",
        )
    )
    return store, ProjectionWorldStateProvider(store)


def direct_provider() -> tuple[DirectExternalSource, DirectExternalWorldStateProvider]:
    source = DirectExternalSource(source_version="v1")
    source.put(
        ExternalStateRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="ok",
            updated_at=AT - timedelta(minutes=1),
            record_version="r1",
        )
    )
    return source, DirectExternalWorldStateProvider(source)


def probes() -> tuple[ProviderProbe, ...]:
    return (
        ProviderProbe(
            entity=ENTITY,
            property_key="status",
            at=AT,
            expected_kind=ExpectedResultKind.ASSERTION,
            expected_value="ok",
        ),
        ProviderProbe(
            entity=UNKNOWN_ENTITY,
            property_key="status",
            at=AT,
            expected_kind=ExpectedResultKind.UNKNOWN,
            expected_unknown_reason=UnknownReason.NO_EVIDENCE,
        ),
    )


def test_native_projection_and_direct_external_pass_same_conformance_suite() -> None:
    _, projected = projection_provider()
    _, direct = direct_provider()
    providers = (native_provider(), projected, direct)

    reports = tuple(check_provider_conformance(provider, probes()) for provider in providers)

    assert all(report.passed for report in reports), reports
    assert {report.provider_name for report in reports} == {
        "InMemoryWorldState",
        "ProjectionWorldStateProvider",
        "DirectExternalWorldStateProvider",
    }


def test_projection_reads_external_sor_without_owning_update_path() -> None:
    store, provider = projection_provider()

    first = provider.query_state(ENTITY, "status", AT)
    assert isinstance(first, StateAssertion)
    assert first.value == "ok"

    store.put(
        SoRRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="changed",
            updated_at=AT + timedelta(minutes=1),
            version="v2",
        )
    )

    second = provider.query_state(ENTITY, "status", AT + timedelta(minutes=2))
    assert isinstance(second, StateAssertion)
    assert second.value == "changed"
    assert first.assertion_id != second.assertion_id
    assert not hasattr(provider, "put")


def test_external_provider_failure_becomes_explicit_unknown() -> None:
    source, provider = direct_provider()
    source.available = False

    result = provider.query_state(ENTITY, "status", AT)
    snapshot = provider.get_snapshot(None, AT)

    assert isinstance(result, Unknown)
    assert result.reason is UnknownReason.PROVIDER_UNAVAILABLE
    assert len(snapshot.unknowns) == 1
    assert snapshot.unknowns[0].reason is UnknownReason.PROVIDER_UNAVAILABLE
    assert snapshot.assertions == ()


def test_direct_external_provider_does_not_use_reference_engine() -> None:
    path = Path(__file__).parents[1] / "examples" / "providers" / "external.py"
    text = path.read_text(encoding="utf-8")

    assert "ReferenceResolver" not in text
    assert "InMemoryWorldState" not in text
