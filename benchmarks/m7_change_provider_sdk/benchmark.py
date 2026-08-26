from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from examples.providers.external import (
    DirectExternalSource,
    DirectExternalWorldStateProvider,
    ExternalStateRecord,
)
from examples.providers.projection import (
    ExternalRecordStore,
    ProjectionWorldStateProvider,
    SoRRecord,
)
from worldstate import (
    ChangeKind,
    ChangePollStatus,
    EntityRef,
    TemporalScope,
    diff_snapshots,
    open_change_cursor,
    provider_change_poll_payload,
)

CASES_PATH = Path(__file__).with_name("cases.json")
T0 = datetime(2026, 8, 26, 2, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)


def _projection(entity: EntityRef, property_key: str, value: str, version: str):
    store = ExternalRecordStore()
    store.put(
        SoRRecord(
            record_id="record-1",
            entity=entity,
            property_key=property_key,
            value=value,
            updated_at=T0 - timedelta(minutes=1),
            version=version,
        )
    )
    return store, ProjectionWorldStateProvider(store)


def _direct(
    entity: EntityRef,
    property_key: str,
    value: str,
    version: str,
    *,
    temporal_scope: TemporalScope | None = None,
):
    source = DirectExternalSource(source_version=version)
    source.put(
        ExternalStateRecord(
            record_id="record-1",
            entity=entity,
            property_key=property_key,
            value=value,
            updated_at=T0 - timedelta(minutes=1),
            record_version=version,
            temporal_scope=temporal_scope,
        )
    )
    return source, DirectExternalWorldStateProvider(source)


def _provider(mode: str, entity: EntityRef, property_key: str, value: str, version: str):
    if mode == "projection":
        return _projection(entity, property_key, value, version)
    if mode == "direct-external":
        return _direct(entity, property_key, value, version)
    raise ValueError(f"unsupported provider_mode: {mode}")


def _update_provider(
    mode: str,
    owner: Any,
    entity: EntityRef,
    property_key: str,
    value: str,
    version: str,
    at: datetime,
) -> None:
    if mode == "projection":
        owner.put(
            SoRRecord(
                record_id="record-1",
                entity=entity,
                property_key=property_key,
                value=value,
                updated_at=at - timedelta(seconds=30),
                version=version,
            )
        )
        return
    if mode == "direct-external":
        owner.source_version = version
        owner.put(
            ExternalStateRecord(
                record_id="record-1",
                entity=entity,
                property_key=property_key,
                value=value,
                updated_at=at - timedelta(seconds=30),
                record_version=version,
            )
        )
        return
    raise ValueError(f"unsupported provider_mode: {mode}")


def _unchanged_case(raw: dict[str, Any], entity: EntityRef, property_key: str) -> dict[str, object]:
    mode = str(raw["provider_mode"])
    value = str(raw["value"])
    version = str(raw["version"])

    _, naive_provider = _provider(mode, entity, property_key, value, version)
    naive_before = naive_provider.get_snapshot(None, T0)
    naive_after = naive_provider.get_snapshot(None, T1)
    naive_delta = diff_snapshots(naive_before, naive_after)

    _, sdk_provider = _provider(mode, entity, property_key, value, version)
    cursor = open_change_cursor(sdk_provider, None, T0)
    prior_ref = cursor.last_good_snapshot.assertions[0].assertion_id
    poll = cursor.poll(T1)
    retained_ref = cursor.last_good_snapshot.assertions[0].assertion_id

    return {
        "case_id": raw["case_id"],
        "provider_mode": mode,
        "expected_status": raw["expected_status"],
        "naive_change_count": len(naive_delta.changes),
        "sdk_status": poll.status.value,
        "sdk_change_count": 0 if poll.delta is None else len(poll.delta.changes),
        "state_ref_retained": prior_ref == retained_ref,
    }


def _changed_case(raw: dict[str, Any], entity: EntityRef, property_key: str) -> dict[str, object]:
    mode = str(raw["provider_mode"])
    owner, provider = _provider(
        mode,
        entity,
        property_key,
        str(raw["before_value"]),
        str(raw["before_version"]),
    )
    cursor = open_change_cursor(provider, None, T0)
    if bool(raw.get("apply_update", True)):
        _update_provider(
            mode,
            owner,
            entity,
            property_key,
            str(raw["after_value"]),
            str(raw["after_version"]),
            T1,
        )
    poll = cursor.poll(T1)
    kinds = [] if poll.delta is None else [change.kind.value for change in poll.delta.changes]
    return {
        "case_id": raw["case_id"],
        "provider_mode": mode,
        "expected_status": raw["expected_status"],
        "expected_change_kind": raw["expected_change_kind"],
        "sdk_status": poll.status.value,
        "change_kinds": kinds,
    }


def _outage_case(entity: EntityRef, property_key: str) -> dict[str, object]:
    naive_source, naive_provider = _direct(entity, property_key, "open", "v1")
    naive_before = naive_provider.get_snapshot(None, T0)
    naive_source.available = False
    naive_after = naive_provider.get_snapshot(None, T1)
    naive_delta = diff_snapshots(naive_before, naive_after)

    source, provider = _direct(entity, property_key, "open", "v1")
    cursor = open_change_cursor(provider, None, T0)
    last_good_ref = cursor.last_good_snapshot.snapshot_id
    source.available = False
    outage = cursor.poll(T1)
    outage_payload = provider_change_poll_payload(outage)

    source.available = True
    source.source_version = "v2"
    source.put(
        ExternalStateRecord(
            record_id="record-1",
            entity=entity,
            property_key=property_key,
            value="closed",
            updated_at=T2 - timedelta(seconds=30),
            record_version="v2",
        )
    )
    recovered = cursor.poll(T2)

    return {
        "naive_change_kinds": [change.kind.value for change in naive_delta.changes],
        "sdk_status": outage.status.value,
        "sdk_advanced": outage.advanced,
        "sdk_delta_is_none": outage.delta is None,
        "diagnostic_reason": outage.diagnostics[0].reason.value,
        "wire_delta_is_none": outage_payload["delta"] is None,
        "recovery_from_last_good": (
            recovered.delta is not None and recovered.delta.from_snapshot_ref == last_good_ref
        ),
        "recovery_change_kinds": (
            [] if recovered.delta is None else [change.kind.value for change in recovered.delta.changes]
        ),
    }


def _validity_case(entity: EntityRef, property_key: str) -> dict[str, object]:
    _, provider = _direct(
        entity,
        property_key,
        "open",
        "v1",
        temporal_scope=TemporalScope(
            start=T0 - timedelta(minutes=1),
            end=T0 + timedelta(minutes=1),
        ),
    )
    cursor = open_change_cursor(provider, None, T0)
    poll = cursor.poll(T1)
    return {
        "status": poll.status.value,
        "change_kinds": [] if poll.delta is None else [change.kind.value for change in poll.delta.changes],
    }


def _replay_sequence(entity: EntityRef, property_key: str):
    store, provider = _projection(entity, property_key, "open", "v1")
    cursor = open_change_cursor(provider, None, T0)
    unchanged = cursor.poll(T1)
    _update_provider("projection", store, entity, property_key, "closed", "v2", T2)
    changed = cursor.poll(T2)
    return unchanged, changed


def run_benchmark(cases_path: Path = CASES_PATH) -> dict[str, object]:
    fixture = json.loads(cases_path.read_text(encoding="utf-8"))
    entity = EntityRef(str(fixture["entity_id"]), entity_type="benchmark-asset")
    property_key = str(fixture["property_key"])

    unchanged_rows = [
        _unchanged_case(raw, entity, property_key) for raw in fixture["unchanged_cases"]
    ]
    changed_rows = [
        _changed_case(raw, entity, property_key) for raw in fixture["changed_cases"]
    ]
    outage = _outage_case(entity, property_key)
    validity = _validity_case(entity, property_key)

    replay_a = _replay_sequence(entity, property_key)
    replay_b = _replay_sequence(entity, property_key)
    replay_stable = replay_a == replay_b

    naive_false_change_count = sum(row["naive_change_count"] > 0 for row in unchanged_rows)
    sdk_false_change_count = sum(
        row["sdk_status"] != row["expected_status"] or row["sdk_change_count"] != 0
        for row in unchanged_rows
    )
    unchanged_count = len(unchanged_rows)
    naive_false_change_rate = naive_false_change_count / unchanged_count if unchanged_count else 0.0
    sdk_false_change_rate = sdk_false_change_count / unchanged_count if unchanged_count else 0.0
    stable_ref_retention_rate = (
        sum(bool(row["state_ref_retained"]) for row in unchanged_rows) / unchanged_count
        if unchanged_count
        else 1.0
    )

    true_change_count = len(changed_rows)
    true_change_detected = sum(
        row["sdk_status"] == row["expected_status"]
        and row["change_kinds"] == [row["expected_change_kind"]]
        for row in changed_rows
    )
    true_change_detection_rate = (
        true_change_detected / true_change_count if true_change_count else 1.0
    )

    naive_outage_false_transition_count = sum(
        kind in {ChangeKind.REMOVED.value, ChangeKind.STATE_CHANGED.value}
        for kind in outage["naive_change_kinds"]
    )
    sdk_outage_false_transition_count = 0 if outage["sdk_delta_is_none"] else 1
    outage_diagnostic_pass = (
        outage["sdk_status"] == fixture["outage_case"]["expected_status"]
        and outage["sdk_advanced"] is False
        and outage["diagnostic_reason"] == "provider_unavailable"
        and outage["wire_delta_is_none"] is True
        and outage["recovery_from_last_good"] is True
        and outage["recovery_change_kinds"] == [ChangeKind.STATE_CHANGED.value]
    )
    validity_expiry_pass = validity["change_kinds"] == [
        fixture["validity_case"]["expected_change_kind"]
    ]

    consumer_neutral_wire_pass = True
    payload = provider_change_poll_payload(replay_a[1])
    rendered = str(payload).lower()
    for forbidden in ("task", "lowa", "geotask"):
        if forbidden in rendered:
            consumer_neutral_wire_pass = False

    persistence_ownership_pass = all(
        not hasattr(provider, "put")
        for _, provider in (
            _projection(entity, property_key, "open", "v1"),
            _direct(entity, property_key, "open", "v1"),
        )
    )

    expected_label_mismatch_count = sum(
        row["sdk_status"] != row["expected_status"] for row in unchanged_rows + changed_rows
    )

    safety_gate = (
        sdk_false_change_rate == 0.0
        and sdk_outage_false_transition_count == 0
        and true_change_detection_rate == 1.0
        and stable_ref_retention_rate == 1.0
        and outage_diagnostic_pass
        and validity_expiry_pass
        and replay_stable
        and consumer_neutral_wire_pass
        and persistence_ownership_pass
        and expected_label_mismatch_count == 0
    )
    utility_gate = (
        naive_false_change_rate > sdk_false_change_rate
        and naive_outage_false_transition_count > sdk_outage_false_transition_count
    )

    return {
        "contract": "worldstate.m7-change-provider-sdk-benchmark",
        "version": "0.1",
        "unchanged_cases": unchanged_rows,
        "changed_cases": changed_rows,
        "outage_case": outage,
        "validity_case": validity,
        "metrics": {
            "provider_mode_count": 2,
            "unchanged_case_count": unchanged_count,
            "naive_false_change_count": naive_false_change_count,
            "naive_false_change_rate": naive_false_change_rate,
            "sdk_false_change_count": sdk_false_change_count,
            "sdk_false_change_rate": sdk_false_change_rate,
            "stable_state_ref_retention_rate": stable_ref_retention_rate,
            "true_change_case_count": true_change_count,
            "true_change_detected_count": true_change_detected,
            "true_change_detection_rate": true_change_detection_rate,
            "naive_outage_false_transition_count": naive_outage_false_transition_count,
            "sdk_outage_false_transition_count": sdk_outage_false_transition_count,
            "outage_diagnostic_pass": outage_diagnostic_pass,
            "validity_expiry_pass": validity_expiry_pass,
            "replay_stability_pass": replay_stable,
            "consumer_neutral_wire_pass": consumer_neutral_wire_pass,
            "persistence_ownership_pass": persistence_ownership_pass,
            "expected_label_mismatch_count": expected_label_mismatch_count,
        },
        "gates": {
            "safety_gate": safety_gate,
            "utility_gate": utility_gate,
            "promotion_gate": safety_gate and utility_gate,
        },
        "claim_limits": {
            "deterministic_fixture_bound": True,
            "provider_modes": ["projection", "direct-external"],
            "pull_based_only": True,
            "event_bus_claim": False,
            "live_provider_reliability_claim": False,
            "production_latency_claim": False,
            "universal_change_transport_claim": False,
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2, sort_keys=True))
