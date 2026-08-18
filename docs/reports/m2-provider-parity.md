# M2 Projection & Provider Conformance Report

**Status:** PASS
**Date:** 2026-08-18
**Baseline:** M1 deterministic reference engine

## Goal

Prove that **WorldState semantic ownership does not imply WorldState data ownership**.

M2 compares three independent deployment modes against the same public provider contract and the same reusable conformance probes.

## Implementations under test

### A. Native reference mode

`InMemoryWorldState` owns only its local in-memory test registries and uses the M1 conservative resolver.

### B. Projection mode

```text
ExternalRecordStore  ← authoritative writes happen here
        ↓ read-only projection
ProjectionWorldStateProvider
        ↓
WorldState contracts / reference resolution
```

The projection provider exposes no `put`/business write method. A record update in the external store is visible on the next WorldState query without migrating the authoritative record into WorldState.

### C. Direct external-provider mode

```text
DirectExternalSource
        ↓
DirectExternalWorldStateProvider
```

This provider implements `WorldStateProvider` directly and does not import or invoke `ReferenceResolver` or `InMemoryWorldState`.

## Shared conformance result

The three implementations execute the same `ProviderProbe` set through `check_provider_conformance(...)`.

The parity criterion is **semantic parity**, not identical internal IDs across unrelated providers. Provider-specific provenance, evidence identifiers, resolver methods, and source versions are allowed to differ. The common contract requires the same defensible outcome kind and expected world-state value while preserving evidence and replay semantics.

Validated behaviors:

- positive assertion conformance;
- explicit `Unknown(NO_EVIDENCE)` conformance;
- evidence retrieval for resolved assertions;
- deterministic snapshot replay;
- canonical snapshot result ordering;
- runtime `WorldStateProvider` structural conformance.

## Projection-authority proof

The test updates the authoritative `ExternalRecordStore` after an initial query. Without writing anything to `ProjectionWorldStateProvider`, a later query resolves the updated record and produces a new assertion identity.

Therefore:

> **Projection is a read model, not a hidden data migration.**

## Failure semantics proof

The direct external source can become unavailable. When that occurs:

```text
query_state(...)
→ Unknown(PROVIDER_UNAVAILABLE)
```

and:

```text
get_snapshot(...)
→ snapshot containing Unknown(PROVIDER_UNAVAILABLE)
```

No previous positive assertion is returned as a fallback.

## Validation

M2 targeted tests:

```text
4 passed
```

Full repository regression at M2 closure:

```text
41 passed
```

## Exit decision

**M2 PASS.**

Native reference, read-only projection, and independent external-provider implementations all satisfy the same WorldState semantic contract. No production database, remote service, task-context logic, agent runtime, or domain migration was introduced.
