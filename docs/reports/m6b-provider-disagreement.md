# WorldState M6b Provider Disagreement & Conflict Persistence

**Status:** PASS — deterministic owner-native evidence

## Scope

M6b validates the existing Native, Projection, and Direct External provider implementations against M5 change semantics and M6 Unknown / Conflict fidelity.

No WorldState Core provider API or resolver semantic was changed.

## Frozen chain

```text
InMemoryWorldState
+ ProjectionWorldStateProvider
+ DirectExternalWorldStateProvider
        ↓
benchmark-local provider-lineage Claim projection
        ↓
ReferenceResolver
        ↓
t0 Conflict
→ t1 Conflict / CONFLICT_CHANGED
→ t2 Assertion / CONFLICT_RESOLVED
```

At t1 an explicit benchmark-local provider-mode policy is separately applied to the already-materialized Conflict. The policy decision, selected candidate, reason, output assertion, and provenance are replay-stable.

## Frozen result

```text
Provider modes                         3
Provider Mode Coverage Rate       100.00%
Epochs                                 3
Conflict Persistence Rate         100.00%
Replay Stability Rate             100.00%
Unsupported Resolution Count           0
Expected Assertion Miss Count          0
False Resolution Rate               0.00
Policy Provenance                     PASS
Policy Replay                         PASS
M5 Change Semantics                   PASS
Safety Gate                           PASS
Persistence Gate                      PASS
Utility Gate                          PASS
Promotion Gate                        PASS
```

## Mutation evidence

- premature provider convergence at t1 → persistence/change gate FAIL;
- non-converged final epoch → expected assertion/change gate FAIL;
- wrong provider priority → False Resolution Rate = 1.0 and safety gate FAIL;
- expected-label-only mutation does not alter provider fusion output.

## Claim boundary

This evidence is deterministic and repository-local. It proves compatibility among the three existing provider implementations. It does not claim live production-provider reliability, universal provider fusion, universal source authority, real-world truth accuracy, latency, or availability.

## Validation

```text
M2 + M5 + M6a + M6b adjacent tests   33 / 33 PASS
Full repository                       95 / 95 PASS
M6b additions                           8 tests
Core files changed                      0
```
