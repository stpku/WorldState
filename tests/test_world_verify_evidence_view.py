"""Publication-consumer tests; do not change or extend WorldState Core."""

from __future__ import annotations

import json

from examples.world_verify.evidence_view import STORIES, evidence_view


def _by_property(view: dict[str, object]) -> dict[str, dict[str, object]]:
    return {fact["property_key"]: fact for fact in view["facts"]}


def test_scale_example_preserves_unknown_real_height() -> None:
    view = evidence_view("pku_scale")
    facts = _by_property(view)
    assert view["demo_data"] == "synthetic-not-a-field-observation"
    assert facts["projection_alignment"]["outcome"]["kind"] == "assertion"
    assert facts["projection_alignment"]["outcome"]["epistemic_mode"] == "simulated"
    assert facts["absolute_height_m"]["outcome"]["kind"] == "unknown"
    assert facts["absolute_height_m"]["outcome"]["reason"] == "no_evidence"
    assert facts["absolute_height_m"]["evidence"] == []


def test_campus_example_preserves_conflict_and_geometry_unknown() -> None:
    facts = _by_property(evidence_view("campus_reconstruction"))
    assert facts["appearance_similarity"]["outcome"]["kind"] == "assertion"
    assert facts["appearance_similarity"]["outcome"]["epistemic_mode"] == "simulated"
    conflict = facts["candidate_roof_orientation"]
    assert conflict["outcome"]["kind"] == "conflict"
    assert len(conflict["outcome"]["candidate_refs"]) == 2
    assert len(conflict["evidence"]) == 2
    assert facts["geometry_verified"]["outcome"]["kind"] == "unknown"


def test_all_assertions_have_explicit_synthetic_provenance() -> None:
    for story in STORIES:
        for fact in evidence_view(story)["facts"]:
            outcome = fact["outcome"]
            if outcome["kind"] == "assertion":
                assert outcome["epistemic_mode"] == "simulated"
                assert outcome["provenance"]["method"] == "reference-resolution"
                assert outcome["provenance"]["evidence_refs"]
            for evidence in fact["evidence"]:
                assert evidence["synthetic"] is True
                assert evidence["source_type"] == "synthetic-teaching-case"


def test_evidence_views_are_replayable_json() -> None:
    for story in STORIES:
        first = json.dumps(evidence_view(story), ensure_ascii=False, sort_keys=True)
        second = json.dumps(evidence_view(story), ensure_ascii=False, sort_keys=True)
        assert first == second
        assert "\"contract\": \"world-verify.evidence-view\"" in first
