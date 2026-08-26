from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Collection, Literal, Protocol

from .ids import semantic_id
from .models import Claim, Conflict, Provenance, StateAssertion, StateQueryResult, Validity

CONFLICT_RESOLUTION_CONTRACT_VERSION = "0.1"

ResolutionDecisionStatus = Literal["resolved", "preserved"]


@dataclass(frozen=True, slots=True)
class ConflictResolutionDecision:
    """Explicit policy decision over one already-materialized Conflict."""

    decision_id: str
    conflict_id: str
    policy_ref: str
    policy_version: str
    decided_at: datetime
    status: ResolutionDecisionStatus
    reason: str
    selected_claim_ref: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("decision_id", self.decision_id),
            ("conflict_id", self.conflict_id),
            ("policy_ref", self.policy_ref),
            ("policy_version", self.policy_version),
            ("reason", self.reason),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() != timedelta(0):
            raise ValueError("decided_at must be timezone-aware UTC")
        if self.status == "resolved":
            if self.selected_claim_ref is None or not self.selected_claim_ref.strip():
                raise ValueError("resolved decision requires selected_claim_ref")
        elif self.status == "preserved":
            if self.selected_claim_ref is not None:
                raise ValueError("preserved decision must not select a claim")
        else:
            raise ValueError(f"unsupported resolution decision status: {self.status}")
        if any(not ref.strip() for ref in self.source_refs):
            raise ValueError("source_refs must not contain empty references")


class ConflictResolutionPolicy(Protocol):
    @property
    def policy_ref(self) -> str: ...

    @property
    def version(self) -> str: ...

    def decide(
        self,
        conflict: Conflict,
        claims: tuple[Claim, ...],
        *,
        at: datetime,
    ) -> ConflictResolutionDecision: ...


@dataclass(frozen=True, slots=True)
class ConflictResolutionResult:
    """Auditable result retaining both policy decision and state outcome."""

    conflict: Conflict
    decision: ConflictResolutionDecision
    outcome: StateQueryResult


def apply_conflict_resolution_policy(
    conflict: Conflict,
    claims: Collection[Claim],
    policy: ConflictResolutionPolicy,
) -> ConflictResolutionResult:
    """Apply one explicit policy without weakening the default conservative resolver.

    The supplied claims must exactly cover the conflict candidate set. Policies may
    either preserve the conflict or select one existing candidate. They may not
    invent a new value, omit a conflicting candidate, or silently change the query
    time boundary.
    """

    ordered = tuple(sorted(claims, key=lambda item: item.claim_id))
    claim_refs = tuple(item.claim_id for item in ordered)
    if len(set(claim_refs)) != len(claim_refs):
        raise ValueError("conflict resolution claims must have unique claim_id values")
    if claim_refs != tuple(sorted(conflict.candidate_refs)):
        raise ValueError("claims must exactly cover conflict.candidate_refs")

    for claim in ordered:
        if claim.entity != conflict.entity or claim.property_key != conflict.property_key:
            raise ValueError("conflict resolution claim does not match conflict proposition")
        if claim.created_at > conflict.as_of:
            raise ValueError("conflict resolution cannot use a claim created after conflict.as_of")
        scope = claim.temporal_scope
        if scope is not None:
            if scope.start is not None and conflict.as_of < scope.start:
                raise ValueError("conflict resolution claim is not yet valid at conflict.as_of")
            if scope.end is not None and conflict.as_of > scope.end:
                raise ValueError("conflict resolution claim is expired at conflict.as_of")

    decision = policy.decide(conflict, ordered, at=conflict.as_of)
    if decision.conflict_id != conflict.conflict_id:
        raise ValueError("resolution decision must bind the supplied conflict")
    if decision.policy_ref != policy.policy_ref or decision.policy_version != policy.version:
        raise ValueError("resolution decision policy identity/version mismatch")
    if decision.decided_at != conflict.as_of:
        raise ValueError("resolution decision must preserve conflict.as_of")
    required_lineage = {conflict.conflict_id, policy.policy_ref}
    if not required_lineage.issubset(set(decision.source_refs)):
        raise ValueError("resolution decision source_refs must include conflict and policy refs")

    if decision.status == "preserved":
        return ConflictResolutionResult(conflict=conflict, decision=decision, outcome=conflict)

    selected = next(
        (claim for claim in ordered if claim.claim_id == decision.selected_claim_ref),
        None,
    )
    if selected is None:
        raise ValueError("resolution decision selected_claim_ref is not a conflict candidate")

    evidence_refs = tuple(
        sorted(
            {
                ref
                for claim in ordered
                for ref in claim.provenance.evidence_refs
            }
        )
    )
    source_refs = tuple(
        sorted(
            {
                ref
                for claim in ordered
                for ref in claim.provenance.source_refs
            }
        )
    )
    parent_assertion_refs = tuple(
        sorted(
            {
                ref
                for claim in ordered
                for ref in claim.provenance.parent_assertion_refs
            }
        )
    )
    provenance = Provenance(
        evidence_refs=evidence_refs,
        source_refs=source_refs,
        parent_assertion_refs=parent_assertion_refs,
        method=f"conflict-resolution-policy:{decision.decision_id}",
        resolver=f"{policy.policy_ref}@{policy.version}",
    )
    validity = Validity(
        resolved_at=conflict.as_of,
        valid_from=None if selected.temporal_scope is None else selected.temporal_scope.start,
        valid_until=None if selected.temporal_scope is None else selected.temporal_scope.end,
    )
    assertion_payload = {
        "conflict_id": conflict.conflict_id,
        "decision_id": decision.decision_id,
        "policy_ref": policy.policy_ref,
        "policy_version": policy.version,
        "selected_claim_ref": selected.claim_id,
        "entity": selected.entity,
        "property_key": selected.property_key,
        "value": selected.value,
        "epistemic_mode": selected.epistemic_mode,
        "validity": validity,
        "provenance": provenance,
        "uncertainty": selected.uncertainty,
        "spatial_scope": selected.spatial_scope,
    }
    assertion = StateAssertion(
        assertion_id=semantic_id("state", assertion_payload),
        entity=selected.entity,
        property_key=selected.property_key,
        value=selected.value,
        epistemic_mode=selected.epistemic_mode,
        validity=validity,
        provenance=provenance,
        version=CONFLICT_RESOLUTION_CONTRACT_VERSION,
        uncertainty=selected.uncertainty,
        spatial_scope=selected.spatial_scope,
    )
    return ConflictResolutionResult(conflict=conflict, decision=decision, outcome=assertion)


def conflict_resolution_decision_payload(
    decision: ConflictResolutionDecision,
) -> dict[str, object]:
    return {
        "contract": "worldstate.conflict-resolution-decision",
        "contract_version": CONFLICT_RESOLUTION_CONTRACT_VERSION,
        "decision_id": decision.decision_id,
        "conflict_id": decision.conflict_id,
        "policy_ref": decision.policy_ref,
        "policy_version": decision.policy_version,
        "decided_at": decision.decided_at.isoformat().replace("+00:00", "Z"),
        "status": decision.status,
        "reason": decision.reason,
        "selected_claim_ref": decision.selected_claim_ref,
        "source_refs": list(decision.source_refs),
    }
