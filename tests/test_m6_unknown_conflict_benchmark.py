from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.m6_unknown_conflict_fidelity.benchmark import CASES_PATH, run_benchmark


def test_m6_benchmark_improves_useful_coverage_without_false_resolution() -> None:
    result = run_benchmark()
    metrics = result["metrics"]

    assert result["case_count"] == 6
    assert metrics["baseline_correct_assertions"] == 2
    assert metrics["policy_correct_assertions"] == 3
    assert metrics["baseline_useful_state_coverage"] == 2 / 3
    assert metrics["policy_useful_state_coverage"] == 1.0
    assert metrics["useful_state_coverage_delta"] == pytest.approx(1 / 3)
    assert metrics["false_resolution_rate"] == 0.0
    assert metrics["false_resolution_threshold"] == 0.0
    assert metrics["conflict_preservation_rate"] == 1.0
    assert metrics["unknown_preservation_rate"] == 1.0
    assert metrics["policy_provenance_coverage"] == 1.0
    assert metrics["unknown_to_resolved_transition_pass"] is True
    assert result["gates"] == {
        "safety_gate": True,
        "utility_gate": True,
        "promotion_gate": True,
    }


def test_benchmark_policy_does_not_read_expected_truth_label(tmp_path: Path) -> None:
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case = next(
        item
        for item in fixture["cases"]
        if item["case_id"] == "explicit-authority-resolves-conflict"
    )
    case["expected_value"] = "open"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    result = run_benchmark(path)
    row = next(
        item
        for item in result["cases"]
        if item["case_id"] == "explicit-authority-resolves-conflict"
    )

    assert row["outcome_value"] == "closed"
    assert result["metrics"]["false_resolution_rate"] == 1.0
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_reversing_source_priority_triggers_false_resolution_gate(tmp_path: Path) -> None:
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case = next(
        item
        for item in fixture["cases"]
        if item["case_id"] == "explicit-authority-resolves-conflict"
    )
    case["policy_priority"] = ["source-secondary", "source-authority"]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    result = run_benchmark(path)

    assert result["metrics"]["false_resolution_count"] == 1
    assert result["metrics"]["false_resolution_rate"] == 1.0
    assert result["metrics"]["policy_useful_state_coverage"] == 2 / 3
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_forcing_ambiguous_conflict_to_value_is_unsupported_resolution(tmp_path: Path) -> None:
    fixture = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case = next(
        item
        for item in fixture["cases"]
        if item["case_id"] == "ambiguous-disagreement-remains-conflict"
    )
    case["policy_priority"] = ["source-a", "source-b"]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    result = run_benchmark(path)

    assert result["metrics"]["unsupported_assertion_count"] == 1
    assert result["metrics"]["conflict_preservation_rate"] == 0.5
    assert result["gates"]["safety_gate"] is False
    assert result["gates"]["promotion_gate"] is False


def test_benchmark_claims_remain_fixture_bound() -> None:
    result = run_benchmark()
    assert result["claim_limits"] == {
        "deterministic_fixture_bound": True,
        "source_priority_is_benchmark_local": True,
        "universal_source_authority_claim": False,
        "real_world_truth_accuracy_claim": False,
        "provider_performance_claim": False,
    }
