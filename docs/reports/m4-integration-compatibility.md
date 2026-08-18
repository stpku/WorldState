# M4 Integration Compatibility Report

**Status:** IN PROGRESS — AgentReality and GeoTask committed-head parity PASS; Lowa proof remains open
**Date:** 2026-08-19
**Baseline:** M0–M3 frozen WorldState baselines

## Goal

Prove interoperability with the wider stack without moving task semantics, grounding semantics, domain judgment, business writes, or production authority into WorldState.

## WorldState ↔ AgentReality

### Result: committed-head parity PASS

A read-only inspection of the current AgentReality workspace found that AgentReality already owns `packages/adapter-worldstate/` and maps already-resolved WorldState outcomes into grounding signals.

WorldState therefore does **not** add an AgentReality runtime dependency or grounding adapter to Core. Instead, M4 adds a point-in-time fixture:

```text
examples/integrations/agentreality_wire.py
```

It verifies the current transport shape for:

```text
StateAssertion
Unknown
Conflict
ProviderUnavailable
SnapshotRef
```

The fixture explicitly does not contain grounding `disposition` or blocking policy. Those remain AgentReality-owned semantics.

Targeted tests verify:

- assertion fields, UTC validity and JSON thawing;
- evidence/source reference transport;
- explicit Unknown and missing-ref preservation;
- Conflict candidate/evidence preservation with no blocking policy;
- provider outage remains Unknown;
- the compatibility fixture stays outside `src/worldstate`.

Committed-head parity is now pinned as:

```text
WorldState producer vectors:
14ea74e2b8e9a1c75b83581934f588e27da2d147
fixture sha256:
127b8030f58f2d07186980cd95a25863ee49d1db6c21169e82b057e4e8600373

AgentReality consumer parity:
0dd10f85ff949416b1346c2f32f61eea80afa0ed
npm run check: 51/51 PASS
```

The AgentReality test reads an exact hash-pinned copy of the WorldState-produced vectors; the WorldState fixture itself contains no grounding disposition or admission policy.

### Fidelity note

The observed grounding projection is intentionally narrower than a lossless WorldState serialization. It currently omits fields such as `EntityRef.namespace`, `EntityRef.entity_type`, full `Uncertainty`, and `SpatialScope`.

That is acceptable for a minimal grounding transport only if consumers do not treat the projection as a complete WorldState snapshot.

## WorldState → GeoTask

### Result: committed-head provider parity PASS

GeoTask now exposes the v2.1 task-context and provider seams as committed additive contracts. The integration does not bind to the legacy `geotask_runtime.TaskContext`.

WorldState first froze a richer consumer-neutral provider wire because the AgentReality grounding projection is intentionally too narrow for task-relative applicability/resolution work:

```text
WorldState provider-wire baseline:
fe9cc199d2e632122346d1bdffb9ad5ebe375c59

contract:
worldstate.state-query-result / 0.1

producer-vector commit:
8154e40035eae1dfcf7d3697c7537408be95276f

fixture sha256:
19a929ccbdf40c1c216084bc7fefa4f4d3ad7e092439159b174f8aab7788f681
```

The generic wire preserves complete entity identity, validity, provenance, uncertainty and spatial scope while keeping `StateAssertion | Unknown | Conflict` explicit.

GeoTask froze its acquisition seam at:

```text
ContextProvider contract:
a491d5885407bf9a738f2b689cd24e4304d85c5f

WorldState consumer parity:
a537b6e2940e1a184a0a6546bd69e9ae815e2da2
```

The GeoTask-owned adapter lives outside Core and imports no WorldState runtime package. It performs only:

```text
explicit ContextRequirement
      ↓ explicit WorldStateQueryBinding
WorldState state-query-result / 0.1
      ↓ preserve provider-owned payload
ContextCandidate
```

Its committed tests prove that assertion, Unknown, Conflict and provider-unavailable Unknown all survive as provider-owned candidate payloads; no conflict winner, applicability result, resolution judgment or sufficiency result is invented by the adapter.

GeoTask full regression before the consumer checkpoint:

```text
2054 passed, 2 skipped
```

A following additive GeoTask checkpoint also provides deterministic context construction from **already assessed** items and explicitly selected candidates:

```text
e4867e4d5b5bfe342f03e04602e39fa1b3ca7ee7
```

That constructor does not acquire, rank or assess candidates. Therefore the end-to-end ownership remains:

```text
WorldStateProvider / provider wire
      ↓
GeoTask ContextProvider adapter
      ↓
ContextCandidate
      ↓
GeoTask relevance / applicability / resolution assessment
      ↓
explicit assessed items + explicit selection
      ↓
GeoTask TaskContext / SufficiencyAssessment
```

## Lowa → WorldState

### Result: governance ready, implementation deferred

The observed Lowa Architecture Reset matrix explicitly classifies Domain Projection and Integration Adapter as non-writing boundaries.

This matches the required future pattern:

```text
Lowa Business SoR
      ↓ read-only Lowa-owned adapter
WorldState Projection
      ↓
shadow consumers
```

The current Lowa worktree contains concurrent uncommitted refactor changes, so WorldState does not write a cross-project adapter into that workspace in this M4 slice.

## Compatibility evidence

Point-in-time source evidence and SHA pins are recorded in:

```text
docs/compatibility/stack-observation-2026-08-18.md
```

These observations are not a cross-repository contract freeze.

## Validation

WorldState full regression after the general provider wire and committed producer vectors:

```text
63 passed
```

WorldState compile validation:

```text
python3 -m compileall -q src tests examples
PASS
```

GeoTask full regression covering the ContextProvider contract, WorldState consumer adapter and explicit construction seam:

```text
2054 passed, 2 skipped
```

AgentReality current full conformance after both WorldState and GeoTask producer-vector pins:

```text
npm run check -> 61/61 PASS
```

## Decision

### PASS

- WorldState Core remains stack-neutral.
- Consumer-owned AgentReality adapter responsibility is preserved.
- WorldState ↔ AgentReality committed-head producer/consumer parity is frozen on exact commits and fixture SHA.
- WorldState → GeoTask committed-head provider parity is frozen on the general provider wire, exact producer fixture SHA, GeoTask ContextProvider contract, and consumer behavior checkpoint.
- GeoTask receives provider-owned candidate payloads without recomputing WorldState truth or inferring task sufficiency from candidate existence.
- Failure, Unknown and Conflict semantics remain fail-closed across both integration seams.

### REMAINS OPEN

- add a Lowa-owned read-only WorldState shadow adapter only from a clean, migration-safe Lowa checkpoint;
- keep AgentReality shadow-by-default until the wider Promotion Gate is satisfied;
- do not interpret M4 parity as authorization for production replacement.

Therefore **M4 remains IN PROGRESS**, not failed and not prematurely declared complete.
