from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable

from .change import StateChangeRef, state_change_payload
from .ids import semantic_id


CAUSALITY_CONTRACT_VERSION = "0.1"
CAUSAL_OBSERVATION_CONTRACT_ID = "worldstate.causal-change-observation"
CAUSAL_RELATION_CONTRACT_ID = "worldstate.causal-relation"
CAUSAL_FRONTIER_CONTRACT_ID = "worldstate.causal-frontier"


class CausalRelationKind(str, Enum):
    SAME_CHANGE = "same_change"
    DUPLICATE_OBSERVATION = "duplicate_observation"
    SUPERSEDES = "supersedes"
    CAUSED_BY = "caused_by"
    DERIVED_FROM = "derived_from"
    CONCURRENT_WITH = "concurrent_with"
    CONFLICTS_WITH = "conflicts_with"
    INVALIDATES = "invalidates"
    RESOLVES = "resolves"
    PARTIALLY_RESOLVES = "partially_resolves"
    UNRELATED = "unrelated"


@dataclass(frozen=True, slots=True)
class CausalChangeObservation:
    """One observation of a WorldState-owned change at three explicit times."""

    observation_id: str
    change: StateChangeRef
    effective_at: datetime
    observed_at: datetime
    ingested_at: datetime
    evidence_refs: tuple[str, ...]
    contract_version: str = CAUSALITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("observation_id must be a non-empty string")
        for name, value in (
            ("effective_at", self.effective_at),
            ("observed_at", self.observed_at),
            ("ingested_at", self.ingested_at),
        ):
            _require_utc(value, name)
        if self.effective_at != self.change.occurred_at:
            raise ValueError("effective_at must equal the WorldState change occurred_at")
        if self.observed_at < self.effective_at:
            raise ValueError("observed_at must not precede effective_at")
        if self.ingested_at < self.observed_at:
            raise ValueError("ingested_at must not precede observed_at")
        if not self.evidence_refs:
            raise ValueError("causal observation requires evidence_refs")
        _require_unique_refs(self.evidence_refs, "evidence_refs")
        if self.contract_version != CAUSALITY_CONTRACT_VERSION:
            raise ValueError(
                f"contract_version must equal {CAUSALITY_CONTRACT_VERSION!r}"
            )


@dataclass(frozen=True, slots=True)
class CausalRelation:
    relation_id: str
    kind: CausalRelationKind
    subject_observation_ref: str
    object_observation_ref: str
    asserted_at: datetime
    evidence_refs: tuple[str, ...]
    contract_version: str = CAUSALITY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.relation_id.strip():
            raise ValueError("relation_id must be a non-empty string")
        if not self.subject_observation_ref.strip() or not self.object_observation_ref.strip():
            raise ValueError("causal relation observation refs must be non-empty")
        if self.subject_observation_ref == self.object_observation_ref:
            raise ValueError("causal relation cannot reference the same observation twice")
        _require_utc(self.asserted_at, "asserted_at")
        if not self.evidence_refs:
            raise ValueError("causal relation requires evidence_refs")
        _require_unique_refs(self.evidence_refs, "evidence_refs")
        if self.contract_version != CAUSALITY_CONTRACT_VERSION:
            raise ValueError(
                f"contract_version must equal {CAUSALITY_CONTRACT_VERSION!r}"
            )


@dataclass(frozen=True, slots=True)
class CausalFrontier:
    """Order-independent canonical change state for one explicit evidence set."""

    frontier_id: str
    as_of: datetime
    observation_refs: tuple[str, ...]
    active_observation_refs: tuple[str, ...]
    active_change_refs: tuple[str, ...]
    duplicate_observation_refs: tuple[str, ...]
    superseded_observation_refs: tuple[str, ...]
    resolved_observation_refs: tuple[str, ...]
    unresolved_observation_groups: tuple[tuple[str, ...], ...]
    relation_refs: tuple[str, ...]
    max_effective_at: datetime
    max_observed_at: datetime
    max_ingested_at: datetime
    contract_version: str = CAUSALITY_CONTRACT_VERSION


def make_causal_relation(
    kind: CausalRelationKind,
    subject_observation_ref: str,
    object_observation_ref: str,
    asserted_at: datetime,
    *,
    evidence_refs: tuple[str, ...],
) -> CausalRelation:
    payload = {
        "kind": kind,
        "subject_observation_ref": subject_observation_ref,
        "object_observation_ref": object_observation_ref,
        "asserted_at": asserted_at,
        "evidence_refs": evidence_refs,
        "contract_version": CAUSALITY_CONTRACT_VERSION,
    }
    return CausalRelation(
        relation_id=semantic_id("causal_relation", payload),
        kind=kind,
        subject_observation_ref=subject_observation_ref,
        object_observation_ref=object_observation_ref,
        asserted_at=asserted_at,
        evidence_refs=evidence_refs,
    )


def build_causal_frontier(
    observations: Iterable[CausalChangeObservation],
    relations: Iterable[CausalRelation],
    *,
    as_of: datetime,
) -> CausalFrontier:
    """Build a deterministic frontier without using arrival/input order as truth policy."""

    _require_utc(as_of, "as_of")
    observation_items = tuple(observations)
    relation_items = tuple(relations)
    if not observation_items:
        raise ValueError("causal frontier requires at least one observation")

    by_id = _unique_by_id(observation_items)
    relation_by_id = _unique_relations(relation_items)
    if any(item.ingested_at > as_of for item in observation_items):
        raise ValueError("causal observation cannot be ingested after frontier as_of")
    if any(item.asserted_at > as_of for item in relation_items):
        raise ValueError("causal relation cannot be asserted after frontier as_of")

    for relation in relation_items:
        subject = by_id.get(relation.subject_observation_ref)
        target = by_id.get(relation.object_observation_ref)
        if subject is None or target is None:
            raise ValueError("causal relation references an unknown observation")
        if relation.asserted_at < max(subject.ingested_at, target.ingested_at):
            raise ValueError("causal relation cannot predate participating observation ingestion")
        _validate_relation_semantics(relation, subject, target)

    _reject_directional_cycles(relation_items)

    duplicate_refs: set[str] = set()
    canonical_ref_by_ref: dict[str, str] = {}
    signature_groups: dict[tuple[object, ...], list[CausalChangeObservation]] = {}
    for observation in observation_items:
        signature_groups.setdefault(_semantic_signature(observation), []).append(observation)
    for group in signature_groups.values():
        canonical = min(group, key=lambda item: (item.observed_at, item.observation_id))
        canonical_ref_by_ref.update(
            {item.observation_id: canonical.observation_id for item in group}
        )
        duplicate_refs.update(item.observation_id for item in group if item != canonical)

    for relation in relation_items:
        if relation.kind in {
            CausalRelationKind.SAME_CHANGE,
            CausalRelationKind.DUPLICATE_OBSERVATION,
        }:
            duplicate_refs.add(relation.subject_observation_ref)
            canonical_ref_by_ref[relation.subject_observation_ref] = canonical_ref_by_ref.get(
                relation.object_observation_ref,
                relation.object_observation_ref,
            )

    superseded_refs: set[str] = set()
    resolved_refs: set[str] = set()
    for relation in relation_items:
        target_ref = canonical_ref_by_ref.get(
            relation.object_observation_ref,
            relation.object_observation_ref,
        )
        if relation.kind in {
            CausalRelationKind.SUPERSEDES,
            CausalRelationKind.INVALIDATES,
        }:
            superseded_refs.add(target_ref)
        elif relation.kind is CausalRelationKind.RESOLVES:
            resolved_refs.add(target_ref)

    active = tuple(
        sorted(
            (
                item
                for item in observation_items
                if item.observation_id not in duplicate_refs
                and item.observation_id not in superseded_refs
                and item.observation_id not in resolved_refs
            ),
            key=lambda item: (
                item.change.entity.entity_id,
                item.change.property_key,
                item.effective_at,
                item.observation_id,
            ),
        )
    )
    unresolved_groups: list[tuple[str, ...]] = []
    active_by_proposition: dict[tuple[str, str], list[CausalChangeObservation]] = {}
    for item in active:
        key = (item.change.entity.entity_id, item.change.property_key)
        active_by_proposition.setdefault(key, []).append(item)
    for group in active_by_proposition.values():
        if len(group) > 1:
            unresolved_groups.append(tuple(sorted(item.observation_id for item in group)))

    active_refs = tuple(item.observation_id for item in active)
    active_change_refs = tuple(item.change.change_id for item in active)
    observation_refs = tuple(sorted(by_id))
    relation_refs = tuple(sorted(relation_by_id))
    unresolved = tuple(sorted(unresolved_groups))
    identity = {
        "observation_refs": observation_refs,
        "active_observation_refs": active_refs,
        "active_change_refs": active_change_refs,
        "duplicate_observation_refs": tuple(sorted(duplicate_refs)),
        "superseded_observation_refs": tuple(sorted(superseded_refs)),
        "resolved_observation_refs": tuple(sorted(resolved_refs)),
        "unresolved_observation_groups": unresolved,
        "relation_refs": relation_refs,
        "contract_version": CAUSALITY_CONTRACT_VERSION,
    }
    return CausalFrontier(
        frontier_id=semantic_id("causal_frontier", identity),
        as_of=as_of,
        observation_refs=observation_refs,
        active_observation_refs=active_refs,
        active_change_refs=active_change_refs,
        duplicate_observation_refs=tuple(sorted(duplicate_refs)),
        superseded_observation_refs=tuple(sorted(superseded_refs)),
        resolved_observation_refs=tuple(sorted(resolved_refs)),
        unresolved_observation_groups=unresolved,
        relation_refs=relation_refs,
        max_effective_at=max(item.effective_at for item in observation_items),
        max_observed_at=max(item.observed_at for item in observation_items),
        max_ingested_at=max(item.ingested_at for item in observation_items),
    )


def causal_change_observation_payload(
    observation: CausalChangeObservation,
) -> dict[str, object]:
    return {
        "contract": CAUSAL_OBSERVATION_CONTRACT_ID,
        "contract_version": observation.contract_version,
        "observation_id": observation.observation_id,
        "effective_at": _time(observation.effective_at),
        "observed_at": _time(observation.observed_at),
        "ingested_at": _time(observation.ingested_at),
        "evidence_refs": list(observation.evidence_refs),
        "change": state_change_payload(observation.change),
    }


def causal_relation_payload(relation: CausalRelation) -> dict[str, object]:
    return {
        "contract": CAUSAL_RELATION_CONTRACT_ID,
        "contract_version": relation.contract_version,
        "relation_id": relation.relation_id,
        "kind": relation.kind.value,
        "subject_observation_ref": relation.subject_observation_ref,
        "object_observation_ref": relation.object_observation_ref,
        "asserted_at": _time(relation.asserted_at),
        "evidence_refs": list(relation.evidence_refs),
    }


def causal_frontier_payload(
    frontier: CausalFrontier,
    observations: Iterable[CausalChangeObservation],
    relations: Iterable[CausalRelation],
) -> dict[str, object]:
    observation_by_id = _unique_by_id(tuple(observations))
    relation_by_id = _unique_relations(tuple(relations))
    if set(observation_by_id) != set(frontier.observation_refs):
        raise ValueError("frontier payload observations do not match frontier identity")
    if set(relation_by_id) != set(frontier.relation_refs):
        raise ValueError("frontier payload relations do not match frontier identity")
    return {
        "contract": CAUSAL_FRONTIER_CONTRACT_ID,
        "contract_version": frontier.contract_version,
        "frontier_id": frontier.frontier_id,
        "as_of": _time(frontier.as_of),
        "max_effective_at": _time(frontier.max_effective_at),
        "max_observed_at": _time(frontier.max_observed_at),
        "max_ingested_at": _time(frontier.max_ingested_at),
        "active_observation_refs": list(frontier.active_observation_refs),
        "active_change_refs": list(frontier.active_change_refs),
        "duplicate_observation_refs": list(frontier.duplicate_observation_refs),
        "superseded_observation_refs": list(frontier.superseded_observation_refs),
        "resolved_observation_refs": list(frontier.resolved_observation_refs),
        "unresolved_observation_groups": [
            list(group) for group in frontier.unresolved_observation_groups
        ],
        "observations": [
            causal_change_observation_payload(observation_by_id[ref])
            for ref in frontier.observation_refs
        ],
        "relations": [causal_relation_payload(relation_by_id[ref]) for ref in frontier.relation_refs],
    }


def _semantic_signature(observation: CausalChangeObservation) -> tuple[object, ...]:
    change = observation.change
    return (
        change.entity.entity_id,
        change.entity.entity_type,
        change.entity.namespace,
        change.property_key,
        change.kind,
        observation.effective_at,
        change.from_state_ref,
        change.to_state_ref,
        change.affected_state_refs,
        change.source_refs,
        observation.evidence_refs,
    )


def _validate_relation_semantics(
    relation: CausalRelation,
    subject: CausalChangeObservation,
    target: CausalChangeObservation,
) -> None:
    same_proposition = (
        subject.change.entity.entity_id == target.change.entity.entity_id
        and subject.change.property_key == target.change.property_key
    )
    if relation.kind in {
        CausalRelationKind.SAME_CHANGE,
        CausalRelationKind.DUPLICATE_OBSERVATION,
    } and _semantic_signature(subject) != _semantic_signature(target):
        raise ValueError("same/duplicate relation requires identical change semantics")
    if relation.kind in {
        CausalRelationKind.SUPERSEDES,
        CausalRelationKind.INVALIDATES,
        CausalRelationKind.RESOLVES,
        CausalRelationKind.PARTIALLY_RESOLVES,
        CausalRelationKind.CONFLICTS_WITH,
    } and not same_proposition:
        raise ValueError(f"{relation.kind.value} relation requires the same proposition")
    if relation.kind in {
        CausalRelationKind.SUPERSEDES,
        CausalRelationKind.INVALIDATES,
        CausalRelationKind.RESOLVES,
        CausalRelationKind.CAUSED_BY,
        CausalRelationKind.DERIVED_FROM,
    } and subject.effective_at < target.effective_at:
        raise ValueError("causal successor cannot be effective before its target/cause")


def _reject_directional_cycles(relations: tuple[CausalRelation, ...]) -> None:
    directional = {
        CausalRelationKind.SUPERSEDES,
        CausalRelationKind.INVALIDATES,
        CausalRelationKind.RESOLVES,
        CausalRelationKind.CAUSED_BY,
        CausalRelationKind.DERIVED_FROM,
    }
    edges: dict[str, set[str]] = {}
    for relation in relations:
        if relation.kind in directional:
            edges.setdefault(relation.subject_observation_ref, set()).add(
                relation.object_observation_ref
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(ref: str) -> None:
        if ref in visiting:
            raise ValueError("causal relation graph contains a directional cycle")
        if ref in visited:
            return
        visiting.add(ref)
        for target in edges.get(ref, ()):
            visit(target)
        visiting.remove(ref)
        visited.add(ref)

    for ref in tuple(edges):
        visit(ref)


def _unique_by_id(
    observations: tuple[CausalChangeObservation, ...],
) -> dict[str, CausalChangeObservation]:
    result: dict[str, CausalChangeObservation] = {}
    for observation in observations:
        if observation.observation_id in result:
            raise ValueError(f"duplicate causal observation ID: {observation.observation_id}")
        result[observation.observation_id] = observation
    return result


def _unique_relations(relations: tuple[CausalRelation, ...]) -> dict[str, CausalRelation]:
    result: dict[str, CausalRelation] = {}
    for relation in relations:
        if relation.relation_id in result:
            raise ValueError(f"duplicate causal relation ID: {relation.relation_id}")
        result[relation.relation_id] = relation
    return result


def _require_unique_refs(refs: tuple[str, ...], name: str) -> None:
    if any(not ref.strip() for ref in refs):
        raise ValueError(f"{name} must not contain empty refs")
    if len(refs) != len(set(refs)):
        raise ValueError(f"{name} must not contain duplicate refs")


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC")


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
