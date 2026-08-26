from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from examples.independent_consumers.cold_chain.consumer import (
    ColdChainChangeView,
    ColdChainMonitor,
    ColdChainWorldView,
)
from examples.independent_consumers.cold_chain.providers import (
    SHIPMENT,
    SHIPMENT_STATUS,
    TEMPERATURE_C,
    build_conflicting_temperature_provider,
    build_registry_provider,
    build_temperature_provider,
    update_registry,
    update_temperature,
)
from examples.providers.projection import ExternalRecordStore, ProjectionWorldStateProvider

UTC = timezone.utc
T0 = datetime(2026, 8, 26, 3, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)


def test_healthy_consumer_reads_registry_and_temperature_with_provenance() -> None:
    _, registry = build_registry_provider(T0)
    _, temperature = build_temperature_provider(T0, temperature_c=4.2)
    view = ColdChainMonitor(registry, temperature).read(T0)

    assert view.entity == SHIPMENT
    assert view.shipment_status.kind == "assertion"
    assert view.shipment_status.value == "in_transit"
    assert view.shipment_status.evidence_refs
    assert view.shipment_status.source_refs
    assert view.temperature_c.kind == "assertion"
    assert view.temperature_c.value == 4.2
    assert view.temperature_c.evidence_refs
    assert view.temperature_c.source_refs


def test_missing_registry_fact_remains_unknown() -> None:
    registry = ProjectionWorldStateProvider(ExternalRecordStore())
    _, temperature = build_temperature_provider(T0)
    view = ColdChainMonitor(registry, temperature).read(T0)

    assert view.shipment_status.kind == "unknown"
    assert view.shipment_status.value is None
    assert view.shipment_status.reason == "no_evidence"
    assert view.temperature_c.kind == "assertion"


def test_conflicting_sensor_readings_remain_conflict() -> None:
    _, registry = build_registry_provider(T0)
    temperature = build_conflicting_temperature_provider(T0)
    view = ColdChainMonitor(registry, temperature).read(T0)

    assert view.temperature_c.kind == "conflict"
    assert view.temperature_c.value is None
    assert len(view.temperature_c.evidence_refs) == 2
    assert "incompatible" in (view.temperature_c.reason or "")


def test_provider_outage_is_exposed_as_unknown_not_domain_decision() -> None:
    _, registry = build_registry_provider(T0)
    source, temperature = build_temperature_provider(T0)
    source.available = False

    view = ColdChainMonitor(registry, temperature).read(T0)

    assert view.temperature_c.kind == "unknown"
    assert view.temperature_c.reason == "provider_unavailable"
    assert view.temperature_c.value is None


def test_independent_watch_surfaces_both_registry_and_sensor_changes() -> None:
    registry_store, registry = build_registry_provider(T0)
    temperature_source, temperature = build_temperature_provider(T0, temperature_c=4.0)
    watch = ColdChainMonitor(registry, temperature).open_watch(T0)

    update_registry(registry_store, T1, status="arrived", version="registry-v2")
    update_temperature(
        temperature_source,
        T1,
        temperature_c=7.5,
        source_version="sensor-v2",
        record_version="reading-v2",
    )
    change = watch.poll(T1)

    assert change.changed_properties == (SHIPMENT_STATUS, TEMPERATURE_C)
    assert change.provider_unavailable_properties == ()
    assert change.registry_poll.delta is not None
    assert change.temperature_poll.delta is not None
    assert [item.property_key for item in change.registry_poll.delta.changes] == [SHIPMENT_STATUS]
    assert [item.property_key for item in change.temperature_poll.delta.changes] == [TEMPERATURE_C]


def test_sensor_outage_does_not_fabricate_temperature_change() -> None:
    _, registry = build_registry_provider(T0)
    source, temperature = build_temperature_provider(T0)
    watch = ColdChainMonitor(registry, temperature).open_watch(T0)
    source.available = False

    change = watch.poll(T1)

    assert change.changed_properties == ()
    assert change.provider_unavailable_properties == (TEMPERATURE_C,)
    assert change.temperature_poll.delta is None
    assert change.temperature_poll.advanced is False


def _replay_sequence():
    registry_store, registry = build_registry_provider(T0)
    temperature_source, temperature = build_temperature_provider(T0, temperature_c=4.0)
    monitor = ColdChainMonitor(registry, temperature)
    initial = monitor.read(T0)
    watch = monitor.open_watch(T0)
    update_registry(registry_store, T1, status="arrived", version="registry-v2")
    update_temperature(
        temperature_source,
        T1,
        temperature_c=7.5,
        source_version="sensor-v2",
        record_version="reading-v2",
    )
    change = watch.poll(T1)
    final = monitor.read(T1)
    return initial, change, final


def test_independent_consumer_sequence_is_replay_stable() -> None:
    first = _replay_sequence()
    replay = _replay_sequence()

    assert first == replay
    assert first[1].registry_poll.poll_id == replay[1].registry_poll.poll_id
    assert first[1].temperature_poll.poll_id == replay[1].temperature_poll.poll_id


def test_extreme_temperature_is_still_a_fact_not_release_or_discard_decision() -> None:
    _, registry = build_registry_provider(T0)
    _, temperature = build_temperature_provider(T0, temperature_c=12.0)
    view = ColdChainMonitor(registry, temperature).read(T0)

    assert view.temperature_c.kind == "assertion"
    assert view.temperature_c.value == 12.0
    assert {field.name for field in fields(ColdChainWorldView)} == {
        "entity",
        "observed_at",
        "shipment_status",
        "temperature_c",
    }
    assert {field.name for field in fields(ColdChainChangeView)} == {
        "observed_at",
        "registry_poll",
        "temperature_poll",
        "changed_properties",
        "provider_unavailable_properties",
    }


def test_consumer_has_no_stack_or_task_engine_dependency() -> None:
    root = Path(__file__).parents[1]
    text = "\n".join(
        (root / path).read_text(encoding="utf-8").lower()
        for path in (
            "examples/independent_consumers/cold_chain/consumer.py",
            "examples/independent_consumers/cold_chain/providers.py",
        )
    )

    assert "import lowa" not in text
    assert "import geotask" not in text
    assert "import agentreality" not in text
    assert "from lowa" not in text
    assert "from geotask" not in text
    assert "from agentreality" not in text
