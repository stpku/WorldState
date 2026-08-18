from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from worldstate import (
    Conflict,
    EntityRef,
    EpistemicMode,
    Provenance,
    SpatialScope,
    StateAssertion,
    Uncertainty,
    Unknown,
    UnknownReason,
    Validity,
    state_query_result_payload,
)

WORLDSTATE_PROVIDER_WIRE_BASELINE = "fe9cc199d2e632122346d1bdffb9ad5ebe375c59"
VECTOR_SCHEMA = "worldstate.provider-wire-v1"
AT = datetime(2026, 8, 19, 2, 0, 0, 123456, tzinfo=timezone.utc)
ENTITY = EntityRef(
    "asset-1",
    entity_type="example_asset",
    namespace="example://worldstate-provider-wire",
)
SCOPE = SpatialScope(
    kind="bbox",
    reference="scope://example/asset-1",
    bbox=(113.1, 22.1, 113.9, 22.9),
    metadata={"crs": "EPSG:4326", "resolution_m": 1000},
)


def _assertion() -> StateAssertion:
    return StateAssertion(
        assertion_id="state-provider-assertion-1",
        entity=ENTITY,
        property_key="operational_status",
        value={"state": "open", "sequence": [1, 2]},
        epistemic_mode=EpistemicMode.OBSERVED,
        validity=Validity(
            resolved_at=AT,
            valid_from=datetime(2026, 8, 19, 1, 45, tzinfo=timezone.utc),
            valid_until=datetime(2026, 8, 19, 2, 30, tzinfo=timezone.utc),
        ),
        provenance=Provenance(
            evidence_refs=("evidence-provider-1",),
            source_refs=("source-provider-1",),
            parent_assertion_refs=("state-parent-1",),
            method="reference-resolution",
            resolver="worldstate.reference-conservative@0.1",
        ),
        version="0.1",
        uncertainty=Uncertainty(
            confidence=0.82,
            method="provider-reported",
            reason="measurement uncertainty",
            metadata={"interval": [0.75, 0.9]},
        ),
        spatial_scope=SCOPE,
    )


def _unknown() -> Unknown:
    return Unknown(
        unknown_id="unknown-provider-1",
        reason=UnknownReason.INSUFFICIENT_EVIDENCE,
        as_of=AT,
        entity=ENTITY,
        property_key="operational_status",
        missing=("authoritative-record",),
        metadata={"retryable": True},
    )


def _conflict() -> Conflict:
    return Conflict(
        conflict_id="conflict-provider-1",
        entity=ENTITY,
        property_key="operational_status",
        candidate_refs=("claim-a", "claim-b"),
        evidence_refs=("evidence-a", "evidence-b"),
        reason="materially incompatible claims",
        as_of=AT,
        metadata={"resolution_required": True},
    )


def _provider_unavailable() -> Unknown:
    return Unknown(
        unknown_id="unknown-provider-unavailable-1",
        reason=UnknownReason.PROVIDER_UNAVAILABLE,
        as_of=AT,
        entity=ENTITY,
        property_key="operational_status",
        missing=(),
        metadata={"provider_ref": "provider://external-worldstate"},
    )


def build_vectors() -> dict[str, object]:
    """Build deterministic consumer-neutral provider-wire vectors."""
    return {
        "schema": VECTOR_SCHEMA,
        "worldstateProviderWireBaseline": WORLDSTATE_PROVIDER_WIRE_BASELINE,
        "vectors": [
            {"name": "assertion", "projection": state_query_result_payload(_assertion())},
            {"name": "unknown", "projection": state_query_result_payload(_unknown())},
            {"name": "conflict", "projection": state_query_result_payload(_conflict())},
            {
                "name": "provider_unavailable",
                "projection": state_query_result_payload(_provider_unavailable()),
            },
        ],
    }


def canonical_vectors_json() -> str:
    return json.dumps(build_vectors(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    destination = Path(__file__).with_name("provider_wire_vectors.json")
    destination.write_text(canonical_vectors_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
