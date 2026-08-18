from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from worldstate import (
    Claim,
    Conflict,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    JSONValue,
    Provenance,
    Source,
    SpatialScope,
    StateAssertion,
    StateQueryResult,
    StateTransition,
    TemporalScope,
    Unknown,
    UnknownReason,
    WorldStateSnapshot,
    semantic_id,
)


@dataclass(frozen=True, slots=True)
class SoRRecord:
    """Minimal record owned by an external System of Record."""

    record_id: str
    entity: EntityRef
    property_key: str
    value: JSONValue
    updated_at: datetime
    version: str
    temporal_scope: TemporalScope | None = None
    spatial_scope: SpatialScope | None = None


class ExternalRecordStore:
    """Authoritative mutable store used only to prove projection semantics.

    WorldState never receives ownership of this store. Updating a record here is
    enough for a later projection query to observe the new state.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[EntityRef, str], SoRRecord] = {}

    def put(self, record: SoRRecord) -> None:
        self._records[(record.entity, record.property_key)] = record

    def records(self) -> tuple[SoRRecord, ...]:
        return tuple(
            sorted(
                self._records.values(),
                key=lambda item: (item.entity.entity_id, item.property_key, item.record_id),
            )
        )


class ProjectionWorldStateProvider:
    """Read-only WorldState projection over an authoritative external store."""

    def __init__(self, store: ExternalRecordStore) -> None:
        self._store = store
        self._evidence_cache: dict[str, Evidence] = {}
        self._unknown_cache: dict[str, Unknown] = {}
        self._conflict_cache: dict[str, Conflict] = {}
        self._scope_refs: dict[str, set[str]] = {}

    def get_snapshot(
        self,
        scope: SpatialScope | None,
        at: datetime,
    ) -> WorldStateSnapshot:
        engine = self._project()
        snapshot = engine.get_snapshot(scope, at)
        for assertion in snapshot.assertions:
            self._remember_evidence(engine, assertion.assertion_id)
        for conflict in snapshot.conflicts:
            self._remember_evidence(engine, conflict.conflict_id)
            self._remember_outcome(conflict, scope)
        for unknown in snapshot.unknowns:
            self._remember_outcome(unknown, scope)
        return snapshot

    def query_state(
        self,
        entity: EntityRef,
        property_key: str,
        at: datetime,
    ) -> StateQueryResult:
        engine = self._project()
        result = engine.query_state(entity, property_key, at)
        if isinstance(result, StateAssertion):
            self._remember_evidence(engine, result.assertion_id)
        elif isinstance(result, Conflict):
            self._remember_evidence(engine, result.conflict_id)
            self._remember_outcome(result, None)
        else:
            self._remember_outcome(result, None)
        return result

    def query_relation(
        self,
        subject: EntityRef,
        relation_key: str,
        object: EntityRef,
        at: datetime,
    ) -> StateQueryResult:
        payload = {
            "subject": subject,
            "relation_key": relation_key,
            "object": object,
            "as_of": at,
            "reason": UnknownReason.UNSUPPORTED_QUERY,
            "provider": "worldstate.projection-example",
        }
        result = Unknown(
            unknown_id=semantic_id("unknown", payload),
            reason=UnknownReason.UNSUPPORTED_QUERY,
            as_of=at,
            entity=subject,
            property_key=relation_key,
            metadata={"provider": "worldstate.projection-example"},
        )
        self._remember_outcome(result, None)
        return result

    def get_evidence(self, state_ref: str) -> tuple[Evidence, ...]:
        refs = self._scope_refs.get(f"evidence:{state_ref}", set())
        return tuple(
            self._evidence_cache[ref]
            for ref in sorted(refs)
            if ref in self._evidence_cache
        )

    def get_unknowns(self, scope: SpatialScope | None) -> tuple[Unknown, ...]:
        scope_key = _scope_key(scope)
        return tuple(
            sorted(
                (
                    item
                    for item in self._unknown_cache.values()
                    if item.unknown_id in self._scope_refs.get(scope_key, set())
                ),
                key=lambda item: item.unknown_id,
            )
        )

    def get_conflicts(self, scope: SpatialScope | None) -> tuple[Conflict, ...]:
        scope_key = _scope_key(scope)
        return tuple(
            sorted(
                (
                    item
                    for item in self._conflict_cache.values()
                    if item.conflict_id in self._scope_refs.get(scope_key, set())
                ),
                key=lambda item: item.conflict_id,
            )
        )

    def get_history(
        self,
        entity: EntityRef,
        interval: TemporalScope,
    ) -> tuple[StateTransition, ...]:
        return ()

    def _project(self) -> InMemoryWorldState:
        engine = InMemoryWorldState()
        for record in self._store.records():
            source = Source(
                source_id="external-sor",
                source_type="system-of-record",
                version=record.version,
                metadata={"record_id": record.record_id},
            )
            evidence_id = semantic_id(
                "ev",
                {
                    "provider": "projection-example",
                    "record_id": record.record_id,
                    "version": record.version,
                    "updated_at": record.updated_at,
                },
            )
            evidence = Evidence(
                evidence_id=evidence_id,
                source=source,
                recorded_at=record.updated_at,
                content_ref=f"sor-record:{record.record_id}",
                metadata={"projected": True},
            )
            claim_id = semantic_id(
                "claim",
                {
                    "provider": "projection-example",
                    "record_id": record.record_id,
                    "version": record.version,
                    "entity": record.entity,
                    "property_key": record.property_key,
                    "value": record.value,
                    "temporal_scope": record.temporal_scope,
                    "spatial_scope": record.spatial_scope,
                },
            )
            claim = Claim(
                claim_id=claim_id,
                entity=record.entity,
                property_key=record.property_key,
                value=record.value,
                epistemic_mode=EpistemicMode.OBSERVED,
                provenance=Provenance(
                    evidence_refs=(evidence_id,),
                    source_refs=(source.source_id,),
                    method="projection",
                ),
                created_at=record.updated_at,
                temporal_scope=record.temporal_scope,
                spatial_scope=record.spatial_scope,
            )
            engine.add_evidence(evidence)
            engine.add_claim(claim)
        return engine

    def _remember_evidence(self, engine: InMemoryWorldState, state_ref: str) -> None:
        evidence = engine.get_evidence(state_ref)
        refs = self._scope_refs.setdefault(f"evidence:{state_ref}", set())
        for item in evidence:
            self._evidence_cache[item.evidence_id] = item
            refs.add(item.evidence_id)

    def _remember_outcome(
        self,
        result: Unknown | Conflict,
        scope: SpatialScope | None,
    ) -> None:
        scope_key = _scope_key(scope)
        if isinstance(result, Unknown):
            self._unknown_cache[result.unknown_id] = result
            result_id = result.unknown_id
        else:
            self._conflict_cache[result.conflict_id] = result
            result_id = result.conflict_id
        self._scope_refs.setdefault(scope_key, set()).add(result_id)


def _scope_key(scope: SpatialScope | None) -> str:
    return semantic_id("scope", {"scope": scope})
