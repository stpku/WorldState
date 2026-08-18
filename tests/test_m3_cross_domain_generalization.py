from datetime import datetime, timedelta, timezone
from pathlib import Path

from examples.cross_domain.benchmark import (
    BenchmarkCase,
    ExpectedOutcome,
    evaluate_cases,
)
from examples.cross_domain.registry_state import (
    REGISTRY_ENTITY,
    REGISTRY_PROPERTY,
    build_registry_provider,
)
from examples.cross_domain.sensor_state import (
    SENSOR_ENTITY,
    SENSOR_PROPERTY,
    build_sensor_provider,
)
from worldstate import Conflict, StateAssertion, Unknown, UnknownReason

UTC = timezone.utc
BASE = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def test_sensor_and_registry_use_same_core_without_semantic_fork() -> None:
    sensor = build_sensor_provider(BASE)
    _, registry = build_registry_provider(BASE)

    sensor_result = sensor.query_state(
        SENSOR_ENTITY,
        SENSOR_PROPERTY,
        BASE + timedelta(minutes=1),
    )
    registry_result = registry.query_state(
        REGISTRY_ENTITY,
        REGISTRY_PROPERTY,
        BASE + timedelta(days=1),
    )

    assert isinstance(sensor_result, StateAssertion)
    assert sensor_result.value == 21.5
    assert isinstance(registry_result, StateAssertion)
    assert registry_result.value == "active"
    assert sensor_result.provenance.method == "reference-resolution"
    assert registry_result.provenance.method == "reference-resolution"


def test_short_lived_sensor_state_expires_without_affecting_registry_semantics() -> None:
    sensor = build_sensor_provider(BASE)
    _, registry = build_registry_provider(BASE)

    sensor_result = sensor.query_state(
        SENSOR_ENTITY,
        SENSOR_PROPERTY,
        BASE + timedelta(minutes=6),
    )
    registry_result = registry.query_state(
        REGISTRY_ENTITY,
        REGISTRY_PROPERTY,
        BASE + timedelta(days=30),
    )

    assert isinstance(sensor_result, Unknown)
    assert sensor_result.reason is UnknownReason.OUTSIDE_VALIDITY
    assert isinstance(registry_result, StateAssertion)
    assert registry_result.value == "active"


def test_sensor_disagreement_is_preserved_as_conflict() -> None:
    sensor = build_sensor_provider(BASE, conflicting=True)

    result = sensor.query_state(
        SENSOR_ENTITY,
        SENSOR_PROPERTY,
        BASE + timedelta(minutes=1),
    )

    assert isinstance(result, Conflict)
    assert result.candidate_refs == ("sensor-claim-a", "sensor-claim-b")
    assert result.evidence_refs == ("sensor-ev-a", "sensor-ev-b")


def test_cross_domain_truth_fidelity_metrics_are_perfect_on_declared_cases() -> None:
    active_sensor = build_sensor_provider(BASE)
    expired_sensor = build_sensor_provider(BASE)
    conflicting_sensor = build_sensor_provider(BASE, conflicting=True)
    _, registry = build_registry_provider(BASE)

    metrics = evaluate_cases(
        (
            BenchmarkCase(
                name="sensor-active",
                provider=active_sensor,
                entity=SENSOR_ENTITY,
                property_key=SENSOR_PROPERTY,
                at=BASE + timedelta(minutes=1),
                expected=ExpectedOutcome.ASSERTION,
                expected_value=21.5,
                validity_case=True,
            ),
            BenchmarkCase(
                name="sensor-expired",
                provider=expired_sensor,
                entity=SENSOR_ENTITY,
                property_key=SENSOR_PROPERTY,
                at=BASE + timedelta(minutes=6),
                expected=ExpectedOutcome.UNKNOWN,
                expected_unknown_reason=UnknownReason.OUTSIDE_VALIDITY,
                validity_case=True,
            ),
            BenchmarkCase(
                name="sensor-conflict",
                provider=conflicting_sensor,
                entity=SENSOR_ENTITY,
                property_key=SENSOR_PROPERTY,
                at=BASE + timedelta(minutes=1),
                expected=ExpectedOutcome.CONFLICT,
            ),
            BenchmarkCase(
                name="registry-active",
                provider=registry,
                entity=REGISTRY_ENTITY,
                property_key=REGISTRY_PROPERTY,
                at=BASE + timedelta(days=1),
                expected=ExpectedOutcome.ASSERTION,
                expected_value="active",
            ),
            BenchmarkCase(
                name="registry-missing-property",
                provider=registry,
                entity=REGISTRY_ENTITY,
                property_key="missing_property",
                at=BASE + timedelta(days=1),
                expected=ExpectedOutcome.UNKNOWN,
                expected_unknown_reason=UnknownReason.NO_EVIDENCE,
            ),
        )
    )

    assert metrics.state_correctness == 1.0
    assert metrics.provenance_coverage == 1.0
    assert metrics.unknown_fidelity == 1.0
    assert metrics.conflict_preservation == 1.0
    assert metrics.validity_accuracy == 1.0
    assert metrics.replayability == 1.0
    assert metrics.unsupported_state_rate == 0.0


def test_example_domain_vocabulary_does_not_leak_into_core() -> None:
    core_root = Path(__file__).parents[1] / "src" / "worldstate"
    core_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted(core_root.glob("*.py"))
    )

    for token in (
        "temperature_c",
        "registration_status",
        "sensor_node",
        "example-registry",
        "example-physical",
    ):
        assert token not in core_text
