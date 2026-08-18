# M1 Reference Resolution Engine Validation

**Status:** PASS
**Date:** 2026-08-18
**Baseline:** WorldState Core v0.1 / M0 frozen contracts

## Goal

Prove the smallest useful, dependency-free implementation of Evidence-Grounded State Resolution without persistence, source ranking, confidence ranking, task semantics, agent runtime semantics, or domain policy.

## Implemented

- `ReferenceResolver` conservative deterministic resolution;
- in-memory observation/evidence/claim registries;
- explicit `Unknown` / `Conflict` preservation;
- provenance availability checks that fail closed;
- temporal validity filtering;
- deterministic `StateAssertion`, `Unknown`, `Conflict`, and snapshot identities;
- canonical snapshot ordering;
- evidence lookup;
- deterministic transition construction and history query;
- reusable provider conformance suite;
- runtime `WorldStateProvider` conformance for `InMemoryWorldState`.

## Resolution baseline

```text
matching claim set
      ↓
no visible claim             → Unknown(NO_EVIDENCE)
claims outside validity      → Unknown(OUTSIDE_VALIDITY)
required provenance missing  → Unknown(INSUFFICIENT_EVIDENCE)
usable claims agree          → StateAssertion
usable claims disagree       → Conflict
```

The resolver does **not** choose a winner by source type, latest timestamp, or confidence.

## Determinism proof

The tests verify that:

- claim input order does not change assertion identity;
- snapshot ingest order does not change snapshot identity;
- repeated query/snapshot replay at the same `as_of` boundary is stable;
- future evidence is not visible to a past query;
- snapshot result ordering is canonical.

## Validation

At M1 closure the repository test suite reported:

```text
37 passed
```

Packaging was also built successfully in an isolated temporary virtual environment as `worldstate-0.0.1.dev0`.

## Exit decision

**M1 PASS.**

The reference engine is now a frozen conformance baseline for M2. This is not authorization to add production persistence or migrate any external System of Record.
