# M8 Independent Consumer Generalization Benchmark v0.1

## Purpose

M8 proves that WorldState remains independently useful outside the Lowa-centered stack path.

The reference consumer is a **Cold-Chain Shipment Monitor** that directly consumes:

```text
WorldStateProvider
+
StateAssertion / Unknown / Conflict
+
M7 ProviderChangeCursor / WorldStateDelta
```

It imports no Lowa, GeoTask, or AgentReality package and requires no cross-stack adapter.

## Static truth scenarios

The deterministic fixture contains four scenarios and eight independently labeled facts:

1. healthy shipment registry + healthy temperature sensor;
2. missing registry fact → `Unknown(NO_EVIDENCE)`;
3. conflicting sensor readings → `Conflict`;
4. sensor provider outage → `Unknown(PROVIDER_UNAVAILABLE)`.

Frozen result:

```text
Static cases                         4
Fact expectations                    8
State correctness                  8/8 = 100%
Assertion provenance coverage      100%
Unknown fidelity                   100%
Conflict preservation              100%
Unsupported State Rate             0.00
```

## Temporal consumer scenario

The consumer opens M7 change cursors for both standard providers:

```text
shipment_status  in_transit → arrived

temperature_c    4.0 → 7.5
```

Expected consumer output:

```text
changed_properties = [shipment_status, temperature_c]
provider_unavailable_properties = []
```

Result: PASS.

A separate sensor outage watch must produce:

```text
changed_properties = []
provider_unavailable_properties = [temperature_c]
```

with no fabricated temperature delta and no cursor advance.

Result: PASS.

## Independence evidence

The benchmark freezes three architecture counter-metrics:

```text
Stack Dependency Count          = 0
Core Domain Leakage Count       = 0
Domain Decision Leakage Count   = 0
```

`Stack Dependency Count` parses the independent consumer/provider imports and rejects Lowa, GeoTask, or AgentReality dependencies.

`Core Domain Leakage Count` scans `src/worldstate` for cold-chain-specific vocabulary and requires zero occurrences.

`Domain Decision Leakage Count` verifies that the consumer surface exposes facts and changed/unavailable properties, not release/discard/compliance/safety decisions.

A 12°C temperature reading remains:

```text
FactView(kind=assertion, value=12.0)
```

not a shipment disposition decision.

## Frozen gates

```text
Truth Fidelity Gate   PASS
Change Gate           PASS
Independence Gate     PASS
Promotion Gate        PASS
```

## Mutation evidence

The benchmark is not self-labeling.

- relabeling the sensor Conflict as an expected Assertion does not change consumer output; Truth Fidelity Gate fails;
- removing the registry SoR update from a fixture that still expects both changes makes Change Gate fail;
- relabeling provider outage as a temperature change does not fabricate a change; Change Gate fails.

## Claim boundary

This proof is deterministic and repository-local.

It does **not** claim:

- production cold-chain compliance capability;
- live provider reliability;
- cold-chain release/discard decisions;
- a cold-chain-specific WorldState resolver;
- a Core fork;
- GeoTask or AgentReality runtime independence beyond the explicit no-dependency proof in this consumer.

## Run

```bash
PYTHONPATH=src:. python3 benchmarks/m8_independent_consumer/benchmark.py
python3 -m pytest -q tests/test_m8_independent_cold_chain_consumer.py tests/test_m8_independent_consumer_benchmark.py
```
