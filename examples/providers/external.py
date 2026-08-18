from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from worldstate import (
    Conflict,
    EntityRef,
    EpistemicMode,
    Evidence,
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
    Validity,
    WorldStateSnapshot,
    semantic_id,
)


class ExternalSourceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalStateRecord:
    record_id: str
    entity: EntityRef
    property_key: str
    value: JSONValue
    updated_at: datetime
    record_version: str
    temporal_scope: TemporalScope | None = None
    spatial_scope: SpatialScope | None = None


class DirectExternalSource:
    """Independent authoritative source with no WorldState reference-engine state."""

    def __init__(self, *, source_version: str = "v1") -> None:
        self.source_version = source_version
        self.available = True
        self._records: dict[tuple[EntityRef, str], ExternalStateRecord] = {}

    def put(self, record: ExternalStateRecord) -> None:
        self._records[(record.entity, record.property_key)] = record

    def get(self, entity: EntityRef, property_key: str) -> ExternalStateRecord | None:
        self._require_available()
        return self._records.get((entity, property_key))

    def records(self) -> tuple[ExternalStateRecord, ...]:
        self._require_available()
        return tuple(
            sorted(
                self._records.values(),
                key=lambda item: (item.entity.entity_id, item.property_key, item.record_id),
            )
        )

    def _require_available(self) -> None:
        if not self.available:
            raise ExternalSourceUnavailable("external source is unavailable")


class DirectExternalWorldStateProvider:
    """WorldStateProvider implemented without the M1 reference resolver/engine."""

    def __init__(self, source: DirectExternalSource) -> None:
        self._source = source
        self._evidence_cache: dict[str, Evidence] = {}
        self._unknown_cache: dict[str, Unknown] = {}

    def get_snapshot(
        self,
        scope: SpatialScope | None,
        at: datetime,
    ) -> WorldStateSnapshot:
        try:
            records = tuple(
                record
                for record in self._source.records()
                if _scope_matches(record.spatial_scope, scope)
            )
        except ExternalSourceUnavailable:
            unknown = self._provider_unavailable(None, None, at)
            return _snapshot(
                (),
                (unknown,),
                (),
                scope=scope,
                at=at,
                source_version=self._source.source_version,
            )

        assertions: list[StateAssertion] = []
        unknowns: list[Unknown] = []
        for record in records:
            result = self._result_from_record(record, at)
            if isinstance(result, StateAssertion):
                assertions.append(result)
            else:
                unknowns.append(result)
        return _snapshot(
            tuple(assertions),
            tuple(unknowns),
            (),
            scope=scope,
            at=at,
            source_version=self._source.source_version,
        )

    def query_state(
        self,
        entity: EntityRef,
        property_key: str,
        at: datetime,
    ) -> StateQueryResult:
        try:
            record = self._source.get(entity, property_key)
        except ExternalSourceUnavailable:
            return self._provider_unavailable(entity, property_key, at)

        if record is None:
            return self._unknown(
                entity,
                property_key,
                at,
                UnknownReason.NO_EVIDENCE,
            )
        return self._result_from_record(record, at)

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
            "provider": "worldstate.direct-external-example",
        }
        result = Unknown(
            unknown_id=semantic_id("unknown", payload),
            reason=UnknownReason.UNSUPPORTED_QUERY,
            as_of=at,
            entity=subject,
            property_key=relation_key,
            metadata={"provider": "worldstate.direct-external-example"},
        )
        self._unknown_cache[result.unknown_id] = result
        return result

    def get_evidence(self, state_ref: str) -> tuple[Evidence, ...]:
        return tuple(
            sorted(
                (
                    evidence
                    for evidence in self._evidence_cache.values()
                    if evidence.metadata.get("state_ref") == state_ref
                ),
                key=lambda item: item.evidence_id,
            )
        )

    def get_unknowns(self, scope: SpatialScope | None) -> tuple[Unknown, ...]:
        return tuple(sorted(self._unknown_cache.values(), key=lambda item: item.unknown_id))

    def get_conflicts(self, scope: SpatialScope | None) -> tuple[Conflict, ...]:
        return ()

    def get_history(
        self,
        entity: EntityRef,
        interval: TemporalScope,
    ) -> tuple[StateTransition, ...]:
        return ()

    def _result_from_record(
        self,
        record: ExternalStateRecord,
        at: datetime,
    ) -> StateAssertion | Unknown:
        if record.updated_at > at:
            return self._unknown(
                record.entity,
                record.property_key,
                at,
                UnknownReason.NO_EVIDENCE,
            )
        if not _time_in_scope(at, record.temporal_scope):
            return self._unknown(
                record.entity,
                record.property_key,
                at,
                UnknownReason.OUTSIDE_VALIDITY,
            )

        source = Source(
            source_id="direct-external-source",
            source_type="external-provider",
            version=self._source.source_version,
            metadata={"record_version": record.record_version},
        )
        evidence_id = semantic_id(
            "ev",
            {
                "provider": "direct-external-example",
                "record_id": record.record_id,
                "record_version": record.record_version,
                "updated_at": record.updated_at,
            },
        )
        provenance = Provenance(
            evidence_refs=(evidence_id,),
            source_refs=(source.source_id,),
            method="external-provider",
        )
        validity = Validity(
            valid_from=(
                None if record.temporal_scope is None else record.temporal_scope.start
            ),
            valid_until=(
                None if record.temporal_scope is None else record.temporal_scope.end
            ),
            resolved_at=at,
        )
        assertion_payload = {
            "entity": record.entity,
            "property_key": record.property_key,
            "value": record.value,
            "epistemic_mode": EpistemicMode.OBSERVED,
            "validity": validity,
            "provenance": provenance,
            "spatial_scope": record.spatial_scope,
            "provider": "direct-external-example",
            "version": self._source.source_version,
        }
        assertion_id = semantic_id("state", assertion_payload)
        assertion = StateAssertion(
            assertion_id=assertion_id,
            entity=record.entity,
            property_key=record.property_key,
            value=record.value,
            epistemic_mode=EpistemicMode.OBSERVED,
            validity=validity,
            provenance=provenance,
            version=self._source.source_version,
            spatial_scope=record.spatial_scope,
        )
        evidence = Evidence(
            evidence_id=evidence_id,
            source=source,
            recorded_at=record.updated_at,
            content_ref=f"external-record:{record.record_id}",
            metadata={
                "record_version": record.record_version,
                "state_ref": assertion_id,
            },
        )
        self._evidence_cache[evidence.evidence_id] = evidence
        return assertion

    def _provider_unavailable(
        self,
        entity: EntityRef | None,
        property_key: str | None,
        at: datetime,
    ) -> Unknown:
        return self._unknown(
            entity,
            property_key,
            at,
            UnknownReason.PROVIDER_UNAVAILABLE,
        )

    def _unknown(
        self,
        entity: EntityRef | None,
        property_key: str | None,
        at: datetime,
        reason: UnknownReason,
    ) -> Unknown:
        payload = {
            "entity": entity,
            "property_key": property_key,
            "as_of": at,
            "reason": reason,
            "provider": "worldstate.direct-external-example",
            "source_version": self._source.source_version,
        }
        result = Unknown(
            unknown_id=semantic_id("unknown", payload),
            reason=reason,
            as_of=at,
            entity=entity,
            property_key=property_key,
            metadata={
                "provider": "worldstate.direct-external-example",
                "source_version": self._source.source_version,
            },
        )
        self._unknown_cache[result.unknown_id] = result
        return result


def _snapshot(
    assertions: tuple[StateAssertion, ...],
    unknowns: tuple[Unknown, ...],
    conflicts: tuple[Conflict, ...],
    *,
    scope: SpatialScope | None,
    at: datetime,
    source_version: str,
) -> WorldStateSnapshot:
    canonical_assertions = tuple(sorted(assertions, key=lambda item: item.assertion_id))
    canonical_unknowns = tuple(sorted(unknowns, key=lambda item: item.unknown_id))
    canonical_conflicts = tuple(sorted(conflicts, key=lambda item: item.conflict_id))
    payload = {
        "as_of": at,
        "scope": scope,
        "assertion_refs": tuple(item.assertion_id for item in canonical_assertions),
        "unknown_refs": tuple(item.unknown_id for item in canonical_unknowns),
        "conflict_refs": tuple(item.conflict_id for item in canonical_conflicts),
        "source_version": source_version,
        "provider": "direct-external-example",
    }
    return WorldStateSnapshot(
        snapshot_id=semantic_id("snap", payload),
        as_of=at,
        created_at=at,
        version=source_version,
        scope=scope,
        assertions=canonical_assertions,
        unknowns=canonical_unknowns,
        conflicts=canonical_conflicts,
        source_versions={"direct-external-source": source_version},
    )


def _time_in_scope(at: datetime, scope: TemporalScope | None) -> bool:
    if scope is None:
        return True
    if scope.start is not None and at < scope.start:
        return False
    if scope.end is not None and at > scope.end:
        return False
    return True


def _scope_matches(
    record_scope: SpatialScope | None,
    requested_scope: SpatialScope | None,
) -> bool:
    if requested_scope is None:
        return True
    if record_scope is None:
        return False
    return record_scope == requested_scope
