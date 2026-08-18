# WorldState Provider Wire Contract v0.1

**Status:** Normative Contract Freeze Candidate
**Date:** 2026-08-19
**Strategic authority:** AgentReality Stack Strategic Architecture Specification v2.1
**Architecture decision:** `docs/architecture/ADR-0003-consumer-neutral-provider-wire.md`

## 0. Purpose

This specification defines the consumer-neutral JSON-safe wire representation of WorldState public semantics.

It exists so a downstream system can consume already-resolved WorldState outcomes without importing the Python runtime and without depending on another consumer's narrower adapter projection.

The core invariant is:

```text
WorldState semantic result
        ↓
consumer-neutral provider wire
        ↓
consumer-owned task / grounding / domain interpretation
```

The wire serializes WorldState semantics only. It does not add Task, Grounding, or Domain Decision semantics.

## 1. Version and contract identifiers

Wire version:

```text
0.1
```

Contract identifiers:

```text
worldstate.state-query-result
worldstate.snapshot
```

Public serializers:

```python
state_query_result_payload(result)
snapshot_payload(snapshot)
```

Supporting serializers:

```python
entity_ref_payload(entity)
spatial_scope_payload(scope)
validity_payload(validity)
provenance_payload(provenance)
uncertainty_payload(uncertainty)
```

## 2. StateQueryResult wire

`StateQueryResult` remains the explicit union:

```text
StateAssertion | Unknown | Conflict
```

The wire MUST preserve these as distinct `kind` values. A serializer or adapter MUST NOT flatten `Unknown` or `Conflict` into an assertion merely to simplify downstream consumption.

### 2.1 StateAssertion

```json
{
  "contract": "worldstate.state-query-result",
  "contract_version": "0.1",
  "kind": "assertion",
  "assertion_id": "state-...",
  "entity": {
    "entity_id": "...",
    "entity_type": "...",
    "namespace": "..."
  },
  "property_key": "...",
  "value": {},
  "epistemic_mode": "observed",
  "validity": {
    "resolved_at": "...Z",
    "valid_from": "...Z",
    "valid_until": "...Z",
    "superseded_by": null
  },
  "provenance": {
    "evidence_refs": [],
    "source_refs": [],
    "parent_assertion_refs": [],
    "method": "...",
    "resolver": "..."
  },
  "version": "0.1",
  "uncertainty": null,
  "spatial_scope": null
}
```

The assertion wire preserves:

- full entity identity;
- JSON-safe value;
- epistemic mode;
- full validity window;
- provenance and resolver lineage;
- optional uncertainty;
- optional spatial scope.

### 2.2 Unknown

```json
{
  "contract": "worldstate.state-query-result",
  "contract_version": "0.1",
  "kind": "unknown",
  "unknown_id": "unknown-...",
  "reason": "insufficient_evidence",
  "as_of": "...Z",
  "entity": null,
  "property_key": null,
  "missing": [],
  "metadata": {}
}
```

`Unknown` is a positive statement about epistemic insufficiency. It is not equivalent to `false`, `empty`, or an assertion with a null value.

### 2.3 Conflict

```json
{
  "contract": "worldstate.state-query-result",
  "contract_version": "0.1",
  "kind": "conflict",
  "conflict_id": "conflict-...",
  "entity": {
    "entity_id": "...",
    "entity_type": null,
    "namespace": null
  },
  "property_key": "...",
  "candidate_refs": ["claim-a", "claim-b"],
  "evidence_refs": ["evidence-a", "evidence-b"],
  "reason": "materially incompatible claims",
  "as_of": "...Z",
  "metadata": {}
}
```

The wire MUST NOT add a `winner`, `selected`, `preferred`, `blocked`, or equivalent field. Conflict resolution and task policy remain outside this serializer.

## 3. EntityRef

The general provider wire preserves the complete public entity reference:

```text
entity_id
entity_type
namespace
```

This differs intentionally from narrower consumer projections that may need only `entity_id`.

## 4. Validity

Validity is serialized as:

```text
resolved_at
valid_from
valid_until
superseded_by
```

All WorldState Core datetimes are UTC. The provider wire renders them using RFC 3339 `Z` notation.

Available microsecond precision MUST be preserved. A generic provider wire MUST NOT truncate timestamps merely to match one consumer's transport format.

## 5. Provenance

Provenance is serialized as:

```text
evidence_refs
source_refs
parent_assertion_refs
method
resolver
```

Downstream consumers may use these references for traceability, applicability assessment, source inspection, or audit. The wire does not interpret them.

## 6. Uncertainty

Optional uncertainty is serialized as:

```text
confidence
method
reason
metadata
```

WorldState does not convert uncertainty into task sufficiency, grounding admission, or business authorization.

## 7. SpatialScope

Optional spatial scope is serialized as:

```text
kind
reference
bbox
metadata
```

The generic wire preserves scope information so a task-context consumer such as GeoTask may later assess applicability or resolution adequacy.

The wire does not perform geometry operations or spatial relevance decisions.

## 8. Snapshot wire

`WorldStateSnapshot` is serialized under:

```text
worldstate.snapshot / 0.1
```

Payload:

```text
snapshot_id
as_of
created_at
version
scope
assertions[]
unknowns[]
conflicts[]
source_versions{}
```

Each nested result is serialized using the same `worldstate.state-query-result / 0.1` contract.

Snapshot result ordering remains canonical because the underlying snapshot contract already sorts stable semantic IDs.

## 9. Consumer neutrality

The provider wire MUST NOT contain GeoTask-owned fields such as:

```text
requirement_id
applicability
resolution_adequacy
sufficiency
context_gap
```

It MUST NOT contain AgentReality-owned fields such as:

```text
disposition
admission
grounding_status
requirementId
```

It MUST NOT contain Lowa-owned fields such as:

```text
score
authorization
review_status
report_publication
```

A consumer wraps or translates the WorldState payload at its own boundary.

## 10. Relationship to AgentReality grounding projection

The existing AgentReality compatibility projection remains deliberately narrower.

```text
General WorldState provider wire
    preserves rich WorldState semantics

AgentReality grounding projection
    carries only fields required by grounding transport
```

Neither replaces the other.

## 11. Relationship to GeoTask ContextProvider

GeoTask may implement a consumer-owned adapter:

```text
WorldState provider wire
      ↓
GeoTask ContextProvider adapter
      ↓
ContextCandidate.payload
```

The adapter SHOULD preserve the complete WorldState result payload as provider-owned candidate information.

It MUST NOT:

- choose a conflict winner;
- reinterpret `Unknown` as a positive assertion;
- decide applicability because an assertion exists;
- decide task sufficiency because a candidate exists.

GeoTask remains responsible for task-relative relevance, applicability, resolution adequacy, context construction, and sufficiency.

## 12. Compatibility rule

A consumer that pins this contract SHOULD record:

- WorldState contract version;
- producer commit;
- producer fixture path;
- producer fixture SHA-256.

Cross-repository promotion SHOULD be based on committed producer vectors rather than floating branch state or hand-authored approximations.

## 13. Non-goals

This contract does not define:

- HTTP endpoints;
- gRPC services;
- event streams;
- provider discovery;
- consumer retries;
- GeoTask relevance/applicability/resolution/sufficiency algorithms;
- AgentReality grounding policy;
- Lowa domain authorization;
- storage or deployment topology.

## 14. Exit gate

The wire contract is ready for M4 provider integration proof when:

```text
1. StateAssertion / Unknown / Conflict round-trip as distinct provider-owned kinds.
2. Entity identity, validity, provenance, uncertainty, and spatial scope are preserved.
3. Wire payloads are JSON serializable and deterministic for the same semantic input.
4. Core contains no consumer runtime dependency.
5. A downstream consumer can wrap the payload without changing WorldState truth semantics.
```
