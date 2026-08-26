# M6b Provider Disagreement & Conflict Persistence Benchmark v0.1

## Purpose

M6b connects existing WorldState provider implementations to the M5 change semantics and M6 Unknown / Conflict fidelity semantics.

It asks a narrower question than general provider quality:

> When independent provider modes disagree about the same proposition, does WorldState preserve that disagreement across time and version change until the evidence actually converges or an explicit auditable policy is applied?

The benchmark uses the repository's existing provider implementations:

```text
InMemoryWorldState
ProjectionWorldStateProvider
DirectExternalWorldStateProvider
```

No Core provider implementation is added for this benchmark.

## Benchmark-local fusion adapter

Each provider is queried independently for the same entity/property/time boundary. Its `StateAssertion` is converted into a new fusion `Claim` that retains:

- provider-mode lineage;
- original evidence references;
- original source references;
- parent assertion reference;
- value and epistemic mode.

The fusion adapter then calls the existing conservative `ReferenceResolver`.

```text
Native assertion
Projection assertion
Direct External assertion
        ↓
benchmark-local Claim projection
        ↓
ReferenceResolver
        ↓
Assertion / Unknown / Conflict
```

This adapter is benchmark-local. M6b does **not** introduce a universal multi-provider fusion API into Core.

## Frozen temporal sequence

### t0

```text
native          open
projection      closed
direct-external open
        ↓
Conflict
```

### t1

Provider versions change, but the material disagreement remains:

```text
native          open
projection      closed
direct-external open
        ↓
Conflict
```

M5 delta:

```text
t0 Conflict → t1 Conflict
= CONFLICT_CHANGED
```

### t2

All three provider modes converge:

```text
native          closed
projection      closed
direct-external closed
        ↓
StateAssertion(closed)
```

M5 delta:

```text
t1 Conflict → t2 Assertion
= CONFLICT_RESOLVED
```

## Explicit policy replay

At t1 the raw fused outcome remains `Conflict`.

A separate benchmark-local provider-mode priority policy is then applied:

```text
projection
> direct-external
> native
```

The policy selects the existing projection-backed conflict candidate and produces:

```text
outcome value   closed
policy reason   explicit provider-mode priority selected provider://projection
```

The following are replay-stable:

- `ConflictResolutionDecision`;
- decision ID;
- selected claim;
- policy reason;
- resulting assertion;
- policy provenance.

The policy does not change the raw provider-fusion state. It is an explicit alternative resolution path over the already-materialized Conflict.

## Frozen metrics

```text
Provider modes                         3
Provider Mode Coverage Rate       100.00%
Epochs                                 3
Expected Conflict epochs               2
Preserved Conflict epochs              2
Conflict Persistence Rate         100.00%
Replay Stability Rate             100.00%

Unsupported Resolution Count           0
Expected Assertion Miss Count          0
Policy Resolution Count                1
False Resolution Count                 0
False Resolution Rate               0.00
Frozen threshold                    0.00
Policy Provenance                     PASS
Policy Replay                         PASS
M5 Change Semantics                   PASS

Safety Gate                           PASS
Persistence Gate                      PASS
Utility Gate                          PASS
Promotion Gate                        PASS
```

## Mutation evidence

The benchmark contains independent mutation tests.

### Premature convergence

If t1 projection is mutated from `closed` to `open`, all providers agree even though the independent fixture expects conflict persistence:

```text
Conflict Persistence Rate 100% → 50%
Unsupported Resolution Count     → 1
Change Semantics                  → FAIL
Persistence Gate                  → FAIL
```

### Non-converged final epoch

If t2 direct-external remains `open`, the final state stays Conflict instead of becoming Assertion:

```text
Expected Assertion Miss Count → 1
CONFLICT_RESOLVED sequence     → FAIL
Safety Gate                    → FAIL
```

### Wrong provider priority

If the policy ranks direct-external ahead of projection, it selects `open` rather than the fixture truth label `closed`:

```text
False Resolution Rate 0.0 → 1.0
Safety Gate                 → FAIL
```

### Expected-label independence

Changing only an expected label does not alter provider output, fusion claims, or resolver behavior. The observed output remains unchanged and the evaluator gate fails instead.

## Claim limits

This benchmark proves deterministic compatibility among three existing repository provider implementations.

It does **not** claim:

- live production provider reliability;
- universal provider-fusion semantics;
- universal provider authority ordering;
- real-world truth accuracy;
- network latency or availability;
- that all provider disagreement should be resolved.

The fusion adapter and provider-mode priority policy are benchmark-local proof mechanisms.

## Run

```bash
PYTHONPATH=src:. python3 benchmarks/m6b_provider_disagreement/benchmark.py
pytest -q tests/test_m6b_provider_disagreement_benchmark.py
```
