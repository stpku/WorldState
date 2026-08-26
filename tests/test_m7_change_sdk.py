from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
    open_change_cursor,
    provider_change_poll_payload,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 26, 1, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)
T2 = T0 + timedelta(minutes=10)
ENTITY = EntityRef("asset-m7", entity_type="asset")


def _projection(value: str = "open", *, version: str = "p1"):
    store = ExternalRecordStore()
    store.put(
        SoRRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value=value,
            updated_at=T0 - timedelta(minutes=1),
            version=version,
        )
    )
    return store, ProjectionWorldStateProvider(store)


def _direct(
    value: str = "open",
    *,
    source_version: str = "d1",
    record_version: str = "r1",
    temporal_scope: TemporalScope | None = None,
):
    source = DirectExternalSource(source_version=source_version)
    source.put(
        ExternalStateRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value=value,
            updated_at=T0 - timedelta(minutes=1),
            record_version=record_version,
            temporal_scope=temporal_scope,
        )
    )
    return source, DirectExternalWorldStateProvider(source)


def test_projection_poll_suppresses_query_clock_only_churn() -> None:
    _, provider = _projection()
    cursor = open_change_cursor(provider, None, T0)
    initial_ref = cursor.last_good_snapshot.assertions[0].assertion_id

    poll = cursor.poll(T1)

    assert poll.status is ChangePollStatus.UNCHANGED
    assert poll.advanced is True
    assert poll.delta is not None
    assert poll.delta.changes == ()
    assert cursor.last_good_snapshot.assertions[0].assertion_id == initial_ref


def test_direct_external_poll_suppresses_query_clock_only_churn() -> None:
    _, provider = _direct()
    cursor = open_change_cursor(provider, None, T0)
    initial_ref = cursor.last_good_snapshot.assertions[0].assertion_id

    poll = cursor.poll(T1)

    assert poll.status is ChangePollStatus.UNCHANGED
    assert poll.delta is not None
    assert poll.delta.changes == ()
    assert cursor.last_good_snapshot.assertions[0].assertion_id == initial_ref


def test_projection_source_update_emits_bounded_state_change() -> None:
    store, provider = _projection()
    cursor = open_change_cursor(provider, None, T0)

    store.put(
        SoRRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="closed",
            updated_at=T1 - timedelta(seconds=30),
            version="p2",
        )
    )
    poll = cursor.poll(T1)

    assert poll.status is ChangePollStatus.CHANGED
    assert poll.delta is not None
    assert len(poll.delta.changes) == 1
    change = poll.delta.changes[0]
    assert change.kind is ChangeKind.STATE_CHANGED
    assert change.entity == ENTITY
    assert change.property_key == "status"


def test_direct_external_source_update_emits_bounded_state_change() -> None:
    source, provider = _direct()
    cursor = open_change_cursor(provider, None, T0)

    source.source_version = "d2"
    source.put(
        ExternalStateRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="closed",
            updated_at=T1 - timedelta(seconds=30),
            record_version="r2",
        )
    )
    poll = cursor.poll(T1)

    assert poll.status is ChangePollStatus.CHANGED
    assert poll.delta is not None
    assert [change.kind for change in poll.delta.changes] == [ChangeKind.STATE_CHANGED]


def test_provider_outage_is_explicit_and_does_not_advance_last_good_state() -> None:
    source, provider = _direct()
    cursor = open_change_cursor(provider, None, T0)
    last_good_ref = cursor.last_good_snapshot.snapshot_id

    source.available = False
    outage = cursor.poll(T1)

    assert outage.status is ChangePollStatus.PROVIDER_UNAVAILABLE
    assert outage.advanced is False
    assert outage.delta is None
    assert len(outage.diagnostics) == 1
    assert outage.diagnostics[0].reason.value == "provider_unavailable"
    assert cursor.last_good_snapshot.snapshot_id == last_good_ref

    source.available = True
    source.source_version = "d2"
    source.put(
        ExternalStateRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="closed",
            updated_at=T2 - timedelta(seconds=30),
            record_version="r2",
        )
    )
    recovered = cursor.poll(T2)

    assert recovered.status is ChangePollStatus.CHANGED
    assert recovered.delta is not None
    assert recovered.delta.from_snapshot_ref == last_good_ref
    assert [change.kind for change in recovered.delta.changes] == [ChangeKind.STATE_CHANGED]


def test_validity_expiry_remains_explicit_change_not_removal() -> None:
    source, provider = _direct(
        temporal_scope=TemporalScope(start=T0 - timedelta(minutes=2), end=T0 + timedelta(minutes=1))
    )
    cursor = open_change_cursor(provider, None, T0)

    poll = cursor.poll(T1)

    assert poll.status is ChangePollStatus.CHANGED
    assert poll.delta is not None
    assert [change.kind for change in poll.delta.changes] == [ChangeKind.VALIDITY_EXPIRED]
    assert cursor.last_good_snapshot.unknowns[0].reason.value == "outside_validity"
    assert source.available is True


def test_change_poll_wire_is_consumer_neutral_and_embeds_existing_delta_wire() -> None:
    store, provider = _projection()
    cursor = open_change_cursor(provider, None, T0)
    store.put(
        SoRRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="closed",
            updated_at=T1 - timedelta(seconds=30),
            version="p2",
        )
    )

    payload = provider_change_poll_payload(cursor.poll(T1))

    assert payload["contract"] == "worldstate.provider-change-poll"
    assert payload["contract_version"] == "0.1"
    assert payload["status"] == "changed"
    assert payload["delta"]["contract"] == "worldstate.delta"  # type: ignore[index]
    assert payload["delta"]["changes"][0]["kind"] == "state_changed"  # type: ignore[index]
    rendered = str(payload).lower()
    assert "task" not in rendered
    assert "lowa" not in rendered
    assert "geotask" not in rendered


def test_provider_outage_wire_carries_diagnostic_without_false_delta() -> None:
    source, provider = _direct()
    cursor = open_change_cursor(provider, None, T0)
    source.available = False

    payload = provider_change_poll_payload(cursor.poll(T1))

    assert payload["status"] == "provider_unavailable"
    assert payload["advanced"] is False
    assert payload["delta"] is None
    assert payload["diagnostics"][0]["kind"] == "unknown"  # type: ignore[index]
    assert payload["diagnostics"][0]["reason"] == "provider_unavailable"  # type: ignore[index]


def _replay_projection_sequence():
    store, provider = _projection()
    cursor = open_change_cursor(provider, None, T0)
    unchanged = cursor.poll(T1)
    store.put(
        SoRRecord(
            record_id="record-1",
            entity=ENTITY,
            property_key="status",
            value="closed",
            updated_at=T2 - timedelta(seconds=30),
            version="p2",
        )
    )
    changed = cursor.poll(T2)
    return unchanged, changed


def test_change_cursor_sequence_is_replay_stable() -> None:
    first = _replay_projection_sequence()
    replay = _replay_projection_sequence()

    assert first == replay
    assert first[0].poll_id == replay[0].poll_id
    assert first[1].poll_id == replay[1].poll_id
    assert first[1].delta is not None and replay[1].delta is not None
    assert first[1].delta.delta_id == replay[1].delta.delta_id


def test_change_cursor_rejects_reverse_time_and_unavailable_bootstrap() -> None:
    source, provider = _direct()
    cursor = open_change_cursor(provider, None, T0)
    with pytest.raises(ValueError, match="must not precede"):
        cursor.poll(T0 - timedelta(seconds=1))

    source.available = False
    with pytest.raises(RuntimeError, match="unavailable provider"):
        open_change_cursor(provider, None, T1)
