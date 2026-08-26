# WorldState Conflict Resolution Policy v0.1

**Status:** M6 Foundation Contract
**Scope:** explicit conflict-resolution policy seam only

## Purpose

WorldState's default reference resolver remains conservative:

```text
agreement        → StateAssertion
missing support  → Unknown
disagreement     → Conflict
```

M6 adds an optional, explicit policy seam for cases where a consumer or deployment has a justified resolution policy. It does not add an implicit global source ranking.

## Contract

```text
Conflict
+ exact candidate Claim set
+ ConflictResolutionPolicy
        ↓
ConflictResolutionDecision
        ↓
StateAssertion OR original Conflict
```

Public objects:

- `ConflictResolutionPolicy`
- `ConflictResolutionDecision`
- `ConflictResolutionResult`
- `apply_conflict_resolution_policy(...)`
- `conflict_resolution_decision_payload(...)`

Contract version:

```text
0.1
```

## Required invariants

```text
Conflict ≠ value-selection inconvenience
No explicit policy ≠ implicit resolution
Higher confidence ≠ automatic truth
Newer claim ≠ automatic truth
Policy decision ≠ permission to invent a value
Resolved value must be one existing conflict candidate
Policy resolution must preserve conflict time boundary
Policy identity/version must be explicit
Decision lineage must bind conflict + policy
```

The supplied claim set must exactly cover `Conflict.candidate_refs`. A caller cannot hide one disagreeing candidate before applying a policy.

## Resolution provenance

A successful policy resolution returns both:

1. the `ConflictResolutionDecision`; and
2. the resulting `StateAssertion`.

The decision records:

```text
decision_id
conflict_id
policy_ref
policy_version
decided_at
status
selected_claim_ref
reason
source_refs
```

The resulting assertion records the policy identity in `provenance.resolver` and binds the decision ID in `provenance.method`. Evidence and source references from all conflicting candidates are retained rather than keeping only the selected candidate's provenance.

## Preserve is a valid outcome

A policy may return:

```text
status = preserved
selected_claim_ref = null
```

In that case the original `Conflict` remains the state outcome. A policy is not required to manufacture a resolution.

## Unknown transitions

M6 does not redefine `Unknown`. The existing conservative resolver already supports:

```text
missing evidence
→ Unknown

required evidence later becomes available
→ StateAssertion
```

The M6 benchmark explicitly verifies this transition.

## Benchmark gate

`benchmarks/m6_unknown_conflict_fidelity/` freezes:

```text
Useful State Coverage
↔ False Resolution Rate
↔ Conflict Preservation Rate
↔ Unknown Preservation Rate
↔ Policy Provenance Coverage
```

Frozen safety threshold:

```text
False Resolution Rate = 0
```

A policy that raises assertion coverage while selecting the wrong value fails the safety gate.

## Non-goals

v0.1 does not define:

- a universal source-authority hierarchy;
- confidence-weighted truth ranking;
- latest-write-wins truth;
- task relevance or sufficiency;
- production authorization;
- distributed conflict-resolution workflow;
- human adjudication UI;
- provider-wire changes;
- real-world truth accuracy claims.

Policy meaning remains deployment/domain owned. WorldState owns the explicit resolution semantics and audit boundary, not the business rule that declares one real source authoritative.
