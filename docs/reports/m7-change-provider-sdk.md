# WorldState M7 Change-Aware Provider & Projection SDK v0.1

**Status:** PASS — first deterministic implementation slice

## Scope

M7 adds a synchronous, pull-based change cursor over the existing `WorldStateProvider` contract.

```text
External SoR
→ WorldStateProvider snapshot
→ ProviderChangeCursor
→ ProviderChangePoll
→ WorldStateDelta / provider diagnostic
→ consumer-neutral wire
```

No event bus, scheduler, durable offset store, provider mutation path, or WorldState-owned persistence is introduced.

## Semantic closure

### Query-clock-only churn

Existing Projection and Direct External providers resolve snapshots at the requested query time. A naive diff therefore sees new state identifiers even when the external record did not change.

M7 retains the prior state ref when all supported semantics are unchanged and only query time moved.

```text
Naive False Change Rate      100.00%  (2/2)
M7 SDK False Change Rate       0.00%  (0/2)
Stable Ref Retention          100.00%
```

### True source changes

```text
Projection true update       detected
Direct External true update  detected
True Change Detection Rate   100.00%  (2/2)
```

Evidence/provenance refresh is not suppressed merely because the material value is unchanged.

### Provider outage

Naive snapshot diff produces:

```text
assertion → provider unavailable snapshot → REMOVED
```

M7 produces:

```text
status = provider_unavailable
delta = null
advanced = false
last-good snapshot retained
```

After recovery the next healthy poll compares against the retained last-good snapshot.

```text
Naive Outage False Transition Count  1
M7 Outage False Transition Count      0
Recovery From Last Good              PASS
```

### Validity expiry

Provider availability and validity remain distinct:

```text
available provider
+ record outside temporal validity
→ Unknown(OUTSIDE_VALIDITY)
→ VALIDITY_EXPIRED
```

Result: PASS.

## Replay and boundary evidence

```text
Replay Stability                  PASS
Consumer-Neutral Wire             PASS
Persistence Ownership Boundary    PASS
Event Bus Required                false
Push Subscription Claimed         false
```

## Frozen gates

```text
Safety Gate       PASS
Utility Gate      PASS
Promotion Gate    PASS
```

## Claim boundary

This result is deterministic and fixture-bound. It does not claim live provider reliability, production latency, push/event semantics, distributed cursor durability, retries, exactly-once delivery, or universal change transport.
