from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from worldstate import (
    Conflict,
    EntityRef,
    JSONValue,
    StateAssertion,
    Unknown,
    UnknownReason,
    WorldStateProvider,
    canonical_json,
)


class ExpectedOutcome(str, Enum):
    ASSERTION = "assertion"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    name: str
    provider: WorldStateProvider
    entity: EntityRef
    property_key: str
    at: datetime
    expected: ExpectedOutcome
    expected_value: JSONValue | None = None
    expected_unknown_reason: UnknownReason | None = None
    validity_case: bool = False


@dataclass(frozen=True, slots=True)
class GeneralizationMetrics:
    state_correctness: float
    provenance_coverage: float
    unknown_fidelity: float
    conflict_preservation: float
    validity_accuracy: float
    replayability: float
    unsupported_state_rate: float


def evaluate_cases(cases: Iterable[BenchmarkCase]) -> GeneralizationMetrics:
    """Evaluate M3 truth-fidelity metrics without adding benchmark policy to Core."""
    items = tuple(cases)
    assertion_expected = 0
    assertion_correct = 0
    actual_assertions = 0
    provenance_supported = 0
    unknown_expected = 0
    unknown_correct = 0
    conflict_expected = 0
    conflict_correct = 0
    validity_expected = 0
    validity_correct = 0
    replay_total = 0
    replay_correct = 0
    unsupported_assertions = 0

    for case in items:
        first = case.provider.query_state(case.entity, case.property_key, case.at)
        replay = case.provider.query_state(case.entity, case.property_key, case.at)
        replay_total += 1
        if _result_identity(first) == _result_identity(replay):
            replay_correct += 1

        outcome_correct = False
        if case.expected is ExpectedOutcome.ASSERTION:
            assertion_expected += 1
            if isinstance(first, StateAssertion):
                outcome_correct = (
                    case.expected_value is None
                    or canonical_json(first.value) == canonical_json(case.expected_value)
                )
                if outcome_correct:
                    assertion_correct += 1
        elif case.expected is ExpectedOutcome.UNKNOWN:
            unknown_expected += 1
            if isinstance(first, Unknown):
                outcome_correct = (
                    case.expected_unknown_reason is None
                    or first.reason is case.expected_unknown_reason
                )
                if outcome_correct:
                    unknown_correct += 1
        elif case.expected is ExpectedOutcome.CONFLICT:
            conflict_expected += 1
            outcome_correct = isinstance(first, Conflict)
            if outcome_correct:
                conflict_correct += 1

        if case.validity_case:
            validity_expected += 1
            if outcome_correct:
                validity_correct += 1

        if isinstance(first, StateAssertion):
            actual_assertions += 1
            returned_refs = {
                evidence.evidence_id
                for evidence in case.provider.get_evidence(first.assertion_id)
            }
            supported = bool(first.provenance.evidence_refs) and set(
                first.provenance.evidence_refs
            ).issubset(returned_refs)
            if supported:
                provenance_supported += 1
            if case.expected is not ExpectedOutcome.ASSERTION or not supported:
                unsupported_assertions += 1

    return GeneralizationMetrics(
        state_correctness=_ratio(assertion_correct, assertion_expected),
        provenance_coverage=_ratio(provenance_supported, actual_assertions),
        unknown_fidelity=_ratio(unknown_correct, unknown_expected),
        conflict_preservation=_ratio(conflict_correct, conflict_expected),
        validity_accuracy=_ratio(validity_correct, validity_expected),
        replayability=_ratio(replay_correct, replay_total),
        unsupported_state_rate=(
            0.0
            if actual_assertions == 0
            else unsupported_assertions / actual_assertions
        ),
    )


def _result_identity(result: object) -> tuple[str, str]:
    if isinstance(result, StateAssertion):
        return ("assertion", result.assertion_id)
    if isinstance(result, Unknown):
        return ("unknown", result.unknown_id)
    if isinstance(result, Conflict):
        return ("conflict", result.conflict_id)
    return (type(result).__name__, canonical_json(result))


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator
