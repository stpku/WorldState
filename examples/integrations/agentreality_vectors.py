from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from examples.integrations.agentreality_wire import (
    project_query_result_for_agentreality,
    snapshot_ref,
)
from worldstate import (
    Claim,
    EntityRef,
    EpistemicMode,
    Evidence,
    InMemoryWorldState,
    Provenance,
    Source,
    TemporalScope,
)

WORLDSTATE_CONTRACT_BASELINE = "24e8a6888097df6f9ea2a9f9a04375c236e45454"
VECTOR_SCHEMA = "worldstate.agentreality.projection-v1"
AT = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)
ENTITY = EntityRef("thing-1", entity_type="example", namespace="cross-repo-vector")


def build_vectors() -> dict[str, object]:
    """Build deterministic producer-side transport vectors for AgentReality.

    The vectors contain only WorldState-owned projected outcomes. They do not
    encode grounding dispositions, admission decisions, or AgentReality policy.
    """
    assertion_provider = InMemoryWorldState()
    source = Source(source_id="source-a", source_type="example", version="v1")
    evidence = Evidence(
        evidence_id="evidence-a",
        source=source,
        recorded_at=AT - timedelta(minutes=2),
    )
    assertion_provider.add_evidence(evidence)
    assertion_provider.add_claim(
        Claim(
            claim_id="claim-a",
            entity=ENTITY,
            property_key="status",
            value={"state": "open", "sequence": [1, 2]},
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=(evidence.evidence_id,),
                source_refs=(source.source_id,),
                method="direct-observation",
            ),
            created_at=AT - timedelta(minutes=1),
            temporal_scope=TemporalScope(
                start=AT - timedelta(minutes=10),
                end=AT + timedelta(minutes=10),
            ),
        )
    )
    assertion = assertion_provider.query_state(ENTITY, "status", AT)
    assertion_snapshot = assertion_provider.get_snapshot(None, AT)

    unknown_provider = InMemoryWorldState()
    unknown_provider.add_claim(
        Claim(
            claim_id="claim-missing-evidence",
            entity=ENTITY,
            property_key="status",
            value="open",
            epistemic_mode=EpistemicMode.OBSERVED,
            provenance=Provenance(
                evidence_refs=("missing-evidence",),
                source_refs=(),
                method="direct-observation",
            ),
            created_at=AT - timedelta(minutes=1),
        )
    )
    unknown = unknown_provider.query_state(ENTITY, "status", AT)

    conflict_provider = InMemoryWorldState()
    for suffix, value in (("a", "open"), ("b", "closed")):
        conflict_source = Source(
            source_id=f"source-{suffix}",
            source_type="example",
            version="v1",
        )
        conflict_evidence = Evidence(
            evidence_id=f"evidence-{suffix}",
            source=conflict_source,
            recorded_at=AT - timedelta(minutes=2),
        )
        conflict_provider.add_evidence(conflict_evidence)
        conflict_provider.add_claim(
            Claim(
                claim_id=f"claim-{suffix}",
                entity=ENTITY,
                property_key="status",
                value=value,
                epistemic_mode=EpistemicMode.OBSERVED,
                provenance=Provenance(
                    evidence_refs=(conflict_evidence.evidence_id,),
                    source_refs=(conflict_source.source_id,),
                    method="direct-observation",
                ),
                created_at=AT - timedelta(minutes=1),
            )
        )
    conflict = conflict_provider.query_state(ENTITY, "status", AT)

    return {
        "schema": VECTOR_SCHEMA,
        "worldstateContractBaseline": WORLDSTATE_CONTRACT_BASELINE,
        "vectors": [
            {
                "name": "assertion",
                "snapshotRef": snapshot_ref(assertion_snapshot.snapshot_id),
                "projection": project_query_result_for_agentreality(assertion),
            },
            {
                "name": "unknown_insufficient_evidence",
                "projection": project_query_result_for_agentreality(unknown),
            },
            {
                "name": "conflict",
                "projection": project_query_result_for_agentreality(conflict),
            },
        ],
    }


def canonical_vectors_json() -> str:
    return json.dumps(
        build_vectors(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> None:
    destination = Path(__file__).with_name("agentreality_vectors.json")
    destination.write_text(canonical_vectors_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
