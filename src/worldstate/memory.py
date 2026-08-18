from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from .ids import canonical_json, semantic_id
from .models import (
    Claim,
    Conflict,
    EntityRef,
    Evidence,
    Observation,
    SpatialScope,
    StateAssertion,
    StateQueryResult,
    StateTransition,
    TemporalScope,
    Unknown,
    UnknownReason,
    WorldStateSnapshot,
)
from .provider import EvidenceSet
from .resolution import ReferenceResolver, ResolutionInputs
from .snapshot import build_snapshot

T = TypeVar("T")


class InMemoryWorldState:
    """Dependency-free M1 reference provider backed only by immutable values."""

    def __init__(self, resolver: ReferenceResolver | None = None) -> None:
        self._resolver = resolver or ReferenceResolver()
        self._observations: dict[str, Observation] = {}
        self._evidence: dict[str, Evidence] = {}
        self._claims: dict[str, Claim] = {}
        self._assertions: dict[str, StateAssertion] = {}
        self._unknowns: dict[str, Unknown] = {}
        self._conflicts: dict[str, Conflict] = {}
        self._transitions: dict[str, StateTransition] = {}
        self._outcome_scopes: dict[str, set[str]] = {}

    def add_observation(self, observation: Observation) -> None:
        """Register an immutable observation, rejecting semantic ID collisions."""
        _put_unique(self._observations, observation.observation_id, observation)

    def add_evidence(self, evidence: Evidence) -> None:
        """Register immutable evidence, rejecting semantic ID collisions."""
        _put_unique(self._evidence, evidence.evidence_id, evidence)

    def add_claim(self, claim: Claim) -> None:
        """Register a claim without treating claim existence as resolved truth."""
        _put_unique(self._claims, claim.claim_id, claim)

    def add_transition(self, transition: StateTransition) -> None:
        """Register an immutable transition for deterministic history queries."""
        _put_unique(self._transitions, transition.transition_id, transition)

    def query_state(
        self,
        entity: EntityRef,
        property_key: str,
        at: datetime,
    ) -> StateQueryResult:
        """Resolve one state proposition using the conservative reference policy."""
        result = self._resolver.resolve_state(
            self._claims.values(),
            entity,
            property_key,
            at,
            available=self._availability(at),
        )
        self._register_outcome(result, None)
        return result

    def query_relation(
        self,
        subject: EntityRef,
        relation_key: str,
        object: EntityRef,
        at: datetime,
    ) -> StateQueryResult:
        """Fail closed until M1 has a normative relation-claim representation."""
        if not relation_key.strip():
            raise ValueError("relation_key must be a non-empty string")
        payload = {
            "subject": subject,
            "relation_key": relation_key,
            "object": object,
            "as_of": at,
            "reason": UnknownReason.UNSUPPORTED_QUERY,
            "provider": "worldstate.in-memory-reference",
        }
        result = Unknown(
            unknown_id=semantic_id("unknown", payload),
            reason=UnknownReason.UNSUPPORTED_QUERY,
            as_of=at,
            entity=subject,
            property_key=relation_key,
            metadata={
                "provider": "worldstate.in-memory-reference",
                "requested_object": {
                    "entity_id": object.entity_id,
                    "entity_type": object.entity_type,
                    "namespace": object.namespace,
                },
            },
        )
        self._register_outcome(result, None)
        return result

    def get_snapshot(
        self,
        scope: SpatialScope | None,
        at: datetime,
    ) -> WorldStateSnapshot:
        """Resolve every known proposition in an exact M1 spatial scope."""
        selected = tuple(
            claim
            for claim in self._claims.values()
            if _scope_matches(claim.spatial_scope, scope)
        )
        keys = tuple(
            sorted(
                {(claim.entity, claim.property_key) for claim in selected},
                key=lambda item: canonical_json(item),
            )
        )
        availability = self._availability(at)
        results = tuple(
            self._resolver.resolve_state(
                selected,
                entity,
                property_key,
                at,
                available=availability,
            )
            for entity, property_key in keys
        )
        for result in results:
            self._register_outcome(result, scope)

        return build_snapshot(
            results,
            as_of=at,
            scope=scope,
            source_versions=self._source_versions(selected, at),
        )

    def get_evidence(self, state_ref: str) -> EvidenceSet:
        """Return registered evidence referenced by a state/claim/transition result."""
        refs: tuple[str, ...]
        if state_ref in self._assertions:
            refs = self._assertions[state_ref].provenance.evidence_refs
        elif state_ref in self._conflicts:
            refs = self._conflicts[state_ref].evidence_refs
        elif state_ref in self._claims:
            refs = self._claims[state_ref].provenance.evidence_refs
        elif state_ref in self._transitions:
            refs = self._transitions[state_ref].provenance.evidence_refs
        elif state_ref in self._evidence:
            refs = (state_ref,)
        else:
            refs = ()
        return tuple(
            self._evidence[ref]
            for ref in sorted(set(refs))
            if ref in self._evidence
        )

    def get_unknowns(self, scope: SpatialScope | None) -> tuple[Unknown, ...]:
        """Return cached explicit Unknown outcomes for the exact requested scope."""
        scope_key = _scope_key(scope)
        return tuple(
            sorted(
                (
                    item
                    for item in self._unknowns.values()
                    if scope_key in self._outcome_scopes.get(item.unknown_id, set())
                ),
                key=lambda item: item.unknown_id,
            )
        )

    def get_conflicts(self, scope: SpatialScope | None) -> tuple[Conflict, ...]:
        """Return cached explicit Conflict outcomes for the exact requested scope."""
        scope_key = _scope_key(scope)
        return tuple(
            sorted(
                (
                    item
                    for item in self._conflicts.values()
                    if scope_key in self._outcome_scopes.get(item.conflict_id, set())
                ),
                key=lambda item: item.conflict_id,
            )
        )

    def get_history(
        self,
        entity: EntityRef,
        interval: TemporalScope,
    ) -> tuple[StateTransition, ...]:
        """Return canonical transitions within an inclusive temporal interval."""
        return tuple(
            sorted(
                (
                    transition
                    for transition in self._transitions.values()
                    if transition.entity == entity
                    and _time_in_interval(transition.transition_time, interval)
                ),
                key=lambda item: (item.transition_time, item.transition_id),
            )
        )

    def _availability(self, at: datetime) -> ResolutionInputs:
        evidence = tuple(
            item for item in self._evidence.values() if item.recorded_at <= at
        )
        assertion_refs = frozenset(
            assertion.assertion_id
            for assertion in self._assertions.values()
            if assertion.validity.resolved_at <= at
        )
        return ResolutionInputs(
            evidence_refs=frozenset(item.evidence_id for item in evidence),
            source_refs=frozenset(item.source.source_id for item in evidence),
            assertion_refs=assertion_refs,
        )

    def _register_outcome(
        self,
        result: StateQueryResult,
        scope: SpatialScope | None,
    ) -> None:
        if isinstance(result, StateAssertion):
            _put_unique(self._assertions, result.assertion_id, result)
            result_id = result.assertion_id
        elif isinstance(result, Unknown):
            _put_unique(self._unknowns, result.unknown_id, result)
            result_id = result.unknown_id
        elif isinstance(result, Conflict):
            _put_unique(self._conflicts, result.conflict_id, result)
            result_id = result.conflict_id
        else:
            raise TypeError(f"unsupported state result: {type(result).__name__}")
        self._outcome_scopes.setdefault(result_id, set()).add(_scope_key(scope))

    def _source_versions(
        self,
        claims: tuple[Claim, ...],
        at: datetime,
    ) -> dict[str, str]:
        evidence_refs = {
            ref
            for claim in claims
            if claim.created_at <= at
            for ref in claim.provenance.evidence_refs
        }
        versions: dict[str, set[str]] = {}
        for ref in evidence_refs:
            evidence = self._evidence.get(ref)
            if (
                evidence is None
                or evidence.recorded_at > at
                or evidence.source.version is None
            ):
                continue
            versions.setdefault(evidence.source.source_id, set()).add(
                evidence.source.version
            )
        return {
            source_id: next(iter(source_versions))
            for source_id, source_versions in sorted(versions.items())
            if len(source_versions) == 1
        }


def _put_unique(store: dict[str, T], semantic_ref: str, value: T) -> None:
    existing = store.get(semantic_ref)
    if existing is None:
        store[semantic_ref] = value
        return
    if canonical_json(existing) != canonical_json(value):
        raise ValueError(f"semantic ID collision for {semantic_ref}")


def _scope_key(scope: SpatialScope | None) -> str:
    return canonical_json(scope)


def _scope_matches(
    claim_scope: SpatialScope | None,
    requested_scope: SpatialScope | None,
) -> bool:
    if requested_scope is None:
        return True
    if claim_scope is None:
        return False
    return canonical_json(claim_scope) == canonical_json(requested_scope)


def _time_in_interval(value: datetime, interval: TemporalScope) -> bool:
    if interval.start is not None and value < interval.start:
        return False
    if interval.end is not None and value > interval.end:
        return False
    return True
