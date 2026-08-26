from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.m8_independent_consumer.benchmark import CASES_PATH, run_benchmark


def _mutated_fixture(tmp_path: Path, mutate) -> Path:
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    mutate(fixture)
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


def test_m8_independent_consumer_closes_truth_change_and_independence_gates() -> None:
    result = run_benchmark()
    metrics = result["metrics"]

    assert result["consumer"] == "cold-chain-shipment-monitor"
    assert metrics["static_case_count"] == 4
    assert metrics["fact_expectation_count"] == 8
    assert metrics["state_correct_count"] == 8
    assert metrics["state_correctness_rate"] == 1.0
    assert metrics["provenance_coverage_rate"] == 1.0
    assert metrics["expected_unknown_count"] == 2
    assert metrics["unknown_fidelity_rate"] == 1.0
    assert metrics["expected_conflict_count"] == 1
    assert metrics["conflict_preservation_rate"] == 1.0
    assert metrics["unsupported_state_rate"] == 0.0
    assert metrics["temporal_change_fidelity_pass"] is True
    assert metrics["outage_change_fidelity_pass"] is True
    assert metrics["replay_stability_pass"] is True
    assert metrics["stack_dependency_count"] == 0
    assert metrics["core_domain_leakage_count"] == 0
    assert metrics["domain_decision_leakage_count"] == 0
    assert metrics["direct_worldstate_consumer"] is True
    assert result["gates"] == {
        "truth_fidelity_gate": True,
        "change_gate": True,
        "independence_gate": True,
        "promotion_gate": True,
    }


def test_conflict_truth_label_mutation_does_not_change_consumer_output(tmp_path: Path) -> None:
    def mutate(fixture):
        case = next(item for item in fixture["static_cases"] if item["case_id"] == "sensor-conflict")
        case["expected_temperature_kind"] = "assertion"
        case["expected_temperature_value"] = 4.0

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))
    row = next(item for item in result["static_cases"] if item["case_id"] == "sensor-conflict")

    assert row["temperature"]["kind"] == "conflict"
    assert result["metrics"]["state_correctness_rate"] == 7 / 8
    assert result["gates"]["truth_fidelity_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_missing_registry_update_breaks_temporal_change_gate(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["temporal_case"]["apply_registry_update"] = False

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))

    assert result["temporal_case"]["changed_properties"] == ["temperature_c"]
    assert result["metrics"]["temporal_change_fidelity_pass"] is False
    assert result["gates"]["change_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_outage_expectation_mutation_does_not_fabricate_change(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["outage_watch_case"]["expected_changed_properties"] = ["temperature_c"]
        fixture["outage_watch_case"]["expected_unavailable_properties"] = []

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))

    assert result["outage_watch_case"]["changed_properties"] == []
    assert result["outage_watch_case"]["unavailable_properties"] == ["temperature_c"]
    assert result["metrics"]["outage_change_fidelity_pass"] is False
    assert result["gates"]["change_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_m8_claims_are_bounded_to_independent_fixture() -> None:
    result = run_benchmark()

    assert result["claim_limits"] == {
        "deterministic_fixture_bound": True,
        "independent_non_lowa_domain": True,
        "official_geotask_required": False,
        "official_agentreality_required": False,
        "core_fork_required": False,
        "domain_specific_resolver_required": False,
        "domain_decision_claim": False,
        "production_cold_chain_compliance_claim": False,
        "live_provider_reliability_claim": False,
    }
