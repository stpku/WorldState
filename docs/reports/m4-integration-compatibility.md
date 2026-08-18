# M4 Integration Compatibility Report

**Status:** IN PROGRESS — WorldState-side compatibility slice PASS
**Date:** 2026-08-18
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
6 passed
```

Full repository regression after publishing committed producer vectors:

```text
52 passed
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
- WorldState ↔ AgentReality committed-head producer/consumer parity is frozen on exact commits and fixture SHA.
- Current WorldState results are mapped without recomputing truth.
- Failure, Unknown and Conflict semantics remain fail-closed.

### REMAINS OPEN

- integrate with GeoTask only after its target explicit sufficiency/provider seam is stable;
- add a Lowa-owned read-only WorldState shadow adapter only from a clean, migration-safe Lowa checkpoint;
- keep AgentReality shadow-by-default until the wider Promotion Gate is satisfied.

Therefore **M4 remains IN PROGRESS**, not failed and not prematurely declared complete.
