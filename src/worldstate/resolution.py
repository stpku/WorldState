from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Collection, Iterable

from .ids import canonical_json, semantic_id
from .models import (
    Claim,
    Conflict,
    EntityRef,
    Provenance,
    SpatialScope,
    StateAssertion,
    StateQueryResult,
    Uncertainty,
    Unknown,
    UnknownReason,
    Validity,
)

REFERENCE_RESOLVER_ID = "worldstate.reference-conservative"
REFERENCE_RESOLVER_VERSION = "0.1"


@dataclass(frozen=True, slots=True)
class ResolutionInputs:
    """Availability boundary used by the deterministic reference resolver."""

    evidence_refs: frozenset[str] = frozenset()
    source_refs: frozenset[str] = frozenset()
    assertion_refs: frozenset[str] = frozenset()


class ReferenceResolver:
    """Conservative deterministic resolver for the M1 conformance baseline.

    The resolver never ranks sources, timestamps, or confidence values. It emits
    an assertion only when all usable claims materially agree. Otherwise it
    preserves absence as ``Unknown`` and disagreement as ``Conflict``.
    """

    resolver_id = REFERENCE_RESOLVER_ID
    version = REFERENCE_RESOLVER_VERSION

    def resolve_state(
        self,
        claims: Iterable[Claim],
        entity: EntityRef,
        property_key: str,
        at: datetime,
        *,
        available: ResolutionInputs | None = None,
    ) -> StateQueryResult:
        """Resolve one entity/property proposition at a UTC ``at`` boundary."""
        if not property_key.strip():
            raise ValueError("property_key must be a non-empty string")

        availability = available or ResolutionInputs()
        matching = tuple(
            sorted(
                (
                    claim
                    for claim in claims
                    if claim.entity == entity and claim.property_key == property_key
                ),
                key=lambda claim: claim.claim_id,
            )
        )

        if not matching:
            return self._unknown(
                entity,
                property_key,
                at,
                UnknownReason.NO_EVIDENCE,
            )

        visible = tuple(claim for claim in matching if claim.created_at <= at)
        if not visible:
            return self._unknown(
                entity,
                property_key,
                at,
                UnknownReason.NO_EVIDENCE,
            )

        active = tuple(claim for claim in visible if _contains(claim, at))
        if not active:
            return self._unknown(
                entity,
                property_key,
                at,
                UnknownReason.OUTSIDE_VALIDITY,
            )

        usable: list[Claim] = []
        missing: set[str] = set()
        for claim in active:
            claim_missing = _missing_provenance_refs(claim, availability)
            if claim_missing:
                missing.update(claim_missing)
                continue
            usable.append(claim)

        if not usable:
            return self._unknown(
                entity,
                property_key,
                at,
                UnknownReason.INSUFFICIENT_EVIDENCE,
                missing=tuple(sorted(missing)),
            )

        material_keys = {_material_key(claim) for claim in usable}
        if len(material_keys) != 1:
            return self._conflict(entity, property_key, at, usable)

        return self._assertion(entity, property_key, at, usable)

    def _unknown(
        self,
        entity: EntityRef,
        property_key: str,
        at: datetime,
        reason: UnknownReason,
        *,
        missing: tuple[str, ...] = (),
    ) -> Unknown:
        payload = {
            "entity": entity,
            "property_key": property_key,
            "reason": reason,
            "as_of": at,
            "missing": missing,
            "resolver": self.resolver_id,
            "version": self.version,
        }
        return Unknown(
            unknown_id=semantic_id("unknown", payload),
            reason=reason,
            as_of=at,
            entity=entity,
            property_key=property_key,
            missing=missing,
            metadata={
                "resolver": self.resolver_id,
                "resolver_version": self.version,
            },
        )

    def _conflict(
        self,
        entity: EntityRef,
        property_key: str,
        at: datetime,
        claims: Collection[Claim],
    ) -> Conflict:
        candidate_refs = tuple(sorted(claim.claim_id for claim in claims))
        evidence_refs = tuple(
            sorted(
                {
                    evidence_ref
                    for claim in claims
                    for evidence_ref in claim.provenance.evidence_refs
                }
            )
        )
        reason = "materially incompatible claims"
        payload = {
            "entity": entity,
            "property_key": property_key,
            "candidate_refs": candidate_refs,
            "evidence_refs": evidence_refs,
            "reason": reason,
            "as_of": at,
            "resolver": self.resolver_id,
            "version": self.version,
        }
        return Conflict(
            conflict_id=semantic_id("conflict", payload),
            entity=entity,
            property_key=property_key,
            candidate_refs=candidate_refs,
            evidence_refs=evidence_refs,
            reason=reason,
            as_of=at,
            metadata={
                "resolver": self.resolver_id,
                "resolver_version": self.version,
            },
        )

    def _assertion(
        self,
        entity: EntityRef,
        property_key: str,
        at: datetime,
        claims: Collection[Claim],
    ) -> StateAssertion:
        ordered = tuple(sorted(claims, key=lambda claim: claim.claim_id))
        first = ordered[0]
        provenance = Provenance(
            evidence_refs=_collect_refs(ordered, "evidence_refs"),
            source_refs=_collect_refs(ordered, "source_refs"),
            parent_assertion_refs=_collect_refs(ordered, "parent_assertion_refs"),
            method="reference-resolution",
            resolver=f"{self.resolver_id}@{self.version}",
        )
        validity = Validity(
            valid_from=_latest_start(ordered),
            valid_until=_earliest_end(ordered),
            resolved_at=at,
        )
        uncertainty = _shared_uncertainty(ordered)
        spatial_scope = _shared_spatial_scope(ordered)
        payload = {
            "entity": entity,
            "property_key": property_key,
            "value": first.value,
            "epistemic_mode": first.epistemic_mode,
            "validity": validity,
            "provenance": provenance,
            "uncertainty": uncertainty,
            "spatial_scope": spatial_scope,
            "resolver": self.resolver_id,
            "version": self.version,
        }
        return StateAssertion(
            assertion_id=semantic_id("state", payload),
            entity=entity,
            property_key=property_key,
            value=first.value,
            epistemic_mode=first.epistemic_mode,
            validity=validity,
            provenance=provenance,
            version=self.version,
            uncertainty=uncertainty,
            spatial_scope=spatial_scope,
        )


def _contains(claim: Claim, at: datetime) -> bool:
    scope = claim.temporal_scope
    if scope is None:
        return True
    if scope.start is not None and at < scope.start:
        return False
    if scope.end is not None and at > scope.end:
        return False
    return True


def _missing_provenance_refs(
    claim: Claim,
    available: ResolutionInputs,
) -> tuple[str, ...]:
    provenance = claim.provenance
    missing: set[str] = set()
    missing.update(set(provenance.evidence_refs) - available.evidence_refs)
    missing.update(set(provenance.source_refs) - available.source_refs)
    missing.update(set(provenance.parent_assertion_refs) - available.assertion_refs)
    return tuple(sorted(missing))


def _material_key(claim: Claim) -> tuple[str, str, str]:
    spatial = "null" if claim.spatial_scope is None else canonical_json(claim.spatial_scope)
    return (
        canonical_json(claim.value),
        claim.epistemic_mode.value,
        spatial,
    )


def _collect_refs(claims: Collection[Claim], field_name: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                ref
                for claim in claims
                for ref in getattr(claim.provenance, field_name)
            }
        )
    )


def _latest_start(claims: Collection[Claim]) -> datetime | None:
    starts = tuple(
        claim.temporal_scope.start
        for claim in claims
        if claim.temporal_scope is not None and claim.temporal_scope.start is not None
    )
    return max(starts) if starts else None


def _earliest_end(claims: Collection[Claim]) -> datetime | None:
    ends = tuple(
        claim.temporal_scope.end
        for claim in claims
        if claim.temporal_scope is not None and claim.temporal_scope.end is not None
    )
    return min(ends) if ends else None


def _shared_uncertainty(claims: Collection[Claim]) -> Uncertainty | None:
    values = tuple(claim.uncertainty for claim in claims)
    if not values:
        return None
    first = values[0]
    if all(canonical_json(value) == canonical_json(first) for value in values):
        return first
    return None


def _shared_spatial_scope(claims: Collection[Claim]) -> SpatialScope | None:
    values = tuple(claim.spatial_scope for claim in claims)
    if not values:
        return None
    first = values[0]
    if all(canonical_json(value) == canonical_json(first) for value in values):
        return first
    return None
