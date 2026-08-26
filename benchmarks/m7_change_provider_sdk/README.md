# M7 Change-Aware Provider & Projection SDK Benchmark v0.1

## Purpose

M7 turns the existing synchronous `WorldStateProvider` surface into a bounded, pull-based change SDK without requiring providers to own an event bus, scheduler, or WorldState persistence.

The benchmark compares:

```text
naive provider.get_snapshot(t0/t1) + diff_snapshots
vs
ProviderChangeCursor
```

using the existing:

- `ProjectionWorldStateProvider`;
- `DirectExternalWorldStateProvider`.

## Why the SDK is necessary

Existing provider snapshots are query-time projections. A provider may resolve the same unchanged external record at a later `at` boundary, which changes `resolved_at` and therefore state identifiers.

A naive snapshot diff therefore reports a false `STATE_CHANGED` even when the underlying supported state is unchanged.

M7 stabilizes state identity only when the difference is query-clock-only. It still treats changes to value, evidence/provenance, source/provider version, validity window, uncertainty, scope, Unknown reason, or Conflict candidates/evidence as real semantic changes.

```text
same supported state + later query clock
→ retain prior state ref
→ UNCHANGED

same value + refreshed evidence/provenance
→ semantic change remains visible
```

## Pull cursor

```text
External SoR
↓
WorldStateProvider.get_snapshot(t0)
↓
open_change_cursor(...)
↓
External SoR changes independently
↓
cursor.poll(t1)
↓
ProviderChangePoll
  ├── status
  ├── WorldStateDelta / null
  └── provider diagnostics
↓
consumer-neutral wire payload
```

The cursor stores only the last good immutable snapshot. It does not own or mutate the provider's System of Record.

## Provider outage rule

A provider outage is not a world-state deletion.

Naive behavior in the deterministic Direct External fixture:

```text
last assertion
→ provider unavailable snapshot
→ diff_snapshots
→ REMOVED
```

M7 behavior:

```text
provider unavailable
→ ProviderChangePoll(status=provider_unavailable)
→ diagnostic Unknown(PROVIDER_UNAVAILABLE)
→ delta = null
→ advanced = false
→ keep last good snapshot
```

After recovery, the next healthy poll compares against the last good snapshot.

## Frozen benchmark result

```text
Provider modes                            2
Unchanged cases                           2

Naive False Change Count                  2
Naive False Change Rate             100.00%
M7 SDK False Change Count                 0
M7 SDK False Change Rate               0.00%
Stable State Ref Retention Rate      100.00%

True Change cases                         2
True Change detected                      2
True Change Detection Rate           100.00%

Naive Outage False Transition Count       1
M7 SDK Outage False Transition Count      0
Provider Outage Diagnostic               PASS
Recovery From Last Good                  PASS
Validity Expiry                          PASS
Replay Stability                         PASS
Consumer-Neutral Wire                    PASS
Persistence Ownership Boundary           PASS

Safety Gate                              PASS
Utility Gate                             PASS
Promotion Gate                           PASS
```

## Counter-metrics

M7 freezes:

```text
False Change Rate = 0
Outage False Transition Count = 0
True Change Detection Rate = 100%
Stable State Ref Retention Rate = 100%
```

A lower false-change rate is not acceptable if real source/evidence changes are missed.

## Mutation evidence

The benchmark includes independent mutations:

- changing only the expected label does not change SDK output; the evaluation gate fails instead;
- removing a source update from a case independently labeled `changed` lowers True Change Detection Rate and fails the safety gate;
- the naive baseline demonstrates both clock-only false changes and an outage-induced false `REMOVED` transition.

## Claim limits

This benchmark is deterministic and fixture-bound.

It does not claim:

- event-bus semantics;
- push subscription semantics;
- live provider reliability;
- production latency;
- universal change transport;
- distributed cursor durability;
- exactly-once delivery.

The M7 v0.1 SDK is intentionally pull-based and synchronous.

## Run

```bash
PYTHONPATH=src:. python3 benchmarks/m7_change_provider_sdk/benchmark.py
python3 -m pytest -q tests/test_m7_change_sdk.py tests/test_m7_change_sdk_benchmark.py
```
