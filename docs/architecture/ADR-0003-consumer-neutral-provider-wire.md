# ADR-0003 — WorldState Publishes a Consumer-Neutral Provider Wire

**Status:** Accepted
**Date:** 2026-08-19
**Strategic authority:** AgentReality Stack Strategic Architecture Specification v2.1

## Context

WorldState already has stable Python semantic contracts and a narrower point-in-time projection used to prove AgentReality grounding compatibility.

That grounding projection is intentionally minimal. It does not transport every WorldState field because AgentReality does not need every field to decide runtime grounding.

GeoTask has a different responsibility. It may need entity identity, scope, validity, uncertainty, and provenance to assess task-relative relevance, applicability, and resolution adequacy.

Therefore reusing the grounding-only transport as the generic WorldState provider API would create a false architectural shortcut:

```text
Grounding transport
≠
General WorldState provider contract
```

## Decision

WorldState publishes a consumer-neutral JSON-safe provider wire with version:

```text
0.1
```

Contract identifiers:

```text
worldstate.state-query-result
worldstate.snapshot
```

The canonical serializers are:

```python
state_query_result_payload(result)
snapshot_payload(snapshot)
```

The general query-result wire preserves:

- `StateAssertion | Unknown | Conflict` as distinct first-class kinds;
- full `EntityRef` identity including `entity_type` and `namespace`;
- property key and value;
- epistemic mode;
- complete validity including `resolved_at`, `valid_from`, `valid_until`, and `superseded_by`;
- provenance evidence/source/parent assertion references, method, and resolver;
- uncertainty confidence/method/reason/metadata;
- spatial scope kind/reference/bbox/metadata;
- Unknown missing references and metadata;
- Conflict candidate/evidence references and metadata.

The snapshot wire preserves all first-class result kinds plus snapshot scope and source versions.

## Consumer neutrality

The provider wire MUST NOT contain:

- GeoTask requirement IDs, applicability conclusions, resolution adequacy, or sufficiency;
- AgentReality grounding disposition, admission, or Harness policy;
- Lowa scoring, authorization, review, or report semantics.

WorldState serializes its own already-resolved semantics only.

## Time representation

UTC datetimes are rendered as RFC 3339 `Z` values while preserving available microsecond precision.

This avoids silently reducing temporal resolution merely to match a narrower downstream transport.

## Relationship to AgentReality adapter

The existing AgentReality wire fixture remains valid as a narrower consumer-owned projection:

```text
WorldState general provider wire
        ├── GeoTask may consume rich provider semantics
        └── AgentReality adapter may consume a narrower grounding projection
```

The existence of a richer provider wire does not require AgentReality to ingest fields it does not need.

## Relationship to GeoTask

A GeoTask-owned `ContextProvider` adapter may consume this wire and wrap the provider-owned payload as `ContextCandidate` without interpreting assertion/unknown/conflict truth semantics.

GeoTask then remains responsible for task-relative:

- relevance;
- applicability;
- resolution adequacy;
- context construction;
- sufficiency.

## Consequences

### Positive

- downstream systems can integrate without importing the Python WorldState runtime;
- a consumer does not have to depend on another consumer's projection format;
- WorldState scope/uncertainty/provenance are not lost before GeoTask assessment;
- `Unknown` and `Conflict` remain explicit across process/repository boundaries.

### Deliberately excluded

This ADR does not create:

- HTTP/gRPC service protocols;
- event streaming;
- schema registry infrastructure;
- task/context policy;
- grounding policy;
- domain-specific adapters in Core.

Those remain separate layers and gates.
