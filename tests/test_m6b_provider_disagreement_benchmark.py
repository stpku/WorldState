from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.m6b_provider_disagreement.benchmark import CASES_PATH, run_benchmark


def _mutated_fixture(tmp_path: Path, mutate) -> Path:
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    mutate(fixture)
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


def test_m6b_three_provider_modes_preserve_conflict_until_convergence() -> None:
    result = run_benchmark()
    metrics = result["metrics"]

    assert result["provider_modes"] == ["native", "projection", "direct-external"]
    assert metrics["provider_mode_count"] == 3
    assert metrics["provider_mode_coverage_rate"] == 1.0
    assert metrics["expected_conflict_epochs"] == 2
    assert metrics["preserved_conflict_epochs"] == 2
    assert metrics["conflict_persistence_rate"] == 1.0
    assert metrics["replay_stability_rate"] == 1.0
    assert metrics["unsupported_resolution_count"] == 0
    assert metrics["expected_assertion_miss_count"] == 0
    assert metrics["false_resolution_rate"] == 0.0
    assert metrics["change_semantics_pass"] is True
    assert result["gates"] == {
        "safety_gate": True,
        "persistence_gate": True,
        "utility_gate": True,
        "promotion_gate": True,
    }


def test_m6b_change_sequence_is_conflict_changed_then_conflict_resolved() -> None:
    result = run_benchmark()

    assert [epoch["fused_kind"] for epoch in result["epochs"]] == [
        "conflict",
        "conflict",
        "assertion",
    ]
    assert result["epochs"][2]["provider_values"] == {
        "direct-external": "closed",
        "native": "closed",
        "projection": "closed",
    }
    assert result["deltas"] == [
        {"from": "t0", "to": "t1", "kind": "conflict_changed", "change_count": 1},
        {"from": "t1", "to": "t2", "kind": "conflict_resolved", "change_count": 1},
    ]


def test_m6b_policy_decision_reason_and_provenance_are_replayable() -> None:
    result = run_benchmark()
    policy = result["policy_resolution"]

    assert policy["decision_status"] == "resolved"
    assert policy["outcome_value"] == "closed"
    assert policy["reason"] == "explicit provider-mode priority selected provider://projection"
    assert policy["replay_stable"] is True
    assert policy["provenance_pass"] is True
    assert result["metrics"]["policy_replay_pass"] is True
    assert result["metrics"]["policy_provenance_pass"] is True


def test_expected_label_mutation_does_not_change_provider_fusion(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["epochs"][1]["expected_kind"] = "assertion"
        fixture["epochs"][1]["expected_value"] = "closed"

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))

    assert result["epochs"][1]["fused_kind"] == "conflict"
    assert result["metrics"]["expected_assertion_miss_count"] == 1
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_premature_provider_convergence_breaks_conflict_persistence_gate(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["epochs"][1]["projection"]["value"] = "open"

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))

    assert result["epochs"][1]["fused_kind"] == "assertion"
    assert result["metrics"]["unsupported_resolution_count"] == 1
    assert result["metrics"]["conflict_persistence_rate"] == 0.5
    assert result["metrics"]["change_semantics_pass"] is False
    assert result["gates"]["persistence_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_nonconverged_final_epoch_cannot_claim_conflict_resolved(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["epochs"][2]["direct_external"]["value"] = "open"

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))

    assert result["epochs"][2]["fused_kind"] == "conflict"
    assert result["metrics"]["expected_assertion_miss_count"] == 1
    assert result["metrics"]["change_semantics_pass"] is False
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_wrong_provider_priority_triggers_false_resolution_gate(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["policy_resolution"]["priority"] = [
            "provider://direct-external",
            "provider://projection",
            "provider://native",
        ]

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))

    assert result["policy_resolution"]["outcome_value"] == "open"
    assert result["metrics"]["false_resolution_count"] == 1
    assert result["metrics"]["false_resolution_rate"] == 1.0
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_m6b_claims_remain_fixture_and_adapter_bound() -> None:
    result = run_benchmark()

    assert result["claim_limits"] == {
        "deterministic_fixture_bound": True,
        "provider_modes_are_existing_examples": True,
        "fusion_adapter_is_benchmark_local": True,
        "provider_authority_policy_is_benchmark_local": True,
        "universal_provider_fusion_claim": False,
        "real_world_truth_accuracy_claim": False,
        "production_provider_reliability_claim": False,
    }
