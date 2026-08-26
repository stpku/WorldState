from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from worldstate import (
    Claim,
    Conflict,
    ConflictResolutionDecision,
    EntityRef,
    EpistemicMode,
    Provenance,
    StateAssertion,
    Unknown,
    apply_conflict_resolution_policy,
)
from worldstate.ids import semantic_id
from worldstate.resolution import ReferenceResolver, ResolutionInputs

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("cases.json")
AT = datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)
POLICY_REF = "policy://benchmark/source-priority/v0.1"
POLICY_VERSION = "0.1"
FALSE_RESOLUTION_THRESHOLD = 0.0


class FixtureSourcePriorityPolicy:
    """Benchmark-local explicit policy; expected labels are never read here."""

    policy_ref = POLICY_REF
    version = POLICY_VERSION

    def __init__(self, priority: tuple[str, ...]) -> None:
        self.priority = priority

    def decide(
        self,
        conflict: Conflict,
        claims: tuple[Claim, ...],
        *,
        at: datetime,
    ) -> ConflictResolutionDecision:
        rank = {source: index for index, source in enumerate(self.priority)}
        ranked: list[tuple[int, str]] = []
        for claim in claims:
            candidate_ranks = [rank[source] for source in claim.provenance.source_refs if source in rank]
            if candidate_ranks:
                ranked.append((min(candidate_ranks), claim.claim_id))

        if not ranked:
            status = "preserved"
            selected = None
            reason = "no conflict candidate has an explicitly ranked source"
        else:
            best_rank = min(item[0] for item in ranked)
            winners = tuple(sorted(ref for candidate_rank, ref in ranked if candidate_rank == best_rank))
            if len(winners) != 1:
                status = "preserved"
                selected = None
                reason = "explicit source ranking does not produce one unique winner"
            else:
                status = "resolved"
                selected = winners[0]
                reason = "explicit source ranking selected one existing conflict candidate"

        decision_payload = {
            "conflict_id": conflict.conflict_id,
            "policy_ref": self.policy_ref,
            "policy_version": self.version,
            "priority": self.priority,
            "status": status,
            "selected_claim_ref": selected,
            "at": at,
        }
        return ConflictResolutionDecision(
            decision_id=semantic_id("conflict_resolution_decision", decision_payload),
            conflict_id=conflict.conflict_id,
            policy_ref=self.policy_ref,
            policy_version=self.version,
            decided_at=at,
            status=status,
            selected_claim_ref=selected,
            reason=reason,
            source_refs=(conflict.conflict_id, self.policy_ref),
        )


def _claim(entity: EntityRef, property_key: str, raw: dict[str, Any]) -> Claim:
    return Claim(
        claim_id=str(raw["claim_id"]),
        entity=entity,
        property_key=property_key,
        value=raw["value"],
        epistemic_mode=EpistemicMode(str(raw["mode"])),
        provenance=Provenance(
            evidence_refs=(str(raw["evidence_ref"]),),
            source_refs=(str(raw["source_ref"]),),
            method="benchmark-fixture",
        ),
        created_at=AT - timedelta(minutes=1),
    )


def _kind(value: object) -> str:
    if isinstance(value, StateAssertion):
        return "assertion"
    if isinstance(value, Unknown):
        return "unknown"
    if isinstance(value, Conflict):
        return "conflict"
    raise TypeError(type(value).__name__)


def _expected_assertion_correct(outcome: object, expected_value: object) -> bool:
    return isinstance(outcome, StateAssertion) and outcome.value == expected_value


def run_benchmark(cases_path: Path = CASES_PATH) -> dict[str, object]:
    fixture = json.loads(cases_path.read_text(encoding="utf-8"))
    resolver = ReferenceResolver()
    rows: list[dict[str, object]] = []

    expected_assertion_cases = 0
    baseline_correct_assertions = 0
    policy_correct_assertions = 0
    false_resolutions = 0
    policy_resolution_count = 0
    expected_conflicts = 0
    preserved_conflicts = 0
    expected_unknowns = 0
    preserved_unknowns = 0
    policy_provenance_ok = 0
    unsupported_assertions = 0

    for raw_case in fixture["cases"]:
        entity = EntityRef(str(raw_case["entity_id"]), entity_type="benchmark-asset")
        property_key = str(raw_case["property_key"])
        claims = tuple(_claim(entity, property_key, raw) for raw in raw_case["claims"])
        available = ResolutionInputs(
            evidence_refs=frozenset(str(ref) for ref in raw_case["available_evidence"]),
            source_refs=frozenset(str(ref) for ref in raw_case["available_sources"]),
        )
        baseline = resolver.resolve_state(claims, entity, property_key, AT, available=available)
        outcome = baseline
        decision = None

        priority = tuple(str(ref) for ref in raw_case["policy_priority"])
        if isinstance(baseline, Conflict) and priority:
            policy_result = apply_conflict_resolution_policy(
                baseline,
                claims,
                FixtureSourcePriorityPolicy(priority),
            )
            outcome = policy_result.outcome
            decision = policy_result.decision
            if decision.status == "resolved":
                policy_resolution_count += 1
                if (
                    isinstance(outcome, StateAssertion)
                    and outcome.provenance.resolver == f"{POLICY_REF}@{POLICY_VERSION}"
                    and decision.decision_id in outcome.provenance.method
                ):
                    policy_provenance_ok += 1

        expected_kind = str(raw_case["expected_kind"])
        expected_value = raw_case["expected_value"]
        if expected_kind == "assertion":
            expected_assertion_cases += 1
            if _expected_assertion_correct(baseline, expected_value):
                baseline_correct_assertions += 1
            if _expected_assertion_correct(outcome, expected_value):
                policy_correct_assertions += 1
            if isinstance(outcome, StateAssertion) and outcome.value != expected_value:
                false_resolutions += 1
        elif expected_kind == "conflict":
            expected_conflicts += 1
            if isinstance(outcome, Conflict):
                preserved_conflicts += 1
            if isinstance(outcome, StateAssertion):
                false_resolutions += 1
                unsupported_assertions += 1
        elif expected_kind == "unknown":
            expected_unknowns += 1
            if isinstance(outcome, Unknown):
                preserved_unknowns += 1
            if isinstance(outcome, StateAssertion):
                false_resolutions += 1
                unsupported_assertions += 1
        else:
            raise ValueError(f"unsupported expected_kind: {expected_kind}")

        rows.append(
            {
                "case_id": raw_case["case_id"],
                "expected_kind": expected_kind,
                "expected_value": expected_value,
                "baseline_kind": _kind(baseline),
                "outcome_kind": _kind(outcome),
                "outcome_value": outcome.value if isinstance(outcome, StateAssertion) else None,
                "policy_status": None if decision is None else decision.status,
                "policy_selected_claim_ref": None if decision is None else decision.selected_claim_ref,
            }
        )

    transition = fixture["unknown_transition"]
    entity = EntityRef(str(transition["entity_id"]), entity_type="benchmark-asset")
    property_key = str(transition["property_key"])
    claim = _claim(entity, property_key, transition["claim"])
    before = resolver.resolve_state(
        (claim,),
        entity,
        property_key,
        AT,
        available=ResolutionInputs(
            evidence_refs=frozenset(str(ref) for ref in transition["before_available_evidence"]),
            source_refs=frozenset(str(ref) for ref in transition["available_sources"]),
        ),
    )
    after = resolver.resolve_state(
        (claim,),
        entity,
        property_key,
        AT,
        available=ResolutionInputs(
            evidence_refs=frozenset(str(ref) for ref in transition["after_available_evidence"]),
            source_refs=frozenset(str(ref) for ref in transition["available_sources"]),
        ),
    )
    unknown_transition_pass = (
        _kind(before) == transition["expected_before_kind"]
        and _kind(after) == transition["expected_after_kind"]
        and isinstance(after, StateAssertion)
        and after.value == transition["expected_after_value"]
    )

    baseline_coverage = (
        baseline_correct_assertions / expected_assertion_cases if expected_assertion_cases else 1.0
    )
    policy_coverage = (
        policy_correct_assertions / expected_assertion_cases if expected_assertion_cases else 1.0
    )
    false_resolution_rate = (
        false_resolutions / policy_resolution_count if policy_resolution_count else 0.0
    )
    conflict_preservation_rate = (
        preserved_conflicts / expected_conflicts if expected_conflicts else 1.0
    )
    unknown_preservation_rate = preserved_unknowns / expected_unknowns if expected_unknowns else 1.0
    policy_provenance_coverage = (
        policy_provenance_ok / policy_resolution_count if policy_resolution_count else 1.0
    )

    safety_gate = (
        false_resolution_rate <= FALSE_RESOLUTION_THRESHOLD
        and unsupported_assertions == 0
        and conflict_preservation_rate == 1.0
        and unknown_preservation_rate == 1.0
        and policy_provenance_coverage == 1.0
        and unknown_transition_pass
    )
    utility_gate = policy_coverage > baseline_coverage and policy_resolution_count > 0

    return {
        "contract": "worldstate.m6-unknown-conflict-fidelity-benchmark",
        "version": "0.1",
        "case_count": len(rows),
        "cases": rows,
        "metrics": {
            "expected_assertion_cases": expected_assertion_cases,
            "baseline_correct_assertions": baseline_correct_assertions,
            "policy_correct_assertions": policy_correct_assertions,
            "baseline_useful_state_coverage": baseline_coverage,
            "policy_useful_state_coverage": policy_coverage,
            "useful_state_coverage_delta": policy_coverage - baseline_coverage,
            "policy_resolution_count": policy_resolution_count,
            "false_resolution_count": false_resolutions,
            "false_resolution_rate": false_resolution_rate,
            "false_resolution_threshold": FALSE_RESOLUTION_THRESHOLD,
            "expected_conflict_count": expected_conflicts,
            "conflict_preservation_rate": conflict_preservation_rate,
            "expected_unknown_count": expected_unknowns,
            "unknown_preservation_rate": unknown_preservation_rate,
            "policy_provenance_coverage": policy_provenance_coverage,
            "unsupported_assertion_count": unsupported_assertions,
            "unknown_to_resolved_transition_pass": unknown_transition_pass,
        },
        "gates": {
            "safety_gate": safety_gate,
            "utility_gate": utility_gate,
            "promotion_gate": safety_gate and utility_gate,
        },
        "claim_limits": {
            "deterministic_fixture_bound": True,
            "source_priority_is_benchmark_local": True,
            "universal_source_authority_claim": False,
            "real_world_truth_accuracy_claim": False,
            "provider_performance_claim": False,
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2, sort_keys=True))
