# Stack Compatibility Observation — 2026-08-18

**Status:** WorldState ↔ AgentReality committed-head parity frozen; GeoTask/Lowa observations remain point-in-time
**WorldState phase:** M4 Integration Compatibility Proofs

## Purpose

Record the actual interfaces observed in the sibling repositories before writing any cross-project adapter in WorldState.

The evidence below is deliberately read-only. All three sibling workspaces contained uncommitted or evolving work at observation time, so their current file shapes MUST NOT be treated as stable public APIs merely because a compatibility fixture can be made to match them today.

## Observed repositories

| Project | Observed branch state | Evidence | Observation |
|---|---|---|---|
| AgentReality | `main...origin/main`, working tree modified | `packages/adapter-worldstate/src/index.ts`, SHA-256 `fa45027763922e4cb0498bcccf3bb1825ee7889803b49da518059a38fb7627cb` | AgentReality already owns a provider-side `adapter-worldstate`; WorldState must not duplicate grounding policy |
| AgentReality | same | `packages/adapter-worldstate/README.md`, SHA-256 `32fa0d92f1460584f148344b9d62ddf76ff2416dc45f689836880ea45083b00e` | Adapter maps already-resolved WorldState semantics and explicitly forbids world-state resolution inside AgentReality |
| GeoTask | `main...origin/main`, untracked strategic work present | `src/geotask_runtime/contracts.py`, SHA-256 `762b36e81484f9d085ab6ab0d09087b630fc54ab2cee7a33ea267e84620f2599` | Current checked-out runtime exposes a legacy `TaskContext` but not the target v2.1 `ContextProvider` / explicit sufficiency contract |
| Lowa | `master...origin/master [ahead 9]`, working tree modified | `docs/refactor/lowa_architecture_reset_v1/read_write_responsibility_matrix.md`, SHA-256 `95b50920c03e8bcceb04e34ff4de978ff149378ef1332d9f99df90c430a28fe7` | Domain Projection and Integration Adapter are explicitly read-only with respect to Lowa business state |

## AgentReality compatibility

The observed AgentReality adapter accepts a provider-neutral projection of:

```text
StateAssertion
  assertionId
  entityId
  propertyKey
  value
  epistemicMode
  validity
  version
  evidenceRefs
  sourceRefs

Unknown
  unknownId
  reason
  asOf
  missing?

Conflict
  conflictId
  reason
  asOf
  candidateRefs
  evidenceRefs
```

Its ownership rule is correct for the target architecture:

```text
WorldState resolves truth
        ↓ already-resolved result
AgentReality adapter maps transport
        ↓
AgentReality evaluates grounding
```

Observed behavior:

```text
StateAssertion       -> grounding disposition ok
Unknown              -> unknown
Conflict             -> unknown by default
ProviderUnavailable  -> unknown
```

A conflict becomes `blocked` only through explicit integration policy. WorldState does not emit that grounding decision.

WorldState M4 therefore provides only a point-in-time wire fixture in:

> `examples/integrations/agentreality_wire.py`

It is intentionally outside `src/worldstate` and pins the observed AgentReality adapter source SHA. It is not a production adapter.

### Committed-head parity update — 2026-08-19

The producer and consumer are now both clean committed checkpoints:

```text
WorldState producer-vector commit:
14ea74e2b8e9a1c75b83581934f588e27da2d147

WorldState fixture sha256:
127b8030f58f2d07186980cd95a25863ee49d1db6c21169e82b057e4e8600373

AgentReality consumer parity commit:
0dd10f85ff949416b1346c2f32f61eea80afa0ed

AgentReality verification:
npm run check -> 51/51 PASS
```

AgentReality keeps an exact SHA-pinned copy of the WorldState producer vectors and tests `StateAssertion`, `Unknown`, and `Conflict` through its own `adapter-worldstate`. No runtime SDK dependency is introduced in either direction.

This closes the committed-head **Contract + Behavior Parity** evidence for the WorldState ↔ AgentReality transport seam. It does not promote AgentReality out of shadow mode and does not authorize a production cutover.

### Fidelity notes

The current AgentReality projection is deliberately narrower than the complete WorldState model. For example, it does not currently transport `EntityRef.namespace`, `EntityRef.entity_type`, full `Uncertainty`, or `SpatialScope` in the assertion projection.

This is not automatically a defect because AgentReality grounding may not need those fields. It does mean the projection MUST be treated as a grounding transport view rather than a lossless WorldState serialization format.

## GeoTask compatibility

The currently checked-out GeoTask runtime contract contains a legacy `TaskContext` with:

```text
local_objects
available_operators
available_data_sources
domain_rules
known_gaps
```

That shape does not express the target strategic semantics frozen for GeoTask:

```text
ContextRequirement
ContextAssessment
TaskContext
ContextGap
SufficiencyAssessment
ContextConstructionTrace
```

Therefore WorldState MUST NOT bind a new M4 adapter to the legacy `TaskContext` merely to claim integration completion.

The correct future direction remains:

```text
WorldStateProvider
      ↓
GeoTask-owned ContextProvider / source adapter
      ↓
GeoTask relevance / applicability / resolution / sufficiency
```

WorldState supplies state; GeoTask owns task relevance and sufficiency.

## Lowa compatibility

The current Lowa Architecture Reset read/write matrix freezes:

```text
Domain Projection   may read = yes   may mutate business state = no
Integration Adapter may read = bounded   may mutate business state = no
```

Therefore a future Lowa integration should be implemented as:

```text
Lowa authoritative Business SoR
        ↓ read-only Lowa-owned adapter
WorldState Projection
```

not:

```text
WorldState
        ↓ write
Lowa business database
```

No WorldState code is added to the currently modified Lowa workspace during this observation.

## M4 decision

### PASS now

- Core remains free of AgentReality / GeoTask / Lowa imports.
- WorldState ↔ AgentReality committed-head producer/consumer vectors pass cross-repository parity.
- `Unknown`, `Conflict`, validity and provenance references survive the compatibility boundary.
- Provider unavailability remains explicit `Unknown`, never a positive state.
- Consumer-owned adapter responsibility is preserved.

### Not yet promoted

- GeoTask target `ContextProvider` / explicit sufficiency seam is not yet present in the observed checked-out runtime contract.
- No Lowa-specific WorldState projection is implemented until the Lowa shadow slice is intentionally scheduled against a clean migration-safe checkpoint.
- AgentReality remains shadow-by-default; committed-head parity is evidence for a gate, not promotion itself.

## Rule

> **Observe current contracts, prove compatibility in fixtures, freeze only after both sides have stable checkpoints.**

This keeps M4 aligned with Contract → Adapter → Shadow → Parity → Promotion rather than turning an uncommitted worktree shape into architecture by accident.
