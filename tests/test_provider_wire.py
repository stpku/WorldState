from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from worldstate import (
    Conflict,
    EntityRef,
    EpistemicMode,
    Provenance,
    SNAPSHOT_CONTRACT_ID,
    STATE_QUERY_RESULT_CONTRACT_ID,
    SpatialScope,
    StateAssertion,
    Uncertainty,
    Unknown,
    UnknownReason,
    Validity,
    WIRE_CONTRACT_VERSION,
    WorldStateSnapshot,
    snapshot_payload,
    state_query_result_payload,
)

UTC = timezone.utc
AT = datetime(2026, 8, 19, 1, 23, 45, 123456, tzinfo=UTC)
ENTITY = EntityRef(
    "thing-1",
    entity_type="example_asset",
    namespace="example://provider-wire",
)
SCOPE = SpatialScope(
    kind="bbox",
    reference="scope://example/1",
    bbox=(113.1, 22.1, 113.9, 22.9),
    metadata={"crs": "EPSG:4326", "resolution_m": 1000},
)


def assertion() -> StateAssertion:
    return StateAssertion(
        assertion_id="state-rich-1",
        entity=ENTITY,
        property_key="status",
        value={"state": "open", "sequence": [1, 2]},
        epistemic_mode=EpistemicMode.OBSERVED,
        validity=Validity(
            resolved_at=AT,
            valid_from=datetime(2026, 8, 19, 1, 0, tzinfo=UTC),
            valid_until=datetime(2026, 8, 19, 2, 0, tzinfo=UTC),
            superseded_by="state-rich-2",
        ),
        provenance=Provenance(
            evidence_refs=("evidence-1", "evidence-2"),
            source_refs=("source-1",),
            parent_assertion_refs=("state-parent",),
            method="reference-resolution",
            resolver="resolver@0.1",
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


def unknown() -> Unknown:
    return Unknown(
        unknown_id="unknown-rich-1",
        reason=UnknownReason.INSUFFICIENT_EVIDENCE,
        as_of=AT,
        entity=ENTITY,
        property_key="status",
        missing=("evidence-authoritative",),
        metadata={"provider": "example", "retryable": True},
    )


def conflict() -> Conflict:
    return Conflict(
        conflict_id="conflict-rich-1",
        entity=ENTITY,
        property_key="status",
        candidate_refs=("claim-a", "claim-b"),
        evidence_refs=("evidence-a", "evidence-b"),
        reason="materially incompatible claims",
        as_of=AT,
        metadata={"resolution_required": True},
    )


def test_public_package_exports_general_wire_contract() -> None:
    import worldstate

    assert worldstate.WIRE_CONTRACT_VERSION == "0.1"
    assert worldstate.STATE_QUERY_RESULT_CONTRACT_ID == "worldstate.state-query-result"
    assert worldstate.SNAPSHOT_CONTRACT_ID == "worldstate.snapshot"


def test_rich_assertion_wire_preserves_provider_semantics_needed_by_task_consumers() -> None:
    payload = state_query_result_payload(assertion())

    assert payload["contract"] == STATE_QUERY_RESULT_CONTRACT_ID
    assert payload["contract_version"] == WIRE_CONTRACT_VERSION
    assert payload["kind"] == "assertion"
    assert payload["entity"] == {
        "entity_id": "thing-1",
        "entity_type": "example_asset",
        "namespace": "example://provider-wire",
    }
    assert payload["value"] == {"state": "open", "sequence": [1, 2]}
    assert payload["validity"] == {
        "resolved_at": "2026-08-19T01:23:45.123456Z",
        "valid_from": "2026-08-19T01:00:00Z",
        "valid_until": "2026-08-19T02:00:00Z",
        "superseded_by": "state-rich-2",
    }
    assert payload["provenance"] == {
        "evidence_refs": ["evidence-1", "evidence-2"],
        "source_refs": ["source-1"],
        "parent_assertion_refs": ["state-parent"],
        "method": "reference-resolution",
        "resolver": "resolver@0.1",
    }
    assert payload["uncertainty"] == {
        "confidence": 0.82,
        "method": "provider-reported",
        "reason": "measurement uncertainty",
        "metadata": {"interval": [0.75, 0.9]},
    }
    assert payload["spatial_scope"] == {
        "kind": "bbox",
        "reference": "scope://example/1",
        "bbox": [113.1, 22.1, 113.9, 22.9],
        "metadata": {"crs": "EPSG:4326", "resolution_m": 1000},
    }
    json.dumps(payload)


def test_unknown_wire_stays_unknown_and_preserves_missing_provider_evidence() -> None:
    payload = state_query_result_payload(unknown())

    assert payload["kind"] == "unknown"
    assert payload["reason"] == "insufficient_evidence"
    assert payload["as_of"] == "2026-08-19T01:23:45.123456Z"
    assert payload["entity"] == {
        "entity_id": "thing-1",
        "entity_type": "example_asset",
        "namespace": "example://provider-wire",
    }
    assert payload["missing"] == ["evidence-authoritative"]
    assert payload["metadata"] == {"provider": "example", "retryable": True}


def test_conflict_wire_preserves_all_candidates_without_choosing_a_winner() -> None:
    payload = state_query_result_payload(conflict())

    assert payload["kind"] == "conflict"
    assert payload["candidate_refs"] == ["claim-a", "claim-b"]
    assert payload["evidence_refs"] == ["evidence-a", "evidence-b"]
    assert payload["reason"] == "materially incompatible claims"
    assert "winner" not in payload
    assert "selected" not in payload


def test_snapshot_wire_preserves_all_first_class_result_kinds_and_scope() -> None:
    snapshot = WorldStateSnapshot(
        snapshot_id="snap-rich-1",
        as_of=AT,
        created_at=AT,
        version="0.1",
        scope=SCOPE,
        assertions=(assertion(),),
        unknowns=(unknown(),),
        conflicts=(conflict(),),
        source_versions={"source-b": "2", "source-a": "1"},
    )

    payload = snapshot_payload(snapshot)

    assert payload["contract"] == SNAPSHOT_CONTRACT_ID
    assert payload["contract_version"] == WIRE_CONTRACT_VERSION
    assert payload["snapshot_id"] == "snap-rich-1"
    assert payload["scope"]["reference"] == "scope://example/1"  # type: ignore[index]
    assert [item["kind"] for item in payload["assertions"]] == ["assertion"]  # type: ignore[index]
    assert [item["kind"] for item in payload["unknowns"]] == ["unknown"]  # type: ignore[index]
    assert [item["kind"] for item in payload["conflicts"]] == ["conflict"]  # type: ignore[index]
    assert payload["source_versions"] == {"source-a": "1", "source-b": "2"}
    json.dumps(payload)


def test_general_wire_is_richer_than_grounding_transport_and_consumer_neutral() -> None:
    payload = state_query_result_payload(assertion())

    assert payload["entity"]["namespace"] == "example://provider-wire"  # type: ignore[index]
    assert payload["uncertainty"] is not None
    assert payload["spatial_scope"] is not None
    assert "requirementId" not in payload
    assert "disposition" not in payload
    assert "admission" not in payload


def test_wire_module_has_no_consumer_runtime_dependency() -> None:
    text = (
        Path(__file__).parents[1] / "src" / "worldstate" / "wire.py"
    ).read_text(encoding="utf-8").lower()

    for forbidden in (
        "import geotask",
        "from geotask",
        "import agentreality",
        "from agentreality",
        "import lowa",
        "from lowa",
        "import deepseek",
        "from deepseek",
    ):
        assert forbidden not in text
