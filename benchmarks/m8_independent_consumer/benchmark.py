from __future__ import annotations

import ast
import json
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from examples.independent_consumers.cold_chain.consumer import (
    ColdChainChangeView,
    ColdChainMonitor,
    ColdChainWorldView,
    FactView,
)
from examples.independent_consumers.cold_chain.providers import (
    SHIPMENT_STATUS,
    TEMPERATURE_C,
    build_conflicting_temperature_provider,
    build_registry_provider,
    build_temperature_provider,
    update_registry,
    update_temperature,
)
from examples.providers.projection import ExternalRecordStore, ProjectionWorldStateProvider

CASES_PATH = Path(__file__).with_name("cases.json")
ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=5)
STACK_MODULE_PREFIXES = ("lowa", "geotask", "agentreality")
DOMAIN_CORE_TOKENS = ("cold_chain", "cold-chain", "shipment_status", "temperature_c")
DECISION_FIELD_TOKENS = ("decision", "action", "release", "discard", "compliance", "safe", "alarm")


def _registry_provider(raw: dict[str, Any]):
    if raw["registry_mode"] == "missing":
        return None, ProjectionWorldStateProvider(ExternalRecordStore())
    return build_registry_provider(
        T0,
        status=str(raw.get("registry_status", "in_transit")),
    )


def _temperature_provider(raw: dict[str, Any]):
    mode = raw["temperature_mode"]
    if mode == "conflict":
        return None, build_conflicting_temperature_provider(T0)
    source, provider = build_temperature_provider(
        T0,
        temperature_c=float(raw.get("temperature_c", 4.0)),
    )
    if mode == "outage":
        source.available = False
    return source, provider


def _fact_expected(fact: FactView, raw: dict[str, Any], prefix: str) -> bool:
    expected_kind = raw[f"expected_{prefix}_kind"]
    if fact.kind != expected_kind:
        return False
    expected_value_key = f"expected_{prefix}_value"
    if expected_value_key in raw and fact.value != raw[expected_value_key]:
        return False
    expected_reason_key = f"expected_{prefix}_reason"
    if expected_reason_key in raw and fact.reason != raw[expected_reason_key]:
        return False
    return True


def _run_static_case(raw: dict[str, Any]) -> dict[str, object]:
    _, registry = _registry_provider(raw)
    _, temperature = _temperature_provider(raw)
    view = ColdChainMonitor(registry, temperature).read(T0)
    return {
        "case_id": raw["case_id"],
        "registry": {
            "kind": view.shipment_status.kind,
            "value": view.shipment_status.value,
            "reason": view.shipment_status.reason,
            "supported": bool(view.shipment_status.evidence_refs and view.shipment_status.source_refs)
            if view.shipment_status.kind == "assertion"
            else None,
            "expected_pass": _fact_expected(view.shipment_status, raw, "registry"),
        },
        "temperature": {
            "kind": view.temperature_c.kind,
            "value": view.temperature_c.value,
            "reason": view.temperature_c.reason,
            "supported": bool(view.temperature_c.evidence_refs and view.temperature_c.source_refs)
            if view.temperature_c.kind == "assertion"
            else None,
            "expected_pass": _fact_expected(view.temperature_c, raw, "temperature"),
        },
    }


def _run_temporal(raw: dict[str, Any]) -> dict[str, object]:
    registry_store, registry = build_registry_provider(
        T0,
        status=str(raw["initial_registry_status"]),
    )
    temperature_source, temperature = build_temperature_provider(
        T0,
        temperature_c=float(raw["initial_temperature_c"]),
    )
    watch = ColdChainMonitor(registry, temperature).open_watch(T0)

    if bool(raw.get("apply_registry_update", True)):
        update_registry(
            registry_store,
            T1,
            status=str(raw["updated_registry_status"]),
            version="registry-v2",
        )
    if bool(raw.get("apply_temperature_update", True)):
        update_temperature(
            temperature_source,
            T1,
            temperature_c=float(raw["updated_temperature_c"]),
            source_version="sensor-v2",
            record_version="reading-v2",
        )

    change = watch.poll(T1)
    return {
        "changed_properties": list(change.changed_properties),
        "unavailable_properties": list(change.provider_unavailable_properties),
        "registry_poll_id": change.registry_poll.poll_id,
        "temperature_poll_id": change.temperature_poll.poll_id,
        "expected_pass": (
            list(change.changed_properties) == list(raw["expected_changed_properties"])
            and list(change.provider_unavailable_properties)
            == list(raw["expected_unavailable_properties"])
        ),
    }


def _run_outage_watch(raw: dict[str, Any]) -> dict[str, object]:
    _, registry = build_registry_provider(T0)
    source, temperature = build_temperature_provider(T0)
    watch = ColdChainMonitor(registry, temperature).open_watch(T0)
    source.available = False
    change = watch.poll(T1)
    return {
        "changed_properties": list(change.changed_properties),
        "unavailable_properties": list(change.provider_unavailable_properties),
        "temperature_delta_is_none": change.temperature_poll.delta is None,
        "temperature_advanced": change.temperature_poll.advanced,
        "expected_pass": (
            list(change.changed_properties) == list(raw["expected_changed_properties"])
            and list(change.provider_unavailable_properties)
            == list(raw["expected_unavailable_properties"])
            and change.temperature_poll.delta is None
            and change.temperature_poll.advanced is False
        ),
    }


def _decision_boundary(raw: dict[str, Any]) -> dict[str, object]:
    _, registry = build_registry_provider(T0)
    _, temperature = build_temperature_provider(
        T0,
        temperature_c=float(raw["temperature_c"]),
    )
    view = ColdChainMonitor(registry, temperature).read(T0)
    world_fields = tuple(field.name for field in fields(ColdChainWorldView))
    change_fields = tuple(field.name for field in fields(ColdChainChangeView))
    public_monitor_methods = tuple(
        sorted(
            name
            for name in dir(ColdChainMonitor)
            if not name.startswith("_") and callable(getattr(ColdChainMonitor, name))
        )
    )
    leakage_fields = tuple(
        name
        for name in (*world_fields, *change_fields, *public_monitor_methods)
        if any(token in name.lower() for token in DECISION_FIELD_TOKENS)
    )
    return {
        "temperature_kind": view.temperature_c.kind,
        "temperature_value": view.temperature_c.value,
        "world_view_fields": list(world_fields),
        "change_view_fields": list(change_fields),
        "monitor_methods": list(public_monitor_methods),
        "decision_surface_leakage_fields": list(leakage_fields),
        "expected_pass": (
            view.temperature_c.kind == raw["expected_temperature_kind"]
            and view.temperature_c.value == raw["expected_temperature_value"]
            and not leakage_fields
        ),
    }


def _stack_dependency_count() -> int:
    count = 0
    for relative in (
        "examples/independent_consumers/cold_chain/consumer.py",
        "examples/independent_consumers/cold_chain/providers.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = (node.module,)
            for module in modules:
                if module.split(".", 1)[0].lower() in STACK_MODULE_PREFIXES:
                    count += 1
    return count


def _core_domain_leakage_count() -> int:
    count = 0
    for path in (ROOT / "src" / "worldstate").glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        count += sum(text.count(token) for token in DOMAIN_CORE_TOKENS)
    return count


def run_benchmark(cases_path: Path = CASES_PATH) -> dict[str, object]:
    fixture = json.loads(cases_path.read_text(encoding="utf-8"))
    static_rows = [_run_static_case(raw) for raw in fixture["static_cases"]]
    temporal = _run_temporal(fixture["temporal_case"])
    temporal_replay = _run_temporal(fixture["temporal_case"])
    outage_watch = _run_outage_watch(fixture["outage_watch_case"])
    decision_boundary = _decision_boundary(fixture["decision_boundary_case"])

    fact_results = [
        row[section]
        for row in static_rows
        for section in ("registry", "temperature")
    ]
    fact_count = len(fact_results)
    state_correct_count = sum(bool(fact["expected_pass"]) for fact in fact_results)
    assertion_facts = [fact for fact in fact_results if fact["kind"] == "assertion"]
    supported_assertion_count = sum(bool(fact["supported"]) for fact in assertion_facts)

    expected_unknowns = [
        (raw, section)
        for raw in fixture["static_cases"]
        for section in ("registry", "temperature")
        if raw[f"expected_{section}_kind"] == "unknown"
    ]
    unknown_correct = 0
    for raw, section in expected_unknowns:
        row = next(item for item in static_rows if item["case_id"] == raw["case_id"])
        if row[section]["expected_pass"]:
            unknown_correct += 1

    expected_conflicts = [
        (raw, section)
        for raw in fixture["static_cases"]
        for section in ("registry", "temperature")
        if raw[f"expected_{section}_kind"] == "conflict"
    ]
    conflict_correct = 0
    for raw, section in expected_conflicts:
        row = next(item for item in static_rows if item["case_id"] == raw["case_id"])
        if row[section]["expected_pass"]:
            conflict_correct += 1

    unsupported_state_count = sum(
        fact["kind"] == "assertion" and not bool(fact["supported"])
        for fact in assertion_facts
    )
    stack_dependency_count = _stack_dependency_count()
    core_domain_leakage_count = _core_domain_leakage_count()
    decision_leakage_count = len(decision_boundary["decision_surface_leakage_fields"])
    replay_stable = temporal == temporal_replay

    state_correctness_rate = state_correct_count / fact_count if fact_count else 1.0
    provenance_coverage_rate = (
        supported_assertion_count / len(assertion_facts) if assertion_facts else 1.0
    )
    unknown_fidelity_rate = (
        unknown_correct / len(expected_unknowns) if expected_unknowns else 1.0
    )
    conflict_preservation_rate = (
        conflict_correct / len(expected_conflicts) if expected_conflicts else 1.0
    )
    unsupported_state_rate = (
        unsupported_state_count / len(assertion_facts) if assertion_facts else 0.0
    )

    truth_fidelity_gate = (
        state_correctness_rate == 1.0
        and provenance_coverage_rate == 1.0
        and unknown_fidelity_rate == 1.0
        and conflict_preservation_rate == 1.0
        and unsupported_state_rate == 0.0
    )
    change_gate = bool(temporal["expected_pass"] and outage_watch["expected_pass"] and replay_stable)
    independence_gate = (
        stack_dependency_count == 0
        and core_domain_leakage_count == 0
        and decision_leakage_count == 0
        and bool(decision_boundary["expected_pass"])
    )

    return {
        "contract": "worldstate.m8-independent-consumer-benchmark",
        "version": "0.1",
        "consumer": "cold-chain-shipment-monitor",
        "static_cases": static_rows,
        "temporal_case": temporal,
        "outage_watch_case": outage_watch,
        "decision_boundary_case": decision_boundary,
        "metrics": {
            "static_case_count": len(static_rows),
            "fact_expectation_count": fact_count,
            "state_correct_count": state_correct_count,
            "state_correctness_rate": state_correctness_rate,
            "assertion_fact_count": len(assertion_facts),
            "provenance_supported_assertion_count": supported_assertion_count,
            "provenance_coverage_rate": provenance_coverage_rate,
            "expected_unknown_count": len(expected_unknowns),
            "unknown_fidelity_rate": unknown_fidelity_rate,
            "expected_conflict_count": len(expected_conflicts),
            "conflict_preservation_rate": conflict_preservation_rate,
            "unsupported_state_count": unsupported_state_count,
            "unsupported_state_rate": unsupported_state_rate,
            "temporal_change_fidelity_pass": bool(temporal["expected_pass"]),
            "outage_change_fidelity_pass": bool(outage_watch["expected_pass"]),
            "replay_stability_pass": replay_stable,
            "stack_dependency_count": stack_dependency_count,
            "core_domain_leakage_count": core_domain_leakage_count,
            "domain_decision_leakage_count": decision_leakage_count,
            "direct_worldstate_consumer": True,
        },
        "gates": {
            "truth_fidelity_gate": truth_fidelity_gate,
            "change_gate": change_gate,
            "independence_gate": independence_gate,
            "promotion_gate": truth_fidelity_gate and change_gate and independence_gate,
        },
        "claim_limits": {
            "deterministic_fixture_bound": True,
            "independent_non_lowa_domain": True,
            "official_geotask_required": False,
            "official_agentreality_required": False,
            "core_fork_required": False,
            "domain_specific_resolver_required": False,
            "domain_decision_claim": False,
            "production_cold_chain_compliance_claim": False,
            "live_provider_reliability_claim": False,
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2, sort_keys=True))
