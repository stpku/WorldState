from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from worldstate import (
    Conflict,
    EntityRef,
    ProviderChangeCursor,
    ProviderChangePoll,
    StateAssertion,
    Unknown,
    WorldStateProvider,
    open_change_cursor,
)

from .providers import SHIPMENT, SHIPMENT_STATUS, TEMPERATURE_C

FactKind = Literal["assertion", "unknown", "conflict"]


@dataclass(frozen=True, slots=True)
class FactView:
    property_key: str
    kind: FactKind
    state_ref: str
    value: object | None
    evidence_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ColdChainWorldView:
    entity: EntityRef
    observed_at: datetime
    shipment_status: FactView
    temperature_c: FactView


@dataclass(frozen=True, slots=True)
class ColdChainChangeView:
    observed_at: datetime
    registry_poll: ProviderChangePoll
    temperature_poll: ProviderChangePoll
    changed_properties: tuple[str, ...]
    provider_unavailable_properties: tuple[str, ...]


class ColdChainMonitor:
    """Independent consumer of WorldState truth/change semantics.

    The monitor presents shipment-registry and temperature facts. It deliberately
    does not encode release, discard, alarm, compliance, or routing decisions.
    Those decisions belong to downstream cold-chain policy systems.
    """

    def __init__(
        self,
        registry_provider: WorldStateProvider,
        temperature_provider: WorldStateProvider,
        *,
        shipment: EntityRef = SHIPMENT,
    ) -> None:
        self._registry_provider = registry_provider
        self._temperature_provider = temperature_provider
        self._shipment = shipment

    def read(self, at: datetime) -> ColdChainWorldView:
        registry_result = self._registry_provider.query_state(
            self._shipment,
            SHIPMENT_STATUS,
            at,
        )
        temperature_result = self._temperature_provider.query_state(
            self._shipment,
            TEMPERATURE_C,
            at,
        )
        return ColdChainWorldView(
            entity=self._shipment,
            observed_at=at,
            shipment_status=_fact_view(SHIPMENT_STATUS, registry_result),
            temperature_c=_fact_view(TEMPERATURE_C, temperature_result),
        )

    def open_watch(self, at: datetime) -> "ColdChainWatch":
        return ColdChainWatch(
            registry_cursor=open_change_cursor(self._registry_provider, None, at),
            temperature_cursor=open_change_cursor(self._temperature_provider, None, at),
        )


@dataclass(slots=True)
class ColdChainWatch:
    registry_cursor: ProviderChangeCursor
    temperature_cursor: ProviderChangeCursor

    def poll(self, at: datetime) -> ColdChainChangeView:
        registry_poll = self.registry_cursor.poll(at)
        temperature_poll = self.temperature_cursor.poll(at)

        changed: list[str] = []
        unavailable: list[str] = []
        _collect_poll_property(
            registry_poll,
            SHIPMENT_STATUS,
            changed=changed,
            unavailable=unavailable,
        )
        _collect_poll_property(
            temperature_poll,
            TEMPERATURE_C,
            changed=changed,
            unavailable=unavailable,
        )
        return ColdChainChangeView(
            observed_at=at,
            registry_poll=registry_poll,
            temperature_poll=temperature_poll,
            changed_properties=tuple(sorted(changed)),
            provider_unavailable_properties=tuple(sorted(unavailable)),
        )


def _fact_view(property_key: str, result: object) -> FactView:
    if isinstance(result, StateAssertion):
        return FactView(
            property_key=property_key,
            kind="assertion",
            state_ref=result.assertion_id,
            value=result.value,
            evidence_refs=result.provenance.evidence_refs,
            source_refs=result.provenance.source_refs,
        )
    if isinstance(result, Unknown):
        return FactView(
            property_key=property_key,
            kind="unknown",
            state_ref=result.unknown_id,
            value=None,
            evidence_refs=(),
            source_refs=(),
            reason=result.reason.value,
        )
    if isinstance(result, Conflict):
        return FactView(
            property_key=property_key,
            kind="conflict",
            state_ref=result.conflict_id,
            value=None,
            evidence_refs=result.evidence_refs,
            source_refs=(),
            reason=result.reason,
        )
    raise TypeError(f"unsupported state result: {type(result).__name__}")


def _collect_poll_property(
    poll: ProviderChangePoll,
    property_key: str,
    *,
    changed: list[str],
    unavailable: list[str],
) -> None:
    if poll.status.value == "provider_unavailable":
        unavailable.append(property_key)
        return
    if poll.delta is None:
        return
    if any(change.property_key == property_key for change in poll.delta.changes):
        changed.append(property_key)
