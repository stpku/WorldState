# WorldState Change-Aware Provider & Projection SDK v0.1

**Status:** M7 Foundation Contract
**Mode:** synchronous pull cursor

## Purpose

M7 provides a bounded change-aware SDK over the existing synchronous `WorldStateProvider` contract without requiring provider implementations to adopt an event bus, scheduler, queue, database, or WorldState-owned persistence.

The contract is:

```text
WorldStateProvider
+ last good immutable snapshot
        ↓
ProviderChangeCursor.poll(at)
        ↓
ProviderChangePoll
  ├── changed / unchanged
  ├── provider_unavailable
  ├── WorldStateDelta / null
  └── diagnostics
        ↓
worldstate.provider-change-poll/v0.1
        +
worldstate.delta/v0.1
```

## Public surface

```text
ChangePollStatus
ProviderChangePoll
ProviderChangeCursor
open_change_cursor(...)
provider_change_poll_payload(...)
```

Contract identifiers:

```text
worldstate.provider-change-poll
version 0.1
```

The existing `worldstate.delta/v0.1` wire remains unchanged and is embedded when a healthy poll emits a delta.

## Bootstrap

```python
cursor = open_change_cursor(provider, scope, at)
```

Bootstrap captures one healthy immutable provider snapshot as the cursor's `last_good_snapshot`.

If the provider is unavailable during bootstrap, the operation fails closed because the cursor has no supported last-good state to retain.

## Healthy poll

For a healthy provider snapshot:

```text
provider.get_snapshot(scope, at)
↓
query-clock stabilization
↓
diff_snapshots(last_good, observed)
↓
ProviderChangePoll
↓
advance last_good snapshot
```

A healthy poll always advances the cursor and includes a `WorldStateDelta`, including an empty delta for `UNCHANGED`.

## Query-clock stabilization

Provider snapshots are query-time projections. Re-reading the same supported external record at a later `at` may change `resolved_at` or result `as_of` without any change in the underlying support.

M7 retains the previous state result when all semantic support is unchanged and only the query clock changed.

For `StateAssertion`, the following must remain equal before a prior ref can be retained:

- entity and property key;
- value;
- epistemic mode;
- complete provenance;
- assertion/provider version;
- uncertainty;
- spatial scope;
- validity start/end/supersession.

`validity.resolved_at` alone is ignored for change detection.

For `Unknown`, only `as_of/unknown_id` may drift; reason, proposition, missing refs and metadata must remain equal.

For `Conflict`, only `as_of/conflict_id` may drift; candidate refs, evidence refs, proposition, reason and metadata must remain equal.

Therefore:

```text
same value + same support + later query clock
→ unchanged

same value + new evidence/provenance/source version
→ changed
```

This rule prevents false changes without hiding evidence refresh.

## Provider outage

Provider outage is not world-state deletion.

When the observed snapshot contains `UnknownReason.PROVIDER_UNAVAILABLE`:

```text
status = provider_unavailable
delta = null
advanced = false
diagnostics = provider unavailable Unknown[]
```

The cursor keeps the previous last-good snapshot.

After provider recovery, the next healthy poll compares against that last-good snapshot.

This prevents:

```text
provider outage
≠ REMOVED world state
```

## Validity expiry

A provider that remains available but returns a proposition-scoped `Unknown(OUTSIDE_VALIDITY)` participates in normal diff semantics:

```text
StateAssertion
→ Unknown(OUTSIDE_VALIDITY)
→ VALIDITY_EXPIRED
```

Thus:

```text
Provider Unavailable ≠ Validity Expired
```

## Poll status

```text
CHANGED
  delta exists and delta.changes is non-empty

UNCHANGED
  delta exists and delta.changes is empty

PROVIDER_UNAVAILABLE
  delta is null
  diagnostics are non-empty
  cursor does not advance
```

Inconsistent combinations fail validation.

## Wire contract

`provider_change_poll_payload(...)` emits only WorldState-owned semantics:

```text
contract
contract_version
poll_id
status
observed_at
previous_snapshot_ref
observed_snapshot_ref
advanced
delta
diagnostics
```

No task, relevance, sufficiency, Lowa, GeoTask, or downstream action semantics belong to this contract.

## Stable identity and replay

`poll_id` is a deterministic semantic ID derived from:

- status;
- observation time;
- previous/observed snapshot refs;
- delta ref when present;
- diagnostic refs when present;
- contract version.

The same deterministic provider sequence must reproduce identical poll/delta identities and outputs.

## Persistence ownership

`ProviderChangeCursor` stores only the last-good immutable snapshot reference/object required to compute the next bounded delta.

It does not expose provider mutation methods and does not assume WorldState owns the external System of Record.

```text
Semantic change tracking ≠ persistence ownership
```

## Push/event seam

The historical optional `WorldStateChangeProvider.subscribe_changes(...)` seam remains outside M7 v0.1.

M7 does not claim:

- push subscription semantics;
- event bus semantics;
- distributed cursor persistence;
- exactly-once delivery;
- retry scheduling;
- durable offsets.

Those may be evaluated later only if real consumer evidence requires them.

## Frozen counter-metrics

The deterministic M7 benchmark freezes:

```text
M7 SDK False Change Rate = 0
Outage False Transition Count = 0
True Change Detection Rate = 100%
Stable State Ref Retention Rate = 100%
```

Reducing false changes must never be achieved by suppressing real evidence/provenance/source changes.
