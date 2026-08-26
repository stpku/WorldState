from __future__ import annotations

from datetime import datetime, timedelta

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
    TemporalScope,
)

SHIPMENT = EntityRef(
    "shipment-001",
    entity_type="shipment",
    namespace="example-cold-chain",
)
SHIPMENT_STATUS = "shipment_status"
TEMPERATURE_C = "temperature_c"


def build_registry_provider(
    at: datetime,
    *,
    status: str = "in_transit",
    version: str = "registry-v1",
) -> tuple[ExternalRecordStore, ProjectionWorldStateProvider]:
    """Build an external shipment-registry projection owned outside WorldState."""

    store = ExternalRecordStore()
    store.put(
        SoRRecord(
            record_id="shipment-registry-001",
            entity=SHIPMENT,
            property_key=SHIPMENT_STATUS,
            value=status,
            updated_at=at - timedelta(minutes=1),
            version=version,
        )
    )
    return store, ProjectionWorldStateProvider(store)


def update_registry(
    store: ExternalRecordStore,
    at: datetime,
    *,
    status: str,
    version: str,
) -> None:
    store.put(
        SoRRecord(
            record_id="shipment-registry-001",
            entity=SHIPMENT,
            property_key=SHIPMENT_STATUS,
            value=status,
            updated_at=at - timedelta(seconds=30),
            version=version,
        )
    )


def build_temperature_provider(
    at: datetime,
    *,
    temperature_c: float = 4.0,
    source_version: str = "sensor-v1",
    record_version: str = "reading-v1",
    validity_minutes: int = 10,
) -> tuple[DirectExternalSource, DirectExternalWorldStateProvider]:
    """Build a direct external temperature source with bounded reading validity."""

    source = DirectExternalSource(source_version=source_version)
    source.put(
        ExternalStateRecord(
            record_id="temperature-reading-001",
            entity=SHIPMENT,
            property_key=TEMPERATURE_C,
            value=temperature_c,
            updated_at=at - timedelta(seconds=30),
            record_version=record_version,
            temporal_scope=TemporalScope(
                start=at - timedelta(minutes=1),
                end=at + timedelta(minutes=validity_minutes),
            ),
        )
    )
    return source, DirectExternalWorldStateProvider(source)


def update_temperature(
    source: DirectExternalSource,
    at: datetime,
    *,
    temperature_c: float,
    source_version: str,
    record_version: str,
    validity_minutes: int = 10,
) -> None:
    source.source_version = source_version
    source.put(
        ExternalStateRecord(
            record_id="temperature-reading-001",
            entity=SHIPMENT,
            property_key=TEMPERATURE_C,
            value=temperature_c,
            updated_at=at - timedelta(seconds=30),
            record_version=record_version,
            temporal_scope=TemporalScope(
                start=at - timedelta(minutes=1),
                end=at + timedelta(minutes=validity_minutes),
            ),
        )
    )


def build_conflicting_temperature_provider(at: datetime) -> InMemoryWorldState:
    """Build two independently supported, materially incompatible sensor readings."""

    provider = InMemoryWorldState()
    for suffix, value in (("a", 4.0), ("b", 8.5)):
        source = Source(
            source_id=f"cold-chain-sensor-{suffix}",
            source_type="temperature-sensor",
            version="calibration-v1",
        )
        evidence = Evidence(
            evidence_id=f"cold-chain-temperature-ev-{suffix}",
            source=source,
            recorded_at=at - timedelta(seconds=30),
        )
        provider.add_evidence(evidence)
        provider.add_claim(
            Claim(
                claim_id=f"cold-chain-temperature-claim-{suffix}",
                entity=SHIPMENT,
                property_key=TEMPERATURE_C,
                value=value,
                epistemic_mode=EpistemicMode.OBSERVED,
                provenance=Provenance(
                    evidence_refs=(evidence.evidence_id,),
                    source_refs=(source.source_id,),
                    method="direct-observation",
                ),
                created_at=at - timedelta(seconds=20),
                temporal_scope=TemporalScope(
                    start=at - timedelta(minutes=1),
                    end=at + timedelta(minutes=10),
                ),
            )
        )
    return provider
