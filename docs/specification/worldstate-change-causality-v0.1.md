# WorldState Change Causality v0.1

**Status:** M9 owner-native causal frontier contract
**Date:** 2026-08-27

## Purpose

WorldState already expresses deterministic state deltas, Unknown, Conflict, validity change, provider diagnostics, and history. v0.1 adds the minimum semantic layer needed when evidence arrives late, twice, or in a different order from reality.

The contract answers:

> Which observed changes remain causally active given explicit evidence and relations?

It does not schedule events, deliver messages, choose task relevance, ground an Agent, or make domain decisions.

## Three times

`CausalChangeObservation` separates:

```text
effective_at  when the represented change became effective in reality
observed_at   when evidence observed that change
ingested_at   when the observation entered this replay/consumer boundary
```

`effective_at` equals the underlying `StateChangeRef.occurred_at`. For observed-state v0.1:

```text
effective_at <= observed_at <= ingested_at
```

Arrival/input order has no truth semantics.

## Relations

`CausalRelationKind` supports:

```text
same_change
duplicate_observation
supersedes
caused_by
derived_from
concurrent_with
conflicts_with
invalidates
resolves
partially_resolves
unrelated
```

The relation is explicit evidence. Core never infers source authority or treats later ingestion as supersession.

Directional successor relations cannot point from an earlier effective change to a later target. Directional cycles fail closed.

## Canonical frontier

`build_causal_frontier(...)` produces a content-derived `CausalFrontier` containing:

- all observation and relation refs;
- causally active observation/change refs;
- transport duplicates;
- superseded and resolved refs;
- unresolved active groups;
- maximum effective, observation, and ingestion times.

The frontier identity excludes `as_of`, so replaying the same causal evidence at a later processing boundary does not manufacture a new semantic frontier.

## Duplicate semantics

Observations are automatic transport duplicates only when complete change semantics and evidence refs match. A new observation with the same value but different provenance/source support is not a duplicate.

Resolution/supersession targeting any automatic duplicate is normalized to its canonical observation, preventing a late duplicate from resurrecting resolved state.

## Unresolved semantics

Multiple active observations for one entity/property form an unresolved group unless explicit precedence removes one. This includes:

- concurrent resolution candidates;
- newer conflicting evidence after a prior resolution;
- same value with materially different support but no supersession relation;
- causally ambiguous late evidence.

WorldState does not choose one merely because a consumer wants a single result.

## Out-of-order safety

```text
A effective
B supersedes A
B ingested
A ingested late
```

with explicit relation yields active B regardless of input/arrival order.

```text
A invalidates
B resolves A
late duplicate A ingested
```

yields active B; the duplicate is suppressed and cannot resurrect A.

If the supersession/resolution relation is missing, both remain unresolved. Missing causal evidence therefore fails ambiguous rather than silently latest-wins.

## Replay

Same observations, relations, and policy-free Core behavior produce the same:

- frontier ID;
- active/suppressed sets;
- unresolved groups;
- wire payload.

The builder reads no wall clock, network, randomness, storage, queue, or scheduler.

## Failure boundaries

Frozen tests cover:

- causal inversion from arrival-order policy;
- stale state resurrection through late duplicate;
- false supersession;
- lost/reopened conflict;
- false resolution between concurrent candidates;
- duplicate amplification;
- directional cycles;
- non-deterministic input ordering;
- loss of effective/observation/ingestion time lineage.

## Claim limits

v0.1 is an explicit-evidence deterministic frontier, not a universal causal inference engine. It does not infer relations from timestamps, perform vector clocks, distributed ordering, durable offsets, event delivery, authority ranking, task impact, grounding admission, or domain authorization.
