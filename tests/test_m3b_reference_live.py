from __future__ import annotations

from examples.integrations.m3b_reference_live import build_projection

AS_OF = "2026-08-19T00:00:00Z"


def test_supported_scenario_uses_real_reference_engine_and_is_replayable() -> None:
    first = build_projection("supported", AS_OF)
    replay = build_projection("supported", AS_OF)

    assert first == replay
    assert first["contract"] == "worldstate.state-query-result"
    assert first["contract_version"] == "0.1"
    assert first["kind"] == "assertion"
    assert first["value"] == "ready"
    assert first["validity"]["resolved_at"] == AS_OF  # type: ignore[index]
    assert first["validity"]["valid_until"] == "2026-08-19T00:10:00Z"  # type: ignore[index]
    assert first["provenance"]["evidence_refs"] == ["evidence-reference-a"]  # type: ignore[index]


def test_unknown_scenario_preserves_no_evidence_as_unknown() -> None:
    projection = build_projection("unknown", AS_OF)

    assert projection["kind"] == "unknown"
    assert projection["reason"] == "no_evidence"
    assert projection["as_of"] == AS_OF
    assert "value" not in projection


def test_conflict_scenario_preserves_both_claims_without_winner() -> None:
    projection = build_projection("conflict", AS_OF)

    assert projection["kind"] == "conflict"
    assert projection["candidate_refs"] == ["claim-reference-a", "claim-reference-b"]
    assert projection["evidence_refs"] == ["evidence-reference-a", "evidence-reference-b"]
    assert "winner" not in projection
    assert "value" not in projection
