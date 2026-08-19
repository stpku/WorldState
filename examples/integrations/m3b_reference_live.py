"""Deterministic live-reference WorldState producer for cross-repository M3B-0 evidence.

This integration-only executable exercises the actual ``InMemoryWorldState`` and
``ReferenceResolver`` path, then emits the consumer-neutral provider wire. It
uses an explicit caller-supplied timestamp and never imports GeoTask,
AgentReality, a Harness, or domain product code.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json

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
from worldstate.wire import state_query_result_payload

SCENARIOS = ("supported", "unknown", "conflict")
ENTITY = EntityRef(
    entity_id="reference-asset-1",
    entity_type="reference_asset",
    namespace="example://m3b-reference-live",
)
PROPERTY_KEY = "operational_status"


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of must include a timezone offset")
    return parsed


def _source(source_id: str) -> Source:
    return Source(
        source_id=source_id,
        source_type="m3b-reference-live",
        version="0.1",
    )


def _evidence(evidence_id: str, source: Source, *, as_of: datetime) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source=source,
        recorded_at=as_of - timedelta(minutes=2),
    )


def _claim(
    claim_id: str,
    value: str,
    evidence_id: str,
    source: Source,
    *,
    as_of: datetime,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        entity=ENTITY,
        property_key=PROPERTY_KEY,
        value=value,
        epistemic_mode=EpistemicMode.OBSERVED,
        provenance=Provenance(
            evidence_refs=(evidence_id,),
            source_refs=(source.source_id,),
            method="m3b-reference-observation",
        ),
        created_at=as_of - timedelta(minutes=1),
        temporal_scope=TemporalScope(
            start=as_of - timedelta(minutes=5),
            end=as_of + timedelta(minutes=10),
        ),
    )


def build_projection(scenario: str, as_of: str) -> dict[str, object]:
    """Run one exact-time reference-provider scenario and return provider wire."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of: {', '.join(SCENARIOS)}")

    at = _parse_timestamp(as_of)
    provider = InMemoryWorldState()

    if scenario == "supported":
        source = _source("source-reference-a")
        provider.add_evidence(_evidence("evidence-reference-a", source, as_of=at))
        provider.add_claim(
            _claim(
                "claim-reference-a",
                "ready",
                "evidence-reference-a",
                source,
                as_of=at,
            )
        )
    elif scenario == "conflict":
        source_a = _source("source-reference-a")
        source_b = _source("source-reference-b")
        provider.add_evidence(_evidence("evidence-reference-a", source_a, as_of=at))
        provider.add_evidence(_evidence("evidence-reference-b", source_b, as_of=at))
        provider.add_claim(
            _claim(
                "claim-reference-a",
                "ready",
                "evidence-reference-a",
                source_a,
                as_of=at,
            )
        )
        provider.add_claim(
            _claim(
                "claim-reference-b",
                "closed",
                "evidence-reference-b",
                source_b,
                as_of=at,
            )
        )

    result = provider.query_state(ENTITY, PROPERTY_KEY, at)
    return state_query_result_payload(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    payload = build_projection(args.scenario, args.as_of)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
