from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .change import WorldStateDelta, diff_snapshots, world_state_delta_payload
from .ids import semantic_id
from .models import (
    Conflict,
    SpatialScope,
    StateAssertion,
    StateQueryResult,
    Unknown,
    UnknownReason,
    WorldStateSnapshot,
)
from .provider import WorldStateProvider
from .snapshot import build_snapshot
from .wire import state_query_result_payload

CHANGE_POLL_CONTRACT_VERSION = "0.1"
CHANGE_POLL_CONTRACT_ID = "worldstate.provider-change-poll"


class ChangePollStatus(str, Enum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True, slots=True)
class ProviderChangePoll:
    """One deterministic pull observation over a WorldStateProvider.

    A provider outage is reported as an explicit diagnostic poll with no state
    delta and does not advance the caller's last-good snapshot boundary.
    """

    poll_id: str
    status: ChangePollStatus
    observed_at: datetime
    previous_snapshot_ref: str
    observed_snapshot_ref: str
    advanced: bool
    delta: WorldStateDelta | None = None
    diagnostics: tuple[Unknown, ...] = ()
    contract_version: str = CHANGE_POLL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.poll_id.strip():
            raise ValueError("poll_id must be a non-empty string")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be timezone-aware UTC")
        if not self.previous_snapshot_ref.strip() or not self.observed_snapshot_ref.strip():
            raise ValueError("snapshot refs must be non-empty strings")
        if self.status is ChangePollStatus.PROVIDER_UNAVAILABLE:
            if self.delta is not None or self.advanced:
                raise ValueError("provider-unavailable poll must not advance or emit delta")
            if not self.diagnostics:
                raise ValueError("provider-unavailable poll requires diagnostics")
        else:
            if self.delta is None or not self.advanced:
                raise ValueError("healthy poll must advance and include a delta")
            if self.diagnostics:
                raise ValueError("healthy poll must not carry provider-unavailable diagnostics")
            if self.delta.from_snapshot_ref != self.previous_snapshot_ref:
                raise ValueError("delta must start from previous_snapshot_ref")
            if self.delta.to_snapshot_ref != self.observed_snapshot_ref:
                raise ValueError("delta must end at observed_snapshot_ref")
            expected_status = (
                ChangePollStatus.CHANGED if self.delta.changes else ChangePollStatus.UNCHANGED
            )
            if self.status is not expected_status:
                raise ValueError("poll status does not match delta change count")


class ProviderChangeCursor:
    """Pull-based change cursor over any synchronous WorldStateProvider.

    The cursor stores only the last good immutable snapshot. It does not own the
    provider's persistence or update path and introduces no event infrastructure.
    """

    def __init__(
        self,
        provider: WorldStateProvider,
        scope: SpatialScope | None,
        initial_snapshot: WorldStateSnapshot,
    ) -> None:
        self._provider = provider
        self._scope = scope
        self._last_good_snapshot = initial_snapshot

    @property
    def last_good_snapshot(self) -> WorldStateSnapshot:
        return self._last_good_snapshot

    @property
    def scope(self) -> SpatialScope | None:
        return self._scope

    def poll(self, at: datetime) -> ProviderChangePoll:
        if at.tzinfo is None or at.utcoffset() != timedelta(0):
            raise ValueError("poll time must be timezone-aware UTC")
        if at < self._last_good_snapshot.as_of:
            raise ValueError("poll time must not precede last good snapshot")

        observed = self._provider.get_snapshot(self._scope, at)
        unavailable = _provider_unavailable_diagnostics(observed)
        if unavailable:
            return _build_unavailable_poll(self._last_good_snapshot, observed, unavailable, at)

        stabilized = _stabilize_snapshot(self._last_good_snapshot, observed)
        delta = diff_snapshots(self._last_good_snapshot, stabilized)
        status = ChangePollStatus.CHANGED if delta.changes else ChangePollStatus.UNCHANGED
        poll = _build_healthy_poll(self._last_good_snapshot, stabilized, delta, status, at)
        self._last_good_snapshot = stabilized
        return poll


def open_change_cursor(
    provider: WorldStateProvider,
    scope: SpatialScope | None,
    at: datetime,
) -> ProviderChangeCursor:
    """Bootstrap a pull cursor from one healthy provider snapshot.

    Bootstrap fails closed if the provider reports itself unavailable because no
    supported last-good state exists yet.
    """

    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise ValueError("bootstrap time must be timezone-aware UTC")
    initial = provider.get_snapshot(scope, at)
    diagnostics = _provider_unavailable_diagnostics(initial)
    if diagnostics:
        raise RuntimeError("cannot bootstrap change cursor from unavailable provider")
    return ProviderChangeCursor(provider, scope, initial)


def provider_change_poll_payload(poll: ProviderChangePoll) -> dict[str, object]:
    return {
        "contract": CHANGE_POLL_CONTRACT_ID,
        "contract_version": poll.contract_version,
        "poll_id": poll.poll_id,
        "status": poll.status.value,
        "observed_at": poll.observed_at.isoformat().replace("+00:00", "Z"),
        "previous_snapshot_ref": poll.previous_snapshot_ref,
        "observed_snapshot_ref": poll.observed_snapshot_ref,
        "advanced": poll.advanced,
        "delta": None if poll.delta is None else world_state_delta_payload(poll.delta),
        "diagnostics": [state_query_result_payload(item) for item in poll.diagnostics],
    }


def _stabilize_snapshot(
    previous: WorldStateSnapshot,
    observed: WorldStateSnapshot,
) -> WorldStateSnapshot:
    """Retain prior state refs when only query-time metadata changed.

    Provider implementations may resolve the same external record at a new query
    time and therefore emit a new assertion/unknown/conflict identifier even when
    the underlying supported state did not change. M7 suppresses that clock-only
    churn while preserving changes to value, evidence/provenance, provider/source
    version, validity window, uncertainty, spatial scope, or conflict candidates.
    """

    previous_index = _state_index(previous)
    stabilized: list[StateQueryResult] = []
    for current in (*observed.assertions, *observed.unknowns, *observed.conflicts):
        key = _state_key(current)
        prior = None if key is None else previous_index.get(key)
        stabilized.append(prior if prior is not None and _same_supported_state(prior, current) else current)

    return build_snapshot(
        stabilized,
        as_of=observed.as_of,
        scope=observed.scope,
        source_versions=observed.source_versions,
        created_at=observed.created_at,
        version=observed.version,
    )


def _state_key(result: StateQueryResult) -> tuple[str, str] | None:
    entity = getattr(result, "entity", None)
    property_key = getattr(result, "property_key", None)
    if entity is None or property_key is None:
        return None
    return (entity.entity_id, property_key)


def _state_index(snapshot: WorldStateSnapshot) -> dict[tuple[str, str], StateQueryResult]:
    indexed: dict[tuple[str, str], StateQueryResult] = {}
    for result in (*snapshot.assertions, *snapshot.unknowns, *snapshot.conflicts):
        key = _state_key(result)
        if key is None:
            continue
        if key in indexed:
            raise ValueError("snapshot contains duplicate state proposition")
        indexed[key] = result
    return indexed


def _same_supported_state(before: StateQueryResult, after: StateQueryResult) -> bool:
    if type(before) is not type(after):
        return False
    if isinstance(before, StateAssertion) and isinstance(after, StateAssertion):
        return (
            before.entity == after.entity
            and before.property_key == after.property_key
            and before.value == after.value
            and before.epistemic_mode == after.epistemic_mode
            and before.provenance == after.provenance
            and before.version == after.version
            and before.uncertainty == after.uncertainty
            and before.spatial_scope == after.spatial_scope
            and before.validity.valid_from == after.validity.valid_from
            and before.validity.valid_until == after.validity.valid_until
            and before.validity.superseded_by == after.validity.superseded_by
        )
    if isinstance(before, Unknown) and isinstance(after, Unknown):
        return (
            before.reason == after.reason
            and before.entity == after.entity
            and before.property_key == after.property_key
            and before.missing == after.missing
            and before.metadata == after.metadata
        )
    if isinstance(before, Conflict) and isinstance(after, Conflict):
        return (
            before.entity == after.entity
            and before.property_key == after.property_key
            and before.candidate_refs == after.candidate_refs
            and before.evidence_refs == after.evidence_refs
            and before.reason == after.reason
            and before.metadata == after.metadata
        )
    return False


def _provider_unavailable_diagnostics(snapshot: WorldStateSnapshot) -> tuple[Unknown, ...]:
    return tuple(
        sorted(
            (
                item
                for item in snapshot.unknowns
                if item.reason is UnknownReason.PROVIDER_UNAVAILABLE
            ),
            key=lambda item: item.unknown_id,
        )
    )


def _build_healthy_poll(
    previous: WorldStateSnapshot,
    observed: WorldStateSnapshot,
    delta: WorldStateDelta,
    status: ChangePollStatus,
    at: datetime,
) -> ProviderChangePoll:
    payload = {
        "status": status,
        "observed_at": at,
        "previous_snapshot_ref": previous.snapshot_id,
        "observed_snapshot_ref": observed.snapshot_id,
        "delta_ref": delta.delta_id,
        "diagnostic_refs": (),
        "contract_version": CHANGE_POLL_CONTRACT_VERSION,
    }
    return ProviderChangePoll(
        poll_id=semantic_id("change_poll", payload),
        status=status,
        observed_at=at,
        previous_snapshot_ref=previous.snapshot_id,
        observed_snapshot_ref=observed.snapshot_id,
        advanced=True,
        delta=delta,
    )


def _build_unavailable_poll(
    previous: WorldStateSnapshot,
    observed: WorldStateSnapshot,
    diagnostics: tuple[Unknown, ...],
    at: datetime,
) -> ProviderChangePoll:
    payload = {
        "status": ChangePollStatus.PROVIDER_UNAVAILABLE,
        "observed_at": at,
        "previous_snapshot_ref": previous.snapshot_id,
        "observed_snapshot_ref": observed.snapshot_id,
        "delta_ref": None,
        "diagnostic_refs": tuple(item.unknown_id for item in diagnostics),
        "contract_version": CHANGE_POLL_CONTRACT_VERSION,
    }
    return ProviderChangePoll(
        poll_id=semantic_id("change_poll", payload),
        status=ChangePollStatus.PROVIDER_UNAVAILABLE,
        observed_at=at,
        previous_snapshot_ref=previous.snapshot_id,
        observed_snapshot_ref=observed.snapshot_id,
        advanced=False,
        delta=None,
        diagnostics=diagnostics,
    )
