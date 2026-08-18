from __future__ import annotations

from datetime import datetime

from examples.providers.projection import (
    ExternalRecordStore,
    ProjectionWorldStateProvider,
    SoRRecord,
)
from worldstate import EntityRef, TemporalScope

REGISTRY_ENTITY = EntityRef(
    "organization-1",
    entity_type="organization",
    namespace="example-registry",
)
REGISTRY_PROPERTY = "registration_status"


def build_registry_provider(
    effective_at: datetime,
) -> tuple[ExternalRecordStore, ProjectionWorldStateProvider]:
    """Build a low-frequency authoritative registry projection scenario."""
    store = ExternalRecordStore()
    store.put(
        SoRRecord(
            record_id="registry-record-1",
            entity=REGISTRY_ENTITY,
            property_key=REGISTRY_PROPERTY,
            value="active",
            updated_at=effective_at,
            version="registry-v1",
            temporal_scope=TemporalScope(start=effective_at),
        )
    )
    return store, ProjectionWorldStateProvider(store)
