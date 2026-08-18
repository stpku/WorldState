from __future__ import annotations

import json
from pathlib import Path

from examples.integrations.provider_wire_vectors import (
    VECTOR_SCHEMA,
    WORLDSTATE_PROVIDER_WIRE_BASELINE,
    canonical_vectors_json,
)

FIXTURE = (
    Path(__file__).parents[1]
    / "examples"
    / "integrations"
    / "provider_wire_vectors.json"
)


def test_checked_in_provider_vectors_match_deterministic_producer_output() -> None:
    checked_in = FIXTURE.read_text(encoding="utf-8")

    assert checked_in == canonical_vectors_json()


def test_provider_vectors_cover_first_class_outcomes_without_consumer_policy() -> None:
    checked_in = FIXTURE.read_text(encoding="utf-8")
    payload = json.loads(checked_in)

    assert payload["schema"] == VECTOR_SCHEMA
    assert payload["worldstateProviderWireBaseline"] == WORLDSTATE_PROVIDER_WIRE_BASELINE
    assert [item["name"] for item in payload["vectors"]] == [
        "assertion",
        "unknown",
        "conflict",
        "provider_unavailable",
    ]
    assert [item["projection"]["kind"] for item in payload["vectors"]] == [
        "assertion",
        "unknown",
        "conflict",
        "unknown",
    ]
    assert all(
        item["projection"]["contract"] == "worldstate.state-query-result"
        and item["projection"]["contract_version"] == "0.1"
        for item in payload["vectors"]
    )
    assert '"requirement_id"' not in checked_in
    assert '"applicability"' not in checked_in
    assert '"sufficiency"' not in checked_in
    assert '"disposition"' not in checked_in
    assert '"admission"' not in checked_in


def test_assertion_vector_preserves_rich_state_for_task_relative_consumers() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assertion = payload["vectors"][0]["projection"]

    assert assertion["kind"] == "assertion"
    assert assertion["entity"] == {
        "entity_id": "asset-1",
        "entity_type": "example_asset",
        "namespace": "example://worldstate-provider-wire",
    }
    assert assertion["validity"] == {
        "resolved_at": "2026-08-19T02:00:00.123456Z",
        "valid_from": "2026-08-19T01:45:00Z",
        "valid_until": "2026-08-19T02:30:00Z",
        "superseded_by": None,
    }
    assert assertion["uncertainty"]["confidence"] == 0.82
    assert assertion["spatial_scope"]["reference"] == "scope://example/asset-1"
    assert assertion["provenance"]["evidence_refs"] == ["evidence-provider-1"]


def test_conflict_and_provider_unavailable_remain_explicit_fail_closed_inputs() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    by_name = {item["name"]: item["projection"] for item in payload["vectors"]}

    conflict = by_name["conflict"]
    unavailable = by_name["provider_unavailable"]

    assert conflict["kind"] == "conflict"
    assert conflict["candidate_refs"] == ["claim-a", "claim-b"]
    assert "winner" not in conflict
    assert "selected" not in conflict

    assert unavailable["kind"] == "unknown"
    assert unavailable["reason"] == "provider_unavailable"
