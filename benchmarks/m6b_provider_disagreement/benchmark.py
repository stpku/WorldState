from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from examples.providers.external import (
    DirectExternalSource,
    DirectExternalWorldStateProvider,
    ExternalStateRecord,
)
from examples.providers.projection import (
    ExternalRecordStore,
    ProjectionWorldStateProvider,
    SoRRecord,
)
from worldstate import (
    Claim,
    Conflict,
    ConflictResolutionDecision,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    Provenance,
    Source,
    StateAssertion,
    StateQueryResult,
    apply_conflict_resolution_policy,
    build_snapshot,
    diff_snapshots,
    semantic_id,
)
from worldstate.change import ChangeKind
from worldstate.resolution import ReferenceResolver, ResolutionInputs

CASES_PATH = Path(__file__).with_name("cases.json")
POLICY_REF = "policy://benchmark/provider-mode-priority/v0.1"
POLICY_VERSION = "0.1"
FALSE_RESOLUTION_THRESHOLD = 0.0
PROVIDER_MODES = ("native", "projection", "direct-external")


@dataclass(frozen=True, slots=True)
class EpochRun:
    epoch_id: str
    at: datetime
    provider_assertions: Mapping[str, StateAssertion]
    fusion_claims: tuple[Claim, ...]
    fused_result: StateQueryResult
    snapshot: object


class ProviderModePriorityPolicy:
    """Benchmark-local policy over explicit provider-mode lineage only."""

    policy_ref = POLICY_REF
    version = POLICY_VERSION

    def __init__(self, priority: tuple[str, ...]) -> None:
        self.priority = priority

    def decide(
        self,
        conflict: Conflict,
        claims: tuple[Claim, ...],
        *,
        at: datetime,
    ) -> ConflictResolutionDecision:
        rank = {provider_ref: index for index, provider_ref in enumerate(self.priority)}
        ranked: list[tuple[int, str, str]] = []
        for claim in claims:
            provider_refs = tuple(
                ref for ref in claim.provenance.source_refs if ref.startswith("provider://")
            )
            candidate_ranks = [rank[ref] for ref in provider_refs if ref in rank]
            if candidate_ranks:
                ranked.append((min(candidate_ranks), claim.claim_id, provider_refs[0]))

        if not ranked:
            status = "preserved"
            selected = None
            selected_provider = None
            reason = "no conflict candidate has an explicitly ranked provider mode"
        else:
            best_rank = min(item[0] for item in ranked)
            winners = tuple(sorted(item for item in ranked if item[0] == best_rank))
            if len(winners) != 1:
                status = "preserved"
                selected = None
                selected_provider = None
                reason = "provider-mode ranking does not produce one unique candidate"
            else:
                _, selected, selected_provider = winners[0]
                status = "resolved"
                reason = f"explicit provider-mode priority selected {selected_provider}"

        payload = {
            "conflict_id": conflict.conflict_id,
            "policy_ref": self.policy_ref,
            "policy_version": self.version,
            "priority": self.priority,
            "selected_claim_ref": selected,
            "selected_provider_ref": selected_provider,
            "status": status,
            "at": at,
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


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("benchmark times must be UTC")
    return parsed


def _native_provider(
    entity: EntityRef,
    property_key: str,
    value: object,
    version: str,
    at: datetime,
) -> InMemoryWorldState:
    provider = InMemoryWorldState()
    source = Source(
        source_id="native-source",
        source_type="benchmark-native",
        version=version,
    )
    evidence_id = semantic_id(
        "ev",
        {"provider_mode": "native", "version": version, "value": value, "at": at},
    )
    provider.add_evidence(
        Evidence(
            evidence_id=evidence_id,
            source=source,
            recorded_at=at - timedelta(minutes=1),
        )
    )
    provider.add_claim(
        Claim(
            claim_id=semantic_id(
                "claim",
                {
                    "provider_mode": "native",
                    "version": version,
                    "entity": entity,
                    "property_key": property_key,
                    "value": value,
                },
            ),
            entity=entity,
            property_key=property_key,
            value=value,
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=(evidence_id,),
                source_refs=(source.source_id,),
                method="benchmark-native",
            ),
            created_at=at - timedelta(seconds=30),
        )
    )
    return provider


def _projection_provider(
    entity: EntityRef,
    property_key: str,
    value: object,
    version: str,
    at: datetime,
) -> ProjectionWorldStateProvider:
    store = ExternalRecordStore()
    store.put(
        SoRRecord(
            record_id="fusion-record",
            entity=entity,
            property_key=property_key,
            value=value,
            updated_at=at - timedelta(seconds=30),
            version=version,
        )
    )
    return ProjectionWorldStateProvider(store)


def _direct_provider(
    entity: EntityRef,
    property_key: str,
    value: object,
    version: str,
    at: datetime,
) -> DirectExternalWorldStateProvider:
    source = DirectExternalSource(source_version=version)
    source.put(
        ExternalStateRecord(
            record_id="fusion-record",
            entity=entity,
            property_key=property_key,
            value=value,
            updated_at=at - timedelta(seconds=30),
            record_version=version,
        )
    )
    return DirectExternalWorldStateProvider(source)


def _provider_assertions(
    entity: EntityRef,
    property_key: str,
    raw_epoch: Mapping[str, Any],
    at: datetime,
) -> dict[str, StateAssertion]:
    provider_specs = {
        "native": raw_epoch["native"],
        "projection": raw_epoch["projection"],
        "direct-external": raw_epoch["direct_external"],
    }
    providers = {
        "native": _native_provider(
            entity,
            property_key,
            provider_specs["native"]["value"],
            str(provider_specs["native"]["version"]),
            at,
        ),
        "projection": _projection_provider(
            entity,
            property_key,
            provider_specs["projection"]["value"],
            str(provider_specs["projection"]["version"]),
            at,
        ),
        "direct-external": _direct_provider(
            entity,
            property_key,
            provider_specs["direct-external"]["value"],
            str(provider_specs["direct-external"]["version"]),
            at,
        ),
    }
    assertions: dict[str, StateAssertion] = {}
    for mode in PROVIDER_MODES:
        result = providers[mode].query_state(entity, property_key, at)
        if not isinstance(result, StateAssertion):
            raise ValueError(f"benchmark provider {mode} did not return StateAssertion")
        assertions[mode] = result
    return assertions


def _fusion_claim(mode: str, assertion: StateAssertion, at: datetime) -> Claim:
    provider_ref = f"provider://{mode}"
    claim_id = semantic_id(
        "claim",
        {
            "provider_ref": provider_ref,
            "source_assertion_ref": assertion.assertion_id,
            "entity": assertion.entity,
            "property_key": assertion.property_key,
            "value": assertion.value,
            "epistemic_mode": assertion.epistemic_mode,
            "at": at,
        },
    )
    return Claim(
        claim_id=claim_id,
        entity=assertion.entity,
        property_key=assertion.property_key,
        value=assertion.value,
        epistemic_mode=assertion.epistemic_mode,
        provenance=Provenance(
            evidence_refs=assertion.provenance.evidence_refs,
            source_refs=(provider_ref, *assertion.provenance.source_refs),
            parent_assertion_refs=(assertion.assertion_id,),
            method=f"provider-fusion:{mode}",
        ),
        created_at=at,
        spatial_scope=assertion.spatial_scope,
        uncertainty=assertion.uncertainty,
    )


def _run_epoch(fixture: Mapping[str, Any], raw_epoch: Mapping[str, Any]) -> EpochRun:
    at = _parse_time(str(raw_epoch["at"]))
    entity = EntityRef(str(fixture["entity_id"]), entity_type="benchmark-asset")
    property_key = str(fixture["property_key"])
    assertions = _provider_assertions(entity, property_key, raw_epoch, at)
    claims = tuple(_fusion_claim(mode, assertions[mode], at) for mode in PROVIDER_MODES)
    evidence_refs = frozenset(
        ref for claim in claims for ref in claim.provenance.evidence_refs
    )
    source_refs = frozenset(ref for claim in claims for ref in claim.provenance.source_refs)
    parent_refs = frozenset(
        ref for claim in claims for ref in claim.provenance.parent_assertion_refs
    )
    fused = ReferenceResolver().resolve_state(
        claims,
        entity,
        property_key,
        at,
        available=ResolutionInputs(
            evidence_refs=evidence_refs,
            source_refs=source_refs,
            assertion_refs=parent_refs,
        ),
    )
    source_versions = {
        "native": str(raw_epoch["native"]["version"]),
        "projection": str(raw_epoch["projection"]["version"]),
        "direct-external": str(raw_epoch["direct_external"]["version"]),
    }
    snapshot = build_snapshot((fused,), as_of=at, source_versions=source_versions)
    return EpochRun(
        epoch_id=str(raw_epoch["epoch_id"]),
        at=at,
        provider_assertions=assertions,
        fusion_claims=claims,
        fused_result=fused,
        snapshot=snapshot,
    )


def _kind(result: StateQueryResult) -> str:
    if isinstance(result, StateAssertion):
        return "assertion"
    if isinstance(result, Conflict):
        return "conflict"
    return "unknown"


def run_benchmark(cases_path: Path = CASES_PATH) -> dict[str, object]:
    fixture = json.loads(cases_path.read_text(encoding="utf-8"))
    runs = tuple(_run_epoch(fixture, raw_epoch) for raw_epoch in fixture["epochs"])
    replay_runs = tuple(_run_epoch(fixture, raw_epoch) for raw_epoch in fixture["epochs"])

    expected_by_epoch = {str(item["epoch_id"]): item for item in fixture["epochs"]}
    provider_mode_coverage = sum(
        len(run.provider_assertions) == len(PROVIDER_MODES)
        and set(run.provider_assertions) == set(PROVIDER_MODES)
        for run in runs
    ) / len(runs)
    replay_stability = sum(
        run.snapshot.snapshot_id == replay.snapshot.snapshot_id
        and run.fused_result == replay.fused_result
        for run, replay in zip(runs, replay_runs, strict=True)
    ) / len(runs)

    expected_conflict_epochs = sum(
        1 for item in fixture["epochs"] if item["expected_kind"] == "conflict"
    )
    preserved_conflict_epochs = sum(
        1
        for run in runs
        if expected_by_epoch[run.epoch_id]["expected_kind"] == "conflict"
        and isinstance(run.fused_result, Conflict)
    )
    conflict_persistence_rate = (
        preserved_conflict_epochs / expected_conflict_epochs if expected_conflict_epochs else 1.0
    )

    unsupported_resolution_count = 0
    expected_assertion_miss_count = 0
    for run in runs:
        expected = expected_by_epoch[run.epoch_id]
        if expected["expected_kind"] == "conflict" and isinstance(run.fused_result, StateAssertion):
            unsupported_resolution_count += 1
        if expected["expected_kind"] == "assertion":
            if not isinstance(run.fused_result, StateAssertion):
                expected_assertion_miss_count += 1
            elif run.fused_result.value != expected.get("expected_value"):
                unsupported_resolution_count += 1

    deltas = tuple(
        diff_snapshots(before.snapshot, after.snapshot)
        for before, after in zip(runs, runs[1:])
    )
    delta_kinds = tuple(
        delta.changes[0].kind if len(delta.changes) == 1 else None for delta in deltas
    )
    change_semantics_pass = delta_kinds == (
        ChangeKind.CONFLICT_CHANGED,
        ChangeKind.CONFLICT_RESOLVED,
    )

    policy_fixture = fixture["policy_resolution"]
    policy_epoch = next(run for run in runs if run.epoch_id == policy_fixture["epoch_id"])
    if not isinstance(policy_epoch.fused_result, Conflict):
        policy_result = None
        policy_replay = None
    else:
        priority = tuple(str(item) for item in policy_fixture["priority"])
        policy = ProviderModePriorityPolicy(priority)
        policy_result = apply_conflict_resolution_policy(
            policy_epoch.fused_result,
            policy_epoch.fusion_claims,
            policy,
        )
        policy_replay = apply_conflict_resolution_policy(
            policy_epoch.fused_result,
            policy_epoch.fusion_claims,
            ProviderModePriorityPolicy(priority),
        )

    policy_false_resolution = 0
    policy_provenance_pass = False
    policy_replay_pass = False
    policy_reason = None
    policy_value = None
    if policy_result is not None and policy_replay is not None:
        policy_reason = policy_result.decision.reason
        if isinstance(policy_result.outcome, StateAssertion):
            policy_value = policy_result.outcome.value
            if policy_value != policy_fixture["expected_value"]:
                policy_false_resolution = 1
            policy_provenance_pass = (
                policy_result.outcome.provenance.resolver
                == f"{POLICY_REF}@{POLICY_VERSION}"
                and policy_result.decision.decision_id in policy_result.outcome.provenance.method
            )
        policy_replay_pass = (
            policy_result.decision == policy_replay.decision
            and policy_result.outcome == policy_replay.outcome
        )

    policy_resolution_count = (
        1
        if policy_result is not None and policy_result.decision.status == "resolved"
        else 0
    )
    false_resolution_rate = (
        policy_false_resolution / policy_resolution_count if policy_resolution_count else 0.0
    )

    safety_gate = (
        provider_mode_coverage == 1.0
        and replay_stability == 1.0
        and conflict_persistence_rate == 1.0
        and unsupported_resolution_count == 0
        and expected_assertion_miss_count == 0
        and false_resolution_rate <= FALSE_RESOLUTION_THRESHOLD
        and policy_provenance_pass
        and policy_replay_pass
        and change_semantics_pass
    )
    persistence_gate = (
        conflict_persistence_rate == 1.0
        and change_semantics_pass
        and replay_stability == 1.0
    )
    utility_gate = (
        policy_resolution_count == 1
        and policy_value == policy_fixture["expected_value"]
        and policy_replay_pass
    )

    return {
        "contract": "worldstate.m6b-provider-disagreement-benchmark",
        "version": "0.1",
        "provider_modes": list(PROVIDER_MODES),
        "epochs": [
            {
                "epoch_id": run.epoch_id,
                "provider_values": {
                    mode: assertion.value
                    for mode, assertion in sorted(run.provider_assertions.items())
                },
                "fused_kind": _kind(run.fused_result),
                "fused_ref": (
                    run.fused_result.assertion_id
                    if isinstance(run.fused_result, StateAssertion)
                    else run.fused_result.conflict_id
                    if isinstance(run.fused_result, Conflict)
                    else run.fused_result.unknown_id
                ),
                "expected_kind": expected_by_epoch[run.epoch_id]["expected_kind"],
            }
            for run in runs
        ],
        "deltas": [
            {
                "from": runs[index].epoch_id,
                "to": runs[index + 1].epoch_id,
                "kind": delta.changes[0].kind.value if len(delta.changes) == 1 else None,
                "change_count": len(delta.changes),
            }
            for index, delta in enumerate(deltas)
        ],
        "policy_resolution": {
            "epoch_id": policy_fixture["epoch_id"],
            "decision_status": None if policy_result is None else policy_result.decision.status,
            "decision_id": None if policy_result is None else policy_result.decision.decision_id,
            "reason": policy_reason,
            "outcome_value": policy_value,
            "replay_stable": policy_replay_pass,
            "provenance_pass": policy_provenance_pass,
        },
        "metrics": {
            "provider_mode_count": len(PROVIDER_MODES),
            "provider_mode_coverage_rate": provider_mode_coverage,
            "epoch_count": len(runs),
            "expected_conflict_epochs": expected_conflict_epochs,
            "preserved_conflict_epochs": preserved_conflict_epochs,
            "conflict_persistence_rate": conflict_persistence_rate,
            "replay_stability_rate": replay_stability,
            "unsupported_resolution_count": unsupported_resolution_count,
            "expected_assertion_miss_count": expected_assertion_miss_count,
            "policy_resolution_count": policy_resolution_count,
            "false_resolution_count": policy_false_resolution,
            "false_resolution_rate": false_resolution_rate,
            "false_resolution_threshold": FALSE_RESOLUTION_THRESHOLD,
            "policy_provenance_pass": policy_provenance_pass,
            "policy_replay_pass": policy_replay_pass,
            "change_semantics_pass": change_semantics_pass,
        },
        "gates": {
            "safety_gate": safety_gate,
            "persistence_gate": persistence_gate,
            "utility_gate": utility_gate,
            "promotion_gate": safety_gate and persistence_gate and utility_gate,
        },
        "claim_limits": {
            "deterministic_fixture_bound": True,
            "provider_modes_are_existing_examples": True,
            "fusion_adapter_is_benchmark_local": True,
            "provider_authority_policy_is_benchmark_local": True,
            "universal_provider_fusion_claim": False,
            "real_world_truth_accuracy_claim": False,
            "production_provider_reliability_claim": False,
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2, sort_keys=True))
