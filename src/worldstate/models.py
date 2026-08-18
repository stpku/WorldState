from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TypeAlias

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | tuple["JSONValue", ...] | Mapping[str, "JSONValue"]


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_utc(value: datetime | None, name: str) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")


def freeze_json(value: object) -> JSONValue:
    """Recursively freeze a JSON-compatible value into immutable containers."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON-compatible floats must be finite")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON-compatible mappings require string keys")
        frozen = {key: freeze_json(item) for key, item in value.items()}
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def freeze_metadata(value: Mapping[str, object] | None) -> Mapping[str, JSONValue]:
    raw = {} if value is None else value
    frozen = freeze_json(raw)
    assert isinstance(frozen, Mapping)
    return frozen


class EpistemicMode(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    PREDICTED = "predicted"
    SIMULATED = "simulated"


class UnknownReason(str, Enum):
    NO_EVIDENCE = "no_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OUTSIDE_VALIDITY = "outside_validity"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNRESOLVED_IDENTITY = "unresolved_identity"
    UNSUPPORTED_QUERY = "unsupported_query"


@dataclass(frozen=True, slots=True)
class EntityRef:
    entity_id: str
    entity_type: str | None = None
    namespace: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.entity_id, "entity_id")
        if self.entity_type is not None:
            _require_text(self.entity_type, "entity_type")
        if self.namespace is not None:
            _require_text(self.namespace, "namespace")


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    source_type: str
    uri: str | None = None
    version: str | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        _require_text(self.source_type, "source_type")
        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class TemporalScope:
    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        _require_utc(self.start, "start")
        _require_utc(self.end, "end")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end must not be earlier than start")


@dataclass(frozen=True, slots=True)
class SpatialScope:
    kind: str
    reference: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        if self.bbox is not None:
            if len(self.bbox) != 4:
                raise ValueError("bbox must contain four coordinates")
            min_x, min_y, max_x, max_y = self.bbox
            if max_x < min_x or max_y < min_y:
                raise ValueError("bbox maximums must not be lower than minimums")
        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    entity: EntityRef
    property_key: str
    value: JSONValue
    source: Source
    recorded_at: datetime
    observed_at: datetime | None = None
    spatial_scope: SpatialScope | None = None
    temporal_scope: TemporalScope | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.observation_id, "observation_id")
        _require_text(self.property_key, "property_key")
        _require_utc(self.recorded_at, "recorded_at")
        _require_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "value", freeze_json(self.value))
        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    source: Source
    recorded_at: datetime
    observation_refs: tuple[str, ...] = ()
    content_ref: str | None = None
    content_hash: str | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.evidence_id, "evidence_id")
        _require_utc(self.recorded_at, "recorded_at")
        if any(not ref.strip() for ref in self.observation_refs):
            raise ValueError("observation_refs must not contain empty references")
        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class Provenance:
    evidence_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    method: str
    parent_assertion_refs: tuple[str, ...] = ()
    resolver: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.method, "method")
        if not self.evidence_refs and not self.parent_assertion_refs:
            raise ValueError("provenance requires evidence_refs or parent_assertion_refs")
        for name, refs in (
            ("evidence_refs", self.evidence_refs),
            ("source_refs", self.source_refs),
            ("parent_assertion_refs", self.parent_assertion_refs),
        ):
            if any(not ref.strip() for ref in refs):
                raise ValueError(f"{name} must not contain empty references")


@dataclass(frozen=True, slots=True)
class Uncertainty:
    confidence: float | None = None
    method: str | None = None
    reason: str | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    entity: EntityRef
    property_key: str
    value: JSONValue
    epistemic_mode: EpistemicMode
    provenance: Provenance
    created_at: datetime
    temporal_scope: TemporalScope | None = None
    spatial_scope: SpatialScope | None = None
    uncertainty: Uncertainty | None = None

    def __post_init__(self) -> None:
        _require_text(self.claim_id, "claim_id")
        _require_text(self.property_key, "property_key")
        _require_utc(self.created_at, "created_at")
        object.__setattr__(self, "value", freeze_json(self.value))


@dataclass(frozen=True, slots=True)
class Validity:
    resolved_at: datetime
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        _require_utc(self.resolved_at, "resolved_at")
        _require_utc(self.valid_from, "valid_from")
        _require_utc(self.valid_until, "valid_until")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must not be earlier than valid_from")


@dataclass(frozen=True, slots=True)
class StateAssertion:
    assertion_id: str
    entity: EntityRef
    property_key: str
    value: JSONValue
    epistemic_mode: EpistemicMode
    validity: Validity
    provenance: Provenance
    version: str
    uncertainty: Uncertainty | None = None
    spatial_scope: SpatialScope | None = None

    def __post_init__(self) -> None:
        _require_text(self.assertion_id, "assertion_id")
        _require_text(self.property_key, "property_key")
        _require_text(self.version, "version")
        object.__setattr__(self, "value", freeze_json(self.value))


@dataclass(frozen=True, slots=True)
class RelationAssertion:
    assertion_id: str
    subject: EntityRef
    relation_key: str
    object: EntityRef
    epistemic_mode: EpistemicMode
    validity: Validity
    provenance: Provenance
    version: str
    uncertainty: Uncertainty | None = None
    spatial_scope: SpatialScope | None = None

    def __post_init__(self) -> None:
        _require_text(self.assertion_id, "assertion_id")
        _require_text(self.relation_key, "relation_key")
        _require_text(self.version, "version")


@dataclass(frozen=True, slots=True)
class Unknown:
    unknown_id: str
    reason: UnknownReason
    as_of: datetime
    entity: EntityRef | None = None
    property_key: str | None = None
    missing: tuple[str, ...] = ()
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.unknown_id, "unknown_id")
        _require_utc(self.as_of, "as_of")
        if self.property_key is not None:
            _require_text(self.property_key, "property_key")
        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class Conflict:
    conflict_id: str
    entity: EntityRef
    property_key: str
    candidate_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str
    as_of: datetime
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.conflict_id, "conflict_id")
        _require_text(self.property_key, "property_key")
        _require_text(self.reason, "reason")
        _require_utc(self.as_of, "as_of")
        if len(self.candidate_refs) < 2:
            raise ValueError("conflict requires at least two candidate_refs")
        object.__setattr__(self, "metadata", freeze_metadata(self.metadata))


StateQueryResult: TypeAlias = StateAssertion | Unknown | Conflict


@dataclass(frozen=True, slots=True)
class WorldStateSnapshot:
    snapshot_id: str
    as_of: datetime
    created_at: datetime
    version: str
    scope: SpatialScope | None = None
    assertions: tuple[StateAssertion, ...] = ()
    unknowns: tuple[Unknown, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    source_versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.snapshot_id, "snapshot_id")
        _require_text(self.version, "version")
        _require_utc(self.as_of, "as_of")
        _require_utc(self.created_at, "created_at")
        object.__setattr__(
            self,
            "assertions",
            tuple(sorted(self.assertions, key=lambda item: item.assertion_id)),
        )
        object.__setattr__(
            self,
            "unknowns",
            tuple(sorted(self.unknowns, key=lambda item: item.unknown_id)),
        )
        object.__setattr__(
            self,
            "conflicts",
            tuple(sorted(self.conflicts, key=lambda item: item.conflict_id)),
        )
        object.__setattr__(
            self,
            "source_versions",
            MappingProxyType(dict(sorted(self.source_versions.items()))),
        )


@dataclass(frozen=True, slots=True)
class StateTransition:
    transition_id: str
    entity: EntityRef
    property_key: str
    transition_time: datetime
    provenance: Provenance
    from_assertion_ref: str | None = None
    to_assertion_ref: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.transition_id, "transition_id")
        _require_text(self.property_key, "property_key")
        _require_utc(self.transition_time, "transition_time")
        if self.from_assertion_ref is None and self.to_assertion_ref is None:
            raise ValueError("transition requires a from or to assertion reference")
