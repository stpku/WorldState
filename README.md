# WorldState

> **What is true about the world?**

WorldState is an open, lightweight, domain-neutral foundation for representing **evidence-grounded world state** as explicit, traceable, replayable state.

It turns observations, evidence, authoritative records, and external providers into a `WorldStateSnapshot` without hiding uncertainty, unknowns, conflicts, provenance, or temporal validity.

## Status

**M4 — Integration Compatibility Proofs**

M0 contracts, the M1 deterministic reference engine, M2 native/projection/external-provider parity, and M3 cross-domain generalization are frozen baselines. The current phase proves thin interoperability with the wider stack while keeping production adapters consumer-owned and keeping GeoTask, AgentReality, Lowa, Harness, and domain dependencies out of WorldState Core.

## Core idea

```text
Observation
   ↓
Evidence
   ↓
StateAssertion
   ↓
Validity + Provenance
   ↓
Unknown / Conflict Preservation
   ↓
WorldStateSnapshot
```

WorldState distinguishes state by epistemic mode:

```text
observed
inferred
predicted
simulated
```

These modes are not interchangeable.

## Core objects

The initial public semantic surface is deliberately small:

```text
Entity
Observation
Source
Evidence
Claim
StateAssertion
Relation
SpatialScope
TemporalScope
Validity
Provenance
Uncertainty
Unknown
Conflict
WorldStateSnapshot
StateTransition
Version
```

## Provider contract

The long-term interoperability seam is `WorldStateProvider`:

```python
get_snapshot(scope, time) -> WorldStateSnapshot
query_state(entity, property, time) -> StateQueryResult
query_relation(subject, relation, object, time) -> StateQueryResult
get_evidence(state_ref) -> EvidenceSet
get_unknowns(scope) -> tuple[Unknown, ...]
get_conflicts(scope) -> tuple[Conflict, ...]
get_history(entity, interval) -> tuple[StateTransition, ...]
```

`StateQueryResult` is the explicit union `StateAssertion | Unknown | Conflict`. The mandatory provider contract is synchronous. Change subscriptions belong to the separate optional `WorldStateChangeProvider` seam and MUST NOT force an event-platform dependency into Core.

For cross-process and cross-repository consumers, WorldState also publishes a consumer-neutral JSON-safe provider wire:

```text
worldstate.state-query-result / 0.1
worldstate.snapshot           / 0.1
```

The general wire preserves complete entity identity, validity, provenance, uncertainty and spatial scope while keeping `StateAssertion`, `Unknown` and `Conflict` distinct. It contains no GeoTask applicability/sufficiency, AgentReality grounding/admission, or Lowa business authorization semantics. See [`docs/specification/worldstate-provider-wire-v0.1.md`](docs/specification/worldstate-provider-wire-v0.1.md).

## Three deployment modes

WorldState semantics do not require WorldState to own the authoritative database.

### Native State Store

```text
Observation → WorldState persistence → Snapshot
```

### Projection

```text
Existing Business System of Record → Adapter → WorldState Projection
```

This is the preferred migration pattern for an existing domain product such as Lowa.

### External Provider

```text
GIS / Digital Twin / GSTAR / another world model → WorldStateProvider
```

An external provider may conform to the contract without using the WorldState reference engine.

## Non-goals

WorldState is **not**:

- an Agent runtime or Harness;
- a task-context engine;
- a domain decision engine;
- an authorization system;
- a generic workflow platform;
- a mandatory database;
- a mandatory knowledge graph;
- a Digital Twin product;
- a replacement for an existing System of Record simply because it owns world-state semantics.

In particular:

> **WorldState does not know the Task.**

Task relevance, applicability, resolution adequacy, context sufficiency, and context construction belong outside WorldState.

## Quality model

North Star:

> **Truth Fidelity**

Initial metrics:

- State Correctness
- Freshness
- Provenance Coverage
- Unknown Fidelity
- Conflict Preservation
- Validity Accuracy
- Replayability

Counter-metric:

> **Unsupported State Rate**

Coverage MUST NOT be improved by silently converting `Unknown` or unresolved `Conflict` into a positive assertion.

## Repository shape

```text
src/worldstate/        Core contracts and reference engine
tests/                 Invariants, conformance, replay tests
docs/specification/    Normative project specifications
docs/architecture/     Architecture Decision Records
docs/roadmap/          Milestones and proof plan
examples/               Domain-neutral examples
```

## Initial milestones

- **M0 — Contract & Semantic Foundation**: freeze objects, invariants, provider protocol, deterministic identity rules.
- **M1 — Reference Resolution Engine**: deterministic in-memory resolution preserving unknown/conflict/provenance.
- **M2 — Projection & Provider Conformance**: prove native, projection, and external-provider modes.
- **M3 — Cross-domain Generalization**: at least two unrelated examples without Core changes.
- **M4 — Integration Proofs**: optional GeoTask/Lowa/AgentReality adapters outside Core, after independent foundation proof.

## Architecture principle

```text
Define semantics first.
Keep uncertainty explicit.
Preserve provenance.
Make history replayable.
Own truth semantics, not every database.
```

See [`docs/specification/worldstate-core-v0.1.md`](docs/specification/worldstate-core-v0.1.md) for the first normative design.
