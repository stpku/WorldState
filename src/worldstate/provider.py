from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeAlias, runtime_checkable

from .models import (
    Conflict,
    EntityRef,
    Evidence,
    SpatialScope,
    StateQueryResult,
    StateTransition,
    TemporalScope,
    Unknown,
    WorldStateSnapshot,
)

EvidenceSet: TypeAlias = tuple[Evidence, ...]


@runtime_checkable
class WorldStateProvider(Protocol):
    """Mandatory synchronous semantic interoperability surface for WorldState."""

    def get_snapshot(
        self,
        scope: SpatialScope | None,
        at: datetime,
    ) -> WorldStateSnapshot: ...

    def query_state(
        self,
        entity: EntityRef,
        property_key: str,
        at: datetime,
    ) -> StateQueryResult: ...

    def query_relation(
        self,
        subject: EntityRef,
        relation_key: str,
        object: EntityRef,
        at: datetime,
    ) -> StateQueryResult: ...

    def get_evidence(self, state_ref: str) -> EvidenceSet: ...

    def get_unknowns(self, scope: SpatialScope | None) -> tuple[Unknown, ...]: ...

    def get_conflicts(self, scope: SpatialScope | None) -> tuple[Conflict, ...]: ...

    def get_history(
        self,
        entity: EntityRef,
        interval: TemporalScope,
    ) -> tuple[StateTransition, ...]: ...


class WorldStateChangeProvider(Protocol):
    """Optional future seam for change streams; not required for Core conformance."""

    def subscribe_changes(self, scope: SpatialScope | None) -> object: ...
