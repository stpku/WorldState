from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from worldstate import (
    Claim,
    Conflict,
    ConflictResolutionDecision,
    EntityRef,
    EpistemicMode,
    Provenance,
    StateAssertion,
    Unknown,
    apply_conflict_resolution_policy,
    conflict_resolution_decision_payload,
)
from worldstate.ids import semantic_id
from worldstate.resolution import ReferenceResolver, ResolutionInputs

UTC = timezone.utc
AT = datetime(2026, 8, 26, 0, 0, tzinfo=UTC)
ENTITY = EntityRef("asset-1", entity_type="asset")


def _claim(claim_id: str, value: str, source_ref: str, evidence_ref: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        entity=ENTITY,
        property_key="status",
        value=value,
        epistemic_mode=EpistemicMode.OBSERVED,
        provenance=Provenance(
            evidence_refs=(evidence_ref,),
            source_refs=(source_ref,),
            method="direct-observation",
        ),
        created_at=AT - timedelta(minutes=1),
    )


def _conflict() -> tuple[Conflict, tuple[Claim, Claim]]:
    claims = (
        _claim("claim-a", "open", "source-a", "ev-a"),
        _claim("claim-b", "closed", "source-b", "ev-b"),
    )
    result = ReferenceResolver().resolve_state(
        claims,
        ENTITY,
        "status",
        AT,
        available=ResolutionInputs(
            evidence_refs=frozenset({"ev-a", "ev-b"}),
            source_refs=frozenset({"source-a", "source-b"}),
        ),
    )
    assert isinstance(result, Conflict)
    return result, claims


class SourcePriorityPolicy:
    policy_ref = "policy://source-priority/v0.1"
    version = "0.1"

    def __init__(self, priority: tuple[str, ...]) -> None:
        self.priority = priority

    def decide(self, conflict: Conflict, claims: tuple[Claim, ...], *, at: datetime):
        ranks = {source: index for index, source in enumerate(self.priority)}
        ranked = []
        for claim in claims:
            source = claim.provenance.source_refs[0]
            if source in ranks:
                ranked.append((ranks[source], claim.claim_id))
        if not ranked:
            status = "preserved"
            selected = None
            reason = "policy has no ranked source among conflict candidates"
        else:
            best_rank = min(rank for rank, _ in ranked)
            winners = sorted(ref for rank, ref in ranked if rank == best_rank)
            if len(winners) != 1:
                status = "preserved"
                selected = None
                reason = "policy priority does not produce one unique candidate"
            else:
                status = "resolved"
                selected = winners[0]
                reason = "explicit source-priority policy selected one conflict candidate"
        payload = {
            "conflict_id": conflict.conflict_id,
            "policy_ref": self.policy_ref,
            "policy_version": self.version,
            "at": at,
            "status": status,
            "selected": selected,
            "priority": self.priority,
        }
        return ConflictResolutionDecision(
            decision_id=semantic_id("conflict_resolution_decision", payload),
            conflict_id=conflict.conflict_id,
            policy_ref=self.policy_ref,
            policy_version=self.version,
            decided_at=at,
            status=status,
            selected_claim_ref=selected,
            reason=reason,
            source_refs=(conflict.conflict_id, self.policy_ref),
        )


def test_default_reference_resolver_still_preserves_disagreement() -> None:
    conflict, _ = _conflict()
    assert conflict.candidate_refs == ("claim-a", "claim-b")


def test_explicit_policy_can_resolve_existing_candidate_with_provenance() -> None:
    conflict, claims = _conflict()
    result = apply_conflict_resolution_policy(
        conflict,
        claims,
        SourcePriorityPolicy(("source-b", "source-a")),
    )

    assert result.decision.status == "resolved"
    assert result.decision.selected_claim_ref == "claim-b"
    assert isinstance(result.outcome, StateAssertion)
    assert result.outcome.value == "closed"
    assert result.outcome.provenance.resolver == "policy://source-priority/v0.1@0.1"
    assert result.decision.decision_id in result.outcome.provenance.method
    assert result.outcome.provenance.evidence_refs == ("ev-a", "ev-b")
    assert result.outcome.provenance.source_refs == ("source-a", "source-b")


def test_policy_without_basis_preserves_original_conflict() -> None:
    conflict, claims = _conflict()
    result = apply_conflict_resolution_policy(
        conflict,
        claims,
        SourcePriorityPolicy(("source-c",)),
    )

    assert result.decision.status == "preserved"
    assert result.outcome is conflict


def test_decision_payload_is_deterministic_and_traceable() -> None:
    conflict, claims = _conflict()
    result = apply_conflict_resolution_policy(
        conflict,
        claims,
        SourcePriorityPolicy(("source-a", "source-b")),
    )
    payload = conflict_resolution_decision_payload(result.decision)

    assert payload["contract"] == "worldstate.conflict-resolution-decision"
    assert payload["contract_version"] == "0.1"
    assert payload["conflict_id"] == conflict.conflict_id
    assert payload["policy_ref"] == "policy://source-priority/v0.1"
    assert payload["selected_claim_ref"] == "claim-a"
    assert payload["source_refs"] == [conflict.conflict_id, "policy://source-priority/v0.1"]


def test_claim_set_must_exactly_cover_conflict_candidates() -> None:
    conflict, claims = _conflict()
    with pytest.raises(ValueError, match="exactly cover"):
        apply_conflict_resolution_policy(
            conflict,
            claims[:1],
            SourcePriorityPolicy(("source-a",)),
        )


def test_policy_cannot_select_non_candidate() -> None:
    conflict, claims = _conflict()

    class ForgedPolicy(SourcePriorityPolicy):
        def decide(self, conflict, claims, *, at):
            decision = super().decide(conflict, claims, at=at)
            return ConflictResolutionDecision(
                decision_id=decision.decision_id,
                conflict_id=decision.conflict_id,
                policy_ref=decision.policy_ref,
                policy_version=decision.policy_version,
                decided_at=decision.decided_at,
                status="resolved",
                selected_claim_ref="claim-forged",
                reason="forged selection",
                source_refs=decision.source_refs,
            )

    with pytest.raises(ValueError, match="not a conflict candidate"):
        apply_conflict_resolution_policy(
            conflict,
            claims,
            ForgedPolicy(("source-a",)),
        )


def test_policy_decision_must_include_conflict_and_policy_lineage() -> None:
    conflict, claims = _conflict()

    class MissingLineagePolicy(SourcePriorityPolicy):
        def decide(self, conflict, claims, *, at):
            decision = super().decide(conflict, claims, at=at)
            return ConflictResolutionDecision(
                decision_id=decision.decision_id,
                conflict_id=decision.conflict_id,
                policy_ref=decision.policy_ref,
                policy_version=decision.policy_version,
                decided_at=decision.decided_at,
                status=decision.status,
                selected_claim_ref=decision.selected_claim_ref,
                reason=decision.reason,
                source_refs=(self.policy_ref,),
            )

    with pytest.raises(ValueError, match="source_refs"):
        apply_conflict_resolution_policy(
            conflict,
            claims,
            MissingLineagePolicy(("source-a",)),
        )


def test_policy_identity_must_match_decision_identity() -> None:
    conflict, claims = _conflict()

    class WrongIdentityPolicy(SourcePriorityPolicy):
        def decide(self, conflict, claims, *, at):
            decision = super().decide(conflict, claims, at=at)
            return ConflictResolutionDecision(
                decision_id=decision.decision_id,
                conflict_id=decision.conflict_id,
                policy_ref="policy://other",
                policy_version=decision.policy_version,
                decided_at=decision.decided_at,
                status=decision.status,
                selected_claim_ref=decision.selected_claim_ref,
                reason=decision.reason,
                source_refs=(conflict.conflict_id, "policy://other"),
            )

    with pytest.raises(ValueError, match="identity/version mismatch"):
        apply_conflict_resolution_policy(
            conflict,
            claims,
            WrongIdentityPolicy(("source-a",)),
        )


def test_unknown_can_resolve_only_when_missing_support_becomes_available() -> None:
    claim = _claim("claim-a", "open", "source-a", "ev-a")
    resolver = ReferenceResolver()
    before = resolver.resolve_state(
        (claim,),
        ENTITY,
        "status",
        AT,
        available=ResolutionInputs(),
    )
    after = resolver.resolve_state(
        (claim,),
        ENTITY,
        "status",
        AT,
        available=ResolutionInputs(
            evidence_refs=frozenset({"ev-a"}),
            source_refs=frozenset({"source-a"}),
        ),
    )

    assert isinstance(before, Unknown)
    assert isinstance(after, StateAssertion)
    assert after.value == "open"
