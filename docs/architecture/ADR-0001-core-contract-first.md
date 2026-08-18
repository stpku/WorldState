# ADR-0001 — Contract-First, Dependency-Light Core

**Status:** Accepted for M0  
**Date:** 2026-08-18

## Context

WorldState is intended to become an open, domain-neutral world-state foundation and interoperability contract. The main early risk is platform inflation: selecting storage, graph, GIS, streaming, agent, or web infrastructure before truth semantics are stable.

The strategic architecture requires WorldState to remain independently useful and to support native state, projection from an existing System of Record, and external providers.

## Decision

For M0:

1. Implement semantic contracts as frozen Python dataclasses/value objects.
2. Require Python 3.11+.
3. Keep Core runtime dependencies at zero.
4. Model spatial scope with lightweight references/bounding boxes rather than a mandatory geometry package.
5. Separate `observed_at` from `recorded_at` for replay semantics.
6. Treat `Unknown` and `Conflict` as successful first-class state-query outcomes.
7. Define `StateQueryResult = StateAssertion | Unknown | Conflict`.
8. Use deterministic canonical serialization + SHA-256 helpers for replay-stable semantic IDs.
9. Define a synchronous `WorldStateProvider` as the mandatory interoperability protocol.
10. Keep change subscriptions in a separate optional protocol so event infrastructure is not forced into Core.
11. Defer production persistence, graph databases, web APIs, streaming, Agent/Harness integrations, GeoTask, Lowa, and GSTAR-specific logic.

## Why `StateQueryResult` is a union

A single-return `StateAssertion` API encourages implementations to encode uncertainty as `None`, exceptions, fallback values, or metadata flags. That weakens the strategic requirements that Unknown and Conflict remain explicit.

The union makes unsupported knowledge impossible to ignore accidentally at the type/contract level.

## Why no mandatory database

Semantic ownership and data ownership are different. A Lowa-style business System of Record can remain authoritative while a read-only projection implements WorldState semantics. An external system can implement `WorldStateProvider` without re-persisting its data.

## Why no mandatory GIS dependency

World state frequently has spatial scope, but spatial topology is not the same thing as world-state semantics. Requiring a geometry stack would increase installation cost and bias the Foundation toward GIS-specific implementations. Rich geometry can be supplied by adapters/providers.

## Consequences

### Positive

- Core remains easy to embed.
- Provider conformance can be tested without infrastructure.
- Projection mode remains a first-class architecture.
- Replay and audit are designed in from the start.
- Unknown/conflict preservation is structural rather than stylistic.

### Trade-offs

- M0 value types are less feature-rich than domain schemas.
- Rich geospatial operations require optional adapters.
- No production persistence exists initially.
- The reference resolver must start conservative rather than clever.

## Revisit triggers

Revisit this ADR only if evidence shows that one of the deferred dependencies is required to preserve WorldState semantics themselves, not merely to simplify one integration or deployment.
