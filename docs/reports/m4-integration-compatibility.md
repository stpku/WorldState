# M4 Integration Compatibility Report

**Status:** IN PROGRESS — WorldState-side compatibility slice PASS
**Date:** 2026-08-18
**Baseline:** M0–M3 frozen WorldState baselines

## Goal

Prove interoperability with the wider stack without moving task semantics, grounding semantics, domain judgment, business writes, or production authority into WorldState.

## WorldState ↔ AgentReality

### Result: compatibility fixture PASS

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

### Fidelity note

The observed grounding projection is intentionally narrower than a lossless WorldState serialization. It currently omits fields such as `EntityRef.namespace`, `EntityRef.entity_type`, full `Uncertainty`, and `SpatialScope`.

That is acceptable for a minimal grounding transport only if consumers do not treat the projection as a complete WorldState snapshot.

## WorldState → GeoTask

### Result: deferred pending target contract checkpoint

The checked-out GeoTask runtime currently exposes a legacy `TaskContext` containing local objects, operators, data sources, domain rules and known gaps. It does not yet expose the target v2.1 `ContextProvider` / explicit `SufficiencyAssessment` seam in the observed runtime code.

WorldState therefore refuses to implement a new adapter against the legacy shape merely to claim M4 completion.

The future ownership remains:

```text
WorldStateProvider
      ↓
GeoTask-owned source / ContextProvider adapter
      ↓
GeoTask relevance, applicability, resolution adequacy and sufficiency
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

M4 targeted WorldState compatibility tests:

```text
5 passed
```

Full repository regression after the M4 compatibility slice:

```text
51 passed
```

Compile validation:

```text
python3 -m compileall -q src tests examples
PASS
```

## Decision

### PASS

- WorldState Core remains stack-neutral.
- Consumer-owned AgentReality adapter responsibility is preserved.
- Current WorldState results can be projected into the observed AgentReality transport shape without recomputing truth.
- Failure, Unknown and Conflict semantics remain fail-closed.

### REMAINS OPEN

- freeze a stable cross-repository AgentReality compatibility checkpoint on committed heads;
- integrate with GeoTask only after its target explicit sufficiency/provider seam is stable;
- add a Lowa-owned read-only WorldState shadow adapter only from a clean, migration-safe Lowa checkpoint;
- run cross-repository parity tests before any promotion.

Therefore **M4 remains IN PROGRESS**, not failed and not prematurely declared complete.
