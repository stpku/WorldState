from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TypeAlias

from .ids import semantic_id
from .models import (
    Conflict,
    EntityRef,
    StateAssertion,
    StateQueryResult,
    Unknown,
    UnknownReason,
    WorldStateSnapshot,
)

CHANGE_CONTRACT_VERSION = "0.1"


class ChangeKind(str, Enum):
    ASSERTED = "asserted"
    STATE_CHANGED = "state_changed"
    VALIDITY_EXPIRED = "validity_expired"
    BECAME_UNKNOWN = "became_unknown"
    UNKNOWN_RESOLVED = "unknown_resolved"
    CONFLICT_RAISED = "conflict_raised"
    CONFLICT_RESOLVED = "conflict_resolved"
    UNKNOWN_CHANGED = "unknown_changed"
    CONFLICT_CHANGED = "conflict_changed"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class StateChangeRef:
    change_id: str
    entity: EntityRef
    property_key: str
    kind: ChangeKind
    occurred_at: datetime
    from_state_ref: str | None = None
    to_state_ref: str | None = None
    affected_state_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    contract_version: str = CHANGE_CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class WorldStateDelta:
    delta_id: str
    from_snapshot_ref: str
    to_snapshot_ref: str
    as_of: datetime
    changes: tuple[StateChangeRef, ...]
    contract_version: str = CHANGE_CONTRACT_VERSION


_Key: TypeAlias = tuple[str, str]


def _result_key(result: StateQueryResult) -> _Key | None:
    entity = getattr(result, "entity", None)
    property_key = getattr(result, "property_key", None)
    if entity is None or property_key is None:
        return None
    return (entity.entity_id, property_key)


def _result_ref(result: StateQueryResult) -> str:
    if isinstance(result, StateAssertion):
        return result.assertion_id
    if isinstance(result, Unknown):
        return result.unknown_id
    if isinstance(result, Conflict):
        return result.conflict_id
    raise TypeError(f"unsupported state result: {type(result).__name__}")


def _source_refs(result: StateQueryResult | None) -> tuple[str, ...]:
    if isinstance(result, StateAssertion):
        return result.provenance.source_refs
    return ()


def _snapshot_index(snapshot: WorldStateSnapshot) -> dict[_Key, StateQueryResult]:
    indexed: dict[_Key, StateQueryResult] = {}
    for result in (*snapshot.assertions, *snapshot.unknowns, *snapshot.conflicts):
        key = _result_key(result)
        if key is None:
            continue
        if key in indexed:
            raise ValueError(
                "snapshot contains multiple state results for "
                f"entity={key[0]!r} property_key={key[1]!r}"
            )
        indexed[key] = result
    return indexed


def _change_kind(before: StateQueryResult | None, after: StateQueryResult | None) -> ChangeKind:
    if before is None:
        if isinstance(after, Conflict):
            return ChangeKind.CONFLICT_RAISED
        return ChangeKind.ASSERTED
    if after is None:
        return ChangeKind.REMOVED

    if isinstance(before, StateAssertion) and isinstance(after, StateAssertion):
        return ChangeKind.STATE_CHANGED
    if isinstance(before, StateAssertion) and isinstance(after, Unknown):
        return (
            ChangeKind.VALIDITY_EXPIRED
            if after.reason is UnknownReason.OUTSIDE_VALIDITY
            else ChangeKind.BECAME_UNKNOWN
        )
    if isinstance(before, StateAssertion) and isinstance(after, Conflict):
        return ChangeKind.CONFLICT_RAISED

    if isinstance(before, Unknown) and isinstance(after, StateAssertion):
        return ChangeKind.UNKNOWN_RESOLVED
    if isinstance(before, Unknown) and isinstance(after, Conflict):
        return ChangeKind.CONFLICT_RAISED
    if isinstance(before, Unknown) and isinstance(after, Unknown):
        return ChangeKind.UNKNOWN_CHANGED

    if isinstance(before, Conflict) and isinstance(after, StateAssertion):
        return ChangeKind.CONFLICT_RESOLVED
    if isinstance(before, Conflict) and isinstance(after, Unknown):
        return ChangeKind.CONFLICT_RESOLVED
    if isinstance(before, Conflict) and isinstance(after, Conflict):
        return ChangeKind.CONFLICT_CHANGED

    raise TypeError(
        f"unsupported state transition: {type(before).__name__} -> {type(after).__name__}"
    )


def _same_state(before: StateQueryResult, after: StateQueryResult) -> bool:
    return _result_ref(before) == _result_ref(after) and before == after


def diff_snapshots(
    before: WorldStateSnapshot,
    after: WorldStateSnapshot,
) -> WorldStateDelta:
    """Build a deterministic, bounded delta between two immutable snapshots.

    v0.1 is intentionally key-addressable: only results carrying both entity and
    property_key participate in the delta. Unscoped diagnostic Unknown values are
    preserved in snapshots but are not routable change events.
    """
    if after.as_of < before.as_of:
        raise ValueError("after snapshot must not precede before snapshot")

    before_index = _snapshot_index(before)
    after_index = _snapshot_index(after)
    changes: list[StateChangeRef] = []

    for key in sorted(set(before_index) | set(after_index)):
        old = before_index.get(key)
        new = after_index.get(key)
        if old is not None and new is not None and _same_state(old, new):
            continue

        anchor = new if new is not None else old
        assert anchor is not None
        entity = getattr(anchor, "entity")
        property_key = getattr(anchor, "property_key")
        old_ref = None if old is None else _result_ref(old)
        new_ref = None if new is None else _result_ref(new)
        affected_refs = tuple(sorted(ref for ref in (old_ref, new_ref) if ref is not None))
        source_refs = tuple(sorted(set(_source_refs(old)) | set(_source_refs(new))))
        kind = _change_kind(old, new)
        payload = {
            "entity": entity,
            "property_key": property_key,
            "kind": kind,
            "occurred_at": after.as_of,
            "from_state_ref": old_ref,
            "to_state_ref": new_ref,
            "affected_state_refs": affected_refs,
            "source_refs": source_refs,
            "contract_version": CHANGE_CONTRACT_VERSION,
        }
        changes.append(
            StateChangeRef(
                change_id=semantic_id("change", payload),
                entity=entity,
                property_key=property_key,
                kind=kind,
                occurred_at=after.as_of,
                from_state_ref=old_ref,
                to_state_ref=new_ref,
                affected_state_refs=affected_refs,
                source_refs=source_refs,
            )
        )

    ordered = tuple(changes)
    delta_payload = {
        "from_snapshot_ref": before.snapshot_id,
        "to_snapshot_ref": after.snapshot_id,
        "as_of": after.as_of,
        "change_refs": tuple(item.change_id for item in ordered),
        "contract_version": CHANGE_CONTRACT_VERSION,
    }
    return WorldStateDelta(
        delta_id=semantic_id("delta", delta_payload),
        from_snapshot_ref=before.snapshot_id,
        to_snapshot_ref=after.snapshot_id,
        as_of=after.as_of,
        changes=ordered,
    )


def state_change_payload(change: StateChangeRef) -> dict[str, object]:
    return {
        "contract": "worldstate.state-change-ref",
        "contract_version": change.contract_version,
        "change_id": change.change_id,
        "entity": {
            "entity_id": change.entity.entity_id,
            "entity_type": change.entity.entity_type,
            "namespace": change.entity.namespace,
        },
        "property_key": change.property_key,
        "kind": change.kind.value,
        "occurred_at": change.occurred_at.isoformat().replace("+00:00", "Z"),
        "from_state_ref": change.from_state_ref,
        "to_state_ref": change.to_state_ref,
        "affected_state_refs": list(change.affected_state_refs),
        "source_refs": list(change.source_refs),
    }


def world_state_delta_payload(delta: WorldStateDelta) -> dict[str, object]:
    return {
        "contract": "worldstate.delta",
        "contract_version": delta.contract_version,
        "delta_id": delta.delta_id,
        "from_snapshot_ref": delta.from_snapshot_ref,
        "to_snapshot_ref": delta.to_snapshot_ref,
        "as_of": delta.as_of.isoformat().replace("+00:00", "Z"),
        "changes": [state_change_payload(change) for change in delta.changes],
    }
