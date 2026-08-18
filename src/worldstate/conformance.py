from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .ids import canonical_json
from .models import (
    Conflict,
    EntityRef,
    JSONValue,
    StateAssertion,
    Unknown,
    UnknownReason,
)
from .provider import WorldStateProvider


class ExpectedResultKind(str, Enum):
    ASSERTION = "assertion"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class ProviderProbe:
    """One domain-neutral state query expectation for provider conformance."""

    entity: EntityRef
    property_key: str
    at: datetime
    expected_kind: ExpectedResultKind
    expected_value: JSONValue | None = None
    expected_unknown_reason: UnknownReason | None = None


@dataclass(frozen=True, slots=True)
class ConformanceViolation:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    provider_name: str
    checks: int
    violations: tuple[ConformanceViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


def check_provider_conformance(
    provider: object,
    probes: Iterable[ProviderProbe],
) -> ConformanceReport:
    """Run reusable semantic-shape and replay checks against a provider.

    Providers remain responsible for their own storage architecture. This suite
    checks only the public WorldState contract and deterministic read behavior.
    """
    violations: list[ConformanceViolation] = []
    checks = 1
    provider_name = type(provider).__name__

    if not isinstance(provider, WorldStateProvider):
        violations.append(
            ConformanceViolation(
                code="provider.protocol",
                message="provider does not satisfy WorldStateProvider protocol",
            )
        )
        return ConformanceReport(provider_name, checks, tuple(violations))

    typed_provider = provider
    probe_items = tuple(probes)
    for index, probe in enumerate(probe_items):
        checks += 1
        result = typed_provider.query_state(
            probe.entity,
            probe.property_key,
            probe.at,
        )
        prefix = f"probe[{index}]"

        if probe.expected_kind is ExpectedResultKind.ASSERTION:
            if not isinstance(result, StateAssertion):
                violations.append(
                    ConformanceViolation(
                        code=f"{prefix}.kind",
                        message=f"expected assertion, got {type(result).__name__}",
                    )
                )
                continue
            if probe.expected_value is not None:
                checks += 1
                if canonical_json(result.value) != canonical_json(probe.expected_value):
                    violations.append(
                        ConformanceViolation(
                            code=f"{prefix}.value",
                            message="assertion value differs from expected value",
                        )
                    )
            checks += 1
            returned_evidence = {
                item.evidence_id
                for item in typed_provider.get_evidence(result.assertion_id)
            }
            missing = set(result.provenance.evidence_refs) - returned_evidence
            if missing:
                violations.append(
                    ConformanceViolation(
                        code=f"{prefix}.evidence",
                        message=f"missing evidence refs: {sorted(missing)}",
                    )
                )

        elif probe.expected_kind is ExpectedResultKind.UNKNOWN:
            if not isinstance(result, Unknown):
                violations.append(
                    ConformanceViolation(
                        code=f"{prefix}.kind",
                        message=f"expected unknown, got {type(result).__name__}",
                    )
                )
                continue
            if probe.expected_unknown_reason is not None:
                checks += 1
                if result.reason is not probe.expected_unknown_reason:
                    violations.append(
                        ConformanceViolation(
                            code=f"{prefix}.reason",
                            message=(
                                f"expected {probe.expected_unknown_reason.value}, "
                                f"got {result.reason.value}"
                            ),
                        )
                    )
            checks += 1
            cached_unknown_refs = {
                item.unknown_id for item in typed_provider.get_unknowns(None)
            }
            if result.unknown_id not in cached_unknown_refs:
                violations.append(
                    ConformanceViolation(
                        code=f"{prefix}.unknown_lookup",
                        message="query Unknown is not returned by get_unknowns(None)",
                    )
                )

        elif probe.expected_kind is ExpectedResultKind.CONFLICT:
            if not isinstance(result, Conflict):
                violations.append(
                    ConformanceViolation(
                        code=f"{prefix}.kind",
                        message=f"expected conflict, got {type(result).__name__}",
                    )
                )
                continue
            checks += 1
            returned_evidence = {
                item.evidence_id
                for item in typed_provider.get_evidence(result.conflict_id)
            }
            missing = set(result.evidence_refs) - returned_evidence
            if missing:
                violations.append(
                    ConformanceViolation(
                        code=f"{prefix}.evidence",
                        message=f"missing evidence refs: {sorted(missing)}",
                    )
                )
            checks += 1
            cached_conflict_refs = {
                item.conflict_id for item in typed_provider.get_conflicts(None)
            }
            if result.conflict_id not in cached_conflict_refs:
                violations.append(
                    ConformanceViolation(
                        code=f"{prefix}.conflict_lookup",
                        message="query Conflict is not returned by get_conflicts(None)",
                    )
                )

    for index, probe in enumerate(probe_items):
        checks += 4
        first = typed_provider.get_snapshot(None, probe.at)
        replay = typed_provider.get_snapshot(None, probe.at)
        if first.snapshot_id != replay.snapshot_id:
            violations.append(
                ConformanceViolation(
                    code=f"snapshot[{index}].replay",
                    message="repeated snapshot changed semantic identity",
                )
            )
        if tuple(item.assertion_id for item in first.assertions) != tuple(
            sorted(item.assertion_id for item in first.assertions)
        ):
            violations.append(
                ConformanceViolation(
                    code=f"snapshot[{index}].assertion_order",
                    message="snapshot assertions are not canonically ordered",
                )
            )
        if tuple(item.unknown_id for item in first.unknowns) != tuple(
            sorted(item.unknown_id for item in first.unknowns)
        ):
            violations.append(
                ConformanceViolation(
                    code=f"snapshot[{index}].unknown_order",
                    message="snapshot unknowns are not canonically ordered",
                )
            )
        if tuple(item.conflict_id for item in first.conflicts) != tuple(
            sorted(item.conflict_id for item in first.conflicts)
        ):
            violations.append(
                ConformanceViolation(
                    code=f"snapshot[{index}].conflict_order",
                    message="snapshot conflicts are not canonically ordered",
                )
            )

    return ConformanceReport(provider_name, checks, tuple(violations))
