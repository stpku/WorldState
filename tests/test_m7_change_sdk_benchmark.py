from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.m7_change_provider_sdk.benchmark import CASES_PATH, run_benchmark


def _mutated_fixture(tmp_path: Path, mutate) -> Path:
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    mutate(fixture)
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


def test_m7_benchmark_reduces_false_change_without_missing_true_change() -> None:
    result = run_benchmark()
    metrics = result["metrics"]

    assert metrics["provider_mode_count"] == 2
    assert metrics["naive_false_change_count"] == 2
    assert metrics["naive_false_change_rate"] == 1.0
    assert metrics["sdk_false_change_count"] == 0
    assert metrics["sdk_false_change_rate"] == 0.0
    assert metrics["stable_state_ref_retention_rate"] == 1.0
    assert metrics["true_change_case_count"] == 2
    assert metrics["true_change_detected_count"] == 2
    assert metrics["true_change_detection_rate"] == 1.0
    assert metrics["naive_outage_false_transition_count"] == 1
    assert metrics["sdk_outage_false_transition_count"] == 0
    assert metrics["outage_diagnostic_pass"] is True
    assert metrics["validity_expiry_pass"] is True
    assert metrics["replay_stability_pass"] is True
    assert metrics["consumer_neutral_wire_pass"] is True
    assert metrics["persistence_ownership_pass"] is True
    assert result["gates"] == {
        "safety_gate": True,
        "utility_gate": True,
        "promotion_gate": True,
    }


def test_expected_label_mutation_does_not_change_sdk_output(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["unchanged_cases"][0]["expected_status"] = "changed"

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))
    row = result["unchanged_cases"][0]

    assert row["sdk_status"] == "unchanged"
    assert row["sdk_change_count"] == 0
    assert result["metrics"]["expected_label_mismatch_count"] == 1
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_missing_real_source_change_breaks_detection_gate(tmp_path: Path) -> None:
    def mutate(fixture):
        fixture["changed_cases"][0]["apply_update"] = False

    result = run_benchmark(_mutated_fixture(tmp_path, mutate))
    row = result["changed_cases"][0]

    assert row["sdk_status"] == "unchanged"
    assert row["change_kinds"] == []
    assert result["metrics"]["true_change_detection_rate"] == 0.5
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_naive_baseline_demonstrates_clock_and_outage_false_transitions() -> None:
    result = run_benchmark()

    assert [row["naive_change_count"] for row in result["unchanged_cases"]] == [1, 1]
    assert result["outage_case"]["naive_change_kinds"] == ["removed"]
    assert result["outage_case"]["sdk_status"] == "provider_unavailable"
    assert result["outage_case"]["sdk_delta_is_none"] is True
    assert result["outage_case"]["recovery_from_last_good"] is True
    assert result["outage_case"]["recovery_change_kinds"] == ["state_changed"]


def test_m7_claims_remain_pull_based_and_fixture_bound() -> None:
    result = run_benchmark()

    assert result["claim_limits"] == {
        "deterministic_fixture_bound": True,
        "provider_modes": ["projection", "direct-external"],
        "pull_based_only": True,
        "event_bus_claim": False,
        "live_provider_reliability_claim": False,
        "production_latency_claim": False,
        "universal_change_transport_claim": False,
    }
