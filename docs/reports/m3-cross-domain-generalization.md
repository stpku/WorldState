# M3 Cross-Domain Generalization Report

**Status:** PASS
**Date:** 2026-08-18
**Baseline:** M0 contracts + M1 reference engine + M2 provider parity

## Goal

Pass the WorldState Independence Test by proving that two materially different example domains use the same Core semantics without a Core fork or domain-specific resolver branch.

## Scenario A — Short-Lived Physical Sensor State

Characteristics:

- entity type: physical sensor node;
- source type: direct physical observation;
- update cadence: high / near-real-time;
- validity: short, explicit five-minute interval;
- conflict structure: independent sensors may disagree materially;
- expected behavior: active observation resolves to `StateAssertion`, expired observation becomes `Unknown(OUTSIDE_VALIDITY)`, incompatible supported observations remain `Conflict`.

## Scenario B — Low-Frequency Public Registry State

Characteristics:

- entity type: registered organization;
- source type: authoritative external System of Record;
- update cadence: low;
- validity: long/open-ended from an effective time;
- deployment mode: read-only WorldState projection;
- expected behavior: external SoR remains authoritative while WorldState exposes the record as evidence-grounded state.

## Generalization Boundary

All scenario-specific vocabulary is confined to `examples/cross_domain/` and tests.

The M3 boundary test verifies that the following terms do not appear in `src/worldstate`:

```text
temperature_c
registration_status
sensor_node
example-registry
example-physical
```

No M3 domain branch was added to the resolver, snapshot builder, provider protocol, in-memory engine, or Core models.

## Benchmark Cases

The benchmark executes five declared cases:

1. sensor state within validity → assertion `21.5`;
2. sensor state after validity → `Unknown(OUTSIDE_VALIDITY)`;
3. conflicting sensor observations → `Conflict`;
4. registry state after effective time → assertion `active`;
5. missing registry property → `Unknown(NO_EVIDENCE)`.

Benchmark policy remains in the example layer, not in Core.

## Metrics

| Metric | Result |
|---|---:|
| State Correctness | 1.00 |
| Provenance Coverage | 1.00 |
| Unknown Fidelity | 1.00 |
| Conflict Preservation | 1.00 |
| Validity Accuracy | 1.00 |
| Replayability | 1.00 |
| Unsupported State Rate | **0.00** |

These values describe the declared M3 benchmark cases only; they are not a claim of universal domain correctness.

## Validation

M3 targeted tests:

```text
5 passed
```

Full repository regression at M3 closure:

```text
46 passed
```

## Exit Decision

**M3 PASS.**

The second materially different domain required no semantic Core fork and no domain-specific branch in state resolution. WorldState remains a domain-neutral foundation rather than a sensor engine or registry product.
