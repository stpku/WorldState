from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from worldstate import (
    CausalChangeObservation,
    CausalRelationKind,
    ChangeKind,
    EntityRef,
    StateChangeRef,
    build_causal_frontier,
    causal_frontier_payload,
    make_causal_relation,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
ENTITY = EntityRef("asset-causal", entity_type="asset")


def change(
    identity: str,
    kind: ChangeKind,
    effective_at: datetime,
    *,
    before: str | None,
    after: str | None,
    source: str = "provider-a",
) -> StateChangeRef:
    return StateChangeRef(
        change_id=f"change://{identity}",
        entity=ENTITY,
        property_key="status",
        kind=kind,
        occurred_at=effective_at,
        from_state_ref=before,
        to_state_ref=after,
        affected_state_refs=tuple(sorted(ref for ref in (before, after) if ref is not None)),
        source_refs=(source,),
    )


def observation(
    identity: str,
    item: StateChangeRef,
    *,
    observed_at: datetime,
    ingested_at: datetime,
    evidence: str | None = None,
) -> CausalChangeObservation:
    return CausalChangeObservation(
        observation_id=f"observation://{identity}",
        change=item,
        effective_at=item.occurred_at,
        observed_at=observed_at,
        ingested_at=ingested_at,
        evidence_refs=(evidence or f"evidence://{identity}",),
    )


def relation(
    kind: CausalRelationKind,
    subject: CausalChangeObservation,
    target: CausalChangeObservation,
    *,
    at: datetime,
):
    return make_causal_relation(
        kind,
        subject.observation_id,
        target.observation_id,
        at,
        evidence_refs=(f"evidence://relation/{kind.value}",),
    )


def test_reality_order_is_independent_from_arrival_and_input_order() -> None:
    a_change = change(
        "a",
        ChangeKind.STATE_CHANGED,
        T0 + timedelta(minutes=1),
        before="state-0",
        after="state-a",
    )
    b_change = change(
        "b",
        ChangeKind.STATE_CHANGED,
        T0 + timedelta(minutes=2),
        before="state-a",
        after="state-b",
    )
    # B arrives first; A is observed and ingested late.
    b = observation(
        "b",
        b_change,
        observed_at=T0 + timedelta(minutes=2, seconds=5),
        ingested_at=T0 + timedelta(minutes=2, seconds=10),
    )
    a = observation(
        "a-late",
        a_change,
        observed_at=T0 + timedelta(minutes=2, seconds=20),
        ingested_at=T0 + timedelta(minutes=3),
    )
    supersedes = relation(
        CausalRelationKind.SUPERSEDES,
        b,
        a,
        at=T0 + timedelta(minutes=3, seconds=1),
    )
    as_of = T0 + timedelta(minutes=4)

    first = build_causal_frontier((b, a), (supersedes,), as_of=as_of)
    replay = build_causal_frontier((a, b), (supersedes,), as_of=as_of)

    assert first.frontier_id == replay.frontier_id
    assert first.active_observation_refs == (b.observation_id,)
    assert first.superseded_observation_refs == (a.observation_id,)
    assert first.max_effective_at == b.effective_at
    assert first.max_ingested_at == a.ingested_at


def test_late_duplicate_cannot_resurrect_superseded_state_or_amplify_frontier() -> None:
    old_change = change(
        "old",
        ChangeKind.BECAME_UNKNOWN,
        T0 + timedelta(minutes=1),
        before="state-0",
        after="unknown-1",
    )
    new_change = change(
        "resolved",
        ChangeKind.UNKNOWN_RESOLVED,
        T0 + timedelta(minutes=2),
        before="unknown-1",
        after="state-2",
    )
    old = observation(
        "old",
        old_change,
        observed_at=T0 + timedelta(minutes=1),
        ingested_at=T0 + timedelta(minutes=1, seconds=1),
        evidence="evidence://old-semantic",
    )
    resolved = observation(
        "resolved",
        new_change,
        observed_at=T0 + timedelta(minutes=2),
        ingested_at=T0 + timedelta(minutes=2, seconds=1),
    )
    late_duplicate = observation(
        "old-duplicate-late",
        old_change,
        observed_at=T0 + timedelta(minutes=1),
        ingested_at=T0 + timedelta(minutes=4),
        evidence="evidence://old-semantic",
    )
    resolves = relation(
        CausalRelationKind.RESOLVES,
        resolved,
        late_duplicate,
        at=T0 + timedelta(minutes=4, seconds=1),
    )

    frontier = build_causal_frontier(
        (late_duplicate, resolved, old),
        (resolves,),
        as_of=T0 + timedelta(minutes=5),
    )

    assert frontier.active_observation_refs == (resolved.observation_id,)
    assert frontier.duplicate_observation_refs == (late_duplicate.observation_id,)
    assert frontier.resolved_observation_refs == (old.observation_id,)
    assert frontier.unresolved_observation_groups == ()


def test_newer_conflicting_evidence_reopens_uncertainty_instead_of_silent_resolution() -> None:
    conflict_change = change(
        "conflict-1",
        ChangeKind.CONFLICT_RAISED,
        T0 + timedelta(minutes=1),
        before="state-0",
        after="conflict-1",
    )
    resolution_change = change(
        "resolution-a",
        ChangeKind.CONFLICT_RESOLVED,
        T0 + timedelta(minutes=2),
        before="conflict-1",
        after="state-a",
    )
    later_conflict_change = change(
        "conflict-2",
        ChangeKind.CONFLICT_RAISED,
        T0 + timedelta(minutes=3),
        before="state-a",
        after="conflict-2",
        source="provider-b",
    )
    raised = observation(
        "conflict-1",
        conflict_change,
        observed_at=T0 + timedelta(minutes=1),
        ingested_at=T0 + timedelta(minutes=1, seconds=1),
    )
    resolved = observation(
        "resolution-a",
        resolution_change,
        observed_at=T0 + timedelta(minutes=2),
        ingested_at=T0 + timedelta(minutes=2, seconds=1),
    )
    later = observation(
        "conflict-2-late-arrival",
        later_conflict_change,
        observed_at=T0 + timedelta(minutes=3),
        ingested_at=T0 + timedelta(minutes=5),
    )
    relations = (
        relation(
            CausalRelationKind.RESOLVES,
            resolved,
            raised,
            at=T0 + timedelta(minutes=2, seconds=2),
        ),
        relation(
            CausalRelationKind.CONFLICTS_WITH,
            later,
            resolved,
            at=T0 + timedelta(minutes=5, seconds=1),
        ),
    )

    frontier = build_causal_frontier(
        (later, raised, resolved),
        relations,
        as_of=T0 + timedelta(minutes=6),
    )

    assert set(frontier.active_observation_refs) == {
        resolved.observation_id,
        later.observation_id,
    }
    assert frontier.unresolved_observation_groups == (
        tuple(sorted((resolved.observation_id, later.observation_id))),
    )


def test_two_concurrent_resolution_candidates_remain_unresolved() -> None:
    conflict = observation(
        "conflict",
        change(
            "conflict",
            ChangeKind.CONFLICT_RAISED,
            T0 + timedelta(minutes=1),
            before="state-0",
            after="conflict-1",
        ),
        observed_at=T0 + timedelta(minutes=1),
        ingested_at=T0 + timedelta(minutes=1, seconds=1),
    )
    r1 = observation(
        "resolution-1",
        change(
            "resolution-1",
            ChangeKind.CONFLICT_RESOLVED,
            T0 + timedelta(minutes=2),
            before="conflict-1",
            after="state-a",
            source="provider-a",
        ),
        observed_at=T0 + timedelta(minutes=2),
        ingested_at=T0 + timedelta(minutes=2, seconds=1),
    )
    r2 = observation(
        "resolution-2",
        change(
            "resolution-2",
            ChangeKind.CONFLICT_RESOLVED,
            T0 + timedelta(minutes=2),
            before="conflict-1",
            after="state-b",
            source="provider-b",
        ),
        observed_at=T0 + timedelta(minutes=2),
        ingested_at=T0 + timedelta(minutes=2, seconds=2),
    )
    relations = (
        relation(CausalRelationKind.RESOLVES, r1, conflict, at=T0 + timedelta(minutes=3)),
        relation(CausalRelationKind.RESOLVES, r2, conflict, at=T0 + timedelta(minutes=3)),
        relation(CausalRelationKind.CONCURRENT_WITH, r1, r2, at=T0 + timedelta(minutes=3)),
    )

    frontier = build_causal_frontier(
        (r2, conflict, r1), relations, as_of=T0 + timedelta(minutes=4)
    )

    assert set(frontier.active_observation_refs) == {r1.observation_id, r2.observation_id}
    assert frontier.unresolved_observation_groups


def test_same_value_with_new_provenance_is_not_transport_duplicate() -> None:
    first = observation(
        "same-value-a",
        change(
            "same-value-a",
            ChangeKind.STATE_CHANGED,
            T0 + timedelta(minutes=1),
            before="state-0",
            after="state-1",
            source="provider-a",
        ),
        observed_at=T0 + timedelta(minutes=1),
        ingested_at=T0 + timedelta(minutes=1),
    )
    second = observation(
        "same-value-b",
        change(
            "same-value-b",
            ChangeKind.STATE_CHANGED,
            T0 + timedelta(minutes=1),
            before="state-0",
            after="state-1",
            source="provider-b",
        ),
        observed_at=T0 + timedelta(minutes=1),
        ingested_at=T0 + timedelta(minutes=2),
    )

    frontier = build_causal_frontier((second, first), (), as_of=T0 + timedelta(minutes=3))

    assert frontier.duplicate_observation_refs == ()
    assert len(frontier.active_observation_refs) == 2
    assert frontier.unresolved_observation_groups


def test_false_supersession_and_directional_cycles_fail_closed() -> None:
    older = observation(
        "older",
        change(
            "older",
            ChangeKind.STATE_CHANGED,
            T0 + timedelta(minutes=1),
            before="state-0",
            after="state-1",
        ),
        observed_at=T0 + timedelta(minutes=1),
        ingested_at=T0 + timedelta(minutes=1),
    )
    newer = observation(
        "newer",
        change(
            "newer",
            ChangeKind.STATE_CHANGED,
            T0 + timedelta(minutes=2),
            before="state-1",
            after="state-2",
        ),
        observed_at=T0 + timedelta(minutes=2),
        ingested_at=T0 + timedelta(minutes=2),
    )
    false_relation = relation(
        CausalRelationKind.SUPERSEDES,
        older,
        newer,
        at=T0 + timedelta(minutes=3),
    )
    with pytest.raises(ValueError, match="cannot be effective before"):
        build_causal_frontier((older, newer), (false_relation,), as_of=T0 + timedelta(minutes=4))

    same_time_newer = observation(
        "same-time-newer",
        replace_change_time(newer.change, older.effective_at),
        observed_at=T0 + timedelta(minutes=2),
        ingested_at=T0 + timedelta(minutes=2),
    )
    cycle = (
        relation(
            CausalRelationKind.SUPERSEDES,
            same_time_newer,
            older,
            at=T0 + timedelta(minutes=3),
        ),
        relation(
            CausalRelationKind.SUPERSEDES,
            older,
            same_time_newer,
            at=T0 + timedelta(minutes=3),
        ),
    )
    with pytest.raises(ValueError, match="directional cycle"):
        build_causal_frontier(
            (older, same_time_newer), cycle, as_of=T0 + timedelta(minutes=4)
        )


def replace_change_time(item: StateChangeRef, at: datetime) -> StateChangeRef:
    return StateChangeRef(
        change_id=item.change_id + "-same-time",
        entity=item.entity,
        property_key=item.property_key,
        kind=item.kind,
        occurred_at=at,
        from_state_ref=item.from_state_ref,
        to_state_ref=item.to_state_ref,
        affected_state_refs=item.affected_state_refs,
        source_refs=item.source_refs,
    )


def test_frontier_wire_preserves_three_times_lineage_and_is_replay_stable() -> None:
    item = observation(
        "wire",
        change(
            "wire",
            ChangeKind.STATE_CHANGED,
            T0 + timedelta(minutes=1),
            before="state-0",
            after="state-1",
        ),
        observed_at=T0 + timedelta(minutes=1, seconds=10),
        ingested_at=T0 + timedelta(minutes=2),
    )
    frontier = build_causal_frontier((item,), (), as_of=T0 + timedelta(minutes=3))
    replay = build_causal_frontier((item,), (), as_of=T0 + timedelta(minutes=3))
    payload = causal_frontier_payload(frontier, (item,), ())

    assert frontier == replay
    assert payload["contract"] == "worldstate.causal-frontier"
    assert payload["frontier_id"] == frontier.frontier_id
    wire_observation = payload["observations"][0]
    assert wire_observation["effective_at"] == "2026-08-27T08:01:00Z"
    assert wire_observation["observed_at"] == "2026-08-27T08:01:10Z"
    assert wire_observation["ingested_at"] == "2026-08-27T08:02:00Z"
    assert "task" not in str(payload).lower()
    assert "lowa" not in str(payload).lower()
