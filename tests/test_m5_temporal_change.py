from datetime import datetime, timedelta, timezone

import pytest

from worldstate import (
    ChangeKind,
    Conflict,
    EntityRef,
    EpistemicMode,
    Provenance,
    StateAssertion,
    Unknown,
    UnknownReason,
    Validity,
    WorldStateSnapshot,
    diff_snapshots,
    world_state_delta_payload,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 25, 4, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=5)


def provenance(*sources: str) -> Provenance:
    return Provenance(
        evidence_refs=("ev-1",),
        source_refs=sources or ("source-1",),
        method="test",
    )


def assertion(
    assertion_id: str,
    *,
    entity_id: str = "site-1",
    property_key: str = "airspace_status",
    value: str = "approved",
    valid_until: datetime | None = None,
) -> StateAssertion:
    return StateAssertion(
        assertion_id=assertion_id,
        entity=EntityRef(entity_id=entity_id, entity_type="site"),
        property_key=property_key,
        value=value,
        epistemic_mode=EpistemicMode.OBSERVED,
        validity=Validity(resolved_at=T0, valid_from=T0, valid_until=valid_until),
        provenance=provenance("authority-record"),
        version="0.1",
    )


def snapshot(
    snapshot_id: str,
    *,
    at: datetime,
    assertions=(),
    unknowns=(),
    conflicts=(),
) -> WorldStateSnapshot:
    return WorldStateSnapshot(
        snapshot_id=snapshot_id,
        as_of=at,
        created_at=at,
        version="0.1",
        assertions=tuple(assertions),
        unknowns=tuple(unknowns),
        conflicts=tuple(conflicts),
    )


def test_delta_omits_unchanged_state_and_is_deterministic() -> None:
    stable = assertion("state-stable")
    before = snapshot("snap-0", at=T0, assertions=(stable,))
    after = snapshot("snap-1", at=T1, assertions=(stable,))

    first = diff_snapshots(before, after)
    second = diff_snapshots(before, after)

    assert first == second
    assert first.delta_id == second.delta_id
    assert first.changes == ()


def test_validity_expiry_is_explicit_not_silent_removal() -> None:
    old = assertion("state-approved", valid_until=T0 + timedelta(minutes=1))
    expired = Unknown(
        unknown_id="unknown-expired",
        reason=UnknownReason.OUTSIDE_VALIDITY,
        as_of=T1,
        entity=old.entity,
        property_key=old.property_key,
        missing=("current_authoritative_record",),
    )
    delta = diff_snapshots(
        snapshot("snap-before", at=T0, assertions=(old,)),
        snapshot("snap-after", at=T1, unknowns=(expired,)),
    )

    assert len(delta.changes) == 1
    change = delta.changes[0]
    assert change.kind is ChangeKind.VALIDITY_EXPIRED
    assert change.from_state_ref == "state-approved"
    assert change.to_state_ref == "unknown-expired"
    assert change.affected_state_refs == ("state-approved", "unknown-expired")
    assert change.source_refs == ("authority-record",)


def test_state_change_and_conflict_raise_are_bounded_to_changed_keys() -> None:
    old_status = assertion("state-status-old", property_key="status", value="open")
    stable_capacity = assertion("state-capacity", property_key="capacity", value="10")
    new_status = assertion("state-status-new", property_key="status", value="closed")
    conflict = Conflict(
        conflict_id="conflict-route",
        entity=EntityRef("site-1", entity_type="site"),
        property_key="route_available",
        candidate_refs=("claim-a", "claim-b"),
        evidence_refs=("ev-a", "ev-b"),
        reason="authoritative sources disagree",
        as_of=T1,
    )

    delta = diff_snapshots(
        snapshot("snap-before", at=T0, assertions=(old_status, stable_capacity)),
        snapshot(
            "snap-after",
            at=T1,
            assertions=(new_status, stable_capacity),
            conflicts=(conflict,),
        ),
    )

    assert [(c.property_key, c.kind) for c in delta.changes] == [
        ("route_available", ChangeKind.CONFLICT_RAISED),
        ("status", ChangeKind.STATE_CHANGED),
    ]
    assert all(c.property_key != "capacity" for c in delta.changes)


def test_unknown_and_conflict_resolution_are_explicit() -> None:
    entity = EntityRef("site-1", entity_type="site")
    unknown = Unknown(
        unknown_id="unknown-status",
        reason=UnknownReason.NO_EVIDENCE,
        as_of=T0,
        entity=entity,
        property_key="status",
    )
    conflict = Conflict(
        conflict_id="conflict-capacity",
        entity=entity,
        property_key="capacity",
        candidate_refs=("a", "b"),
        evidence_refs=("ea", "eb"),
        reason="disagree",
        as_of=T0,
    )
    status = assertion("state-status", property_key="status", value="open")
    capacity = assertion("state-capacity", property_key="capacity", value="12")

    delta = diff_snapshots(
        snapshot("snap-before", at=T0, unknowns=(unknown,), conflicts=(conflict,)),
        snapshot("snap-after", at=T1, assertions=(status, capacity)),
    )

    assert [(c.property_key, c.kind) for c in delta.changes] == [
        ("capacity", ChangeKind.CONFLICT_RESOLVED),
        ("status", ChangeKind.UNKNOWN_RESOLVED),
    ]


def test_delta_wire_contract_is_consumer_neutral() -> None:
    old = assertion("state-old", property_key="status", value="open")
    new = assertion("state-new", property_key="status", value="closed")
    delta = diff_snapshots(
        snapshot("snap-before", at=T0, assertions=(old,)),
        snapshot("snap-after", at=T1, assertions=(new,)),
    )

    payload = world_state_delta_payload(delta)

    assert payload["contract"] == "worldstate.delta"
    assert payload["contract_version"] == "0.1"
    assert payload["from_snapshot_ref"] == "snap-before"
    assert payload["to_snapshot_ref"] == "snap-after"
    assert payload["changes"][0]["kind"] == "state_changed"
    assert "task" not in str(payload).lower()
    assert "lowa" not in str(payload).lower()


def test_delta_rejects_reverse_time() -> None:
    with pytest.raises(ValueError, match="must not precede"):
        diff_snapshots(snapshot("later", at=T1), snapshot("earlier", at=T0))


def test_duplicate_key_in_one_snapshot_fails_closed() -> None:
    state = assertion("state-1", property_key="status")
    unknown = Unknown(
        unknown_id="unknown-1",
        reason=UnknownReason.NO_EVIDENCE,
        as_of=T0,
        entity=state.entity,
        property_key="status",
    )
    before = snapshot("bad", at=T0, assertions=(state,), unknowns=(unknown,))

    with pytest.raises(ValueError, match="multiple state results"):
        diff_snapshots(before, snapshot("after", at=T1))
