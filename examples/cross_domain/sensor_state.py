from __future__ import annotations

from datetime import datetime, timedelta

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

SENSOR_ENTITY = EntityRef(
    "sensor-node-1",
    entity_type="sensor_node",
    namespace="example-physical",
)
SENSOR_PROPERTY = "temperature_c"


def build_sensor_provider(
    observed_at: datetime,
    *,
    conflicting: bool = False,
) -> InMemoryWorldState:
    """Build a short-validity physical sensor scenario.

    The example deliberately models two independent observations when
    ``conflicting`` is true. WorldState must preserve the disagreement rather
    than select a sensor implicitly.
    """
    provider = InMemoryWorldState()
    source_a = Source(
        source_id="sensor-a",
        source_type="physical-sensor",
        version="calibration-1",
    )
    ev_a = Evidence(
        evidence_id="sensor-ev-a",
        source=source_a,
        recorded_at=observed_at,
    )
    provider.add_evidence(ev_a)
    provider.add_claim(
        Claim(
            claim_id="sensor-claim-a",
            entity=SENSOR_ENTITY,
            property_key=SENSOR_PROPERTY,
            value=21.5,
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=(ev_a.evidence_id,),
                source_refs=(source_a.source_id,),
                method="direct-observation",
            ),
            created_at=observed_at,
            temporal_scope=TemporalScope(
                start=observed_at,
                end=observed_at + timedelta(minutes=5),
            ),
        )
    )

    if conflicting:
        source_b = Source(
            source_id="sensor-b",
            source_type="physical-sensor",
            version="calibration-1",
        )
        ev_b = Evidence(
            evidence_id="sensor-ev-b",
            source=source_b,
            recorded_at=observed_at,
        )
        provider.add_evidence(ev_b)
        provider.add_claim(
            Claim(
                claim_id="sensor-claim-b",
                entity=SENSOR_ENTITY,
                property_key=SENSOR_PROPERTY,
                value=24.0,
                epistemic_mode=EpistemicMode.OBSERVED,
                provenance=Provenance(
                    evidence_refs=(ev_b.evidence_id,),
                    source_refs=(source_b.source_id,),
                    method="direct-observation",
                ),
                created_at=observed_at,
                temporal_scope=TemporalScope(
                    start=observed_at,
                    end=observed_at + timedelta(minutes=5),
                ),
            )
        )

    return provider
