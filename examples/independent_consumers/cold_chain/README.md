# Cold-Chain Shipment Monitor — Independent WorldState Consumer

This example is the WorldState M8 independent-consumer proof.

It is deliberately outside the Lowa / GeoTask / AgentReality execution path and consumes WorldState contracts directly.

## Domain

The consumer presents two pieces of cold-chain shipment state:

```text
Shipment Registry / API
→ shipment_status

Temperature Sensor
→ temperature_c
```

The registry uses the existing `ProjectionWorldStateProvider`. The temperature source uses the existing `DirectExternalWorldStateProvider`; a separate `InMemoryWorldState` fixture is used to prove conflicting sensor observations remain `Conflict`.

## Consumer chain

```text
WorldStateProvider(registry)
+
WorldStateProvider(temperature)
        ↓
ColdChainMonitor.read(at)
        ↓
ColdChainWorldView
  ├── shipment_status FactView
  └── temperature_c FactView
```

For temporal monitoring:

```text
ColdChainMonitor.open_watch(t0)
        ↓
ProviderChangeCursor × 2
        ↓
External SoR / sensor changes independently
        ↓
ColdChainWatch.poll(t1)
        ↓
ColdChainChangeView
  ├── changed_properties
  └── provider_unavailable_properties
```

## Truth fidelity

The consumer preserves WorldState result kinds rather than flattening them:

```text
StateAssertion → FactView(kind=assertion, value=...)
Unknown        → FactView(kind=unknown, reason=...)
Conflict       → FactView(kind=conflict, value=null)
```

Assertions retain evidence/source references. Unknown and Conflict are not converted into guessed values.

## Decision boundary

This is a state-monitoring consumer, not a cold-chain compliance engine.

For example:

```text
temperature_c = 12.0
```

is still represented as a supported temperature fact. The consumer does not output:

- release shipment;
- discard shipment;
- compliant / non-compliant;
- safe / unsafe;
- routing or operational authorization.

Those decisions require downstream domain policy.

Therefore:

```text
WorldState Truth
≠ Cold-Chain Compliance Decision
```

## Independence boundary

The consumer imports no Lowa, GeoTask, or AgentReality package and requires no cross-stack adapter. It talks directly to `WorldStateProvider` and the M7 pull-based change cursor.

No cold-chain vocabulary is added to `src/worldstate`.

## Run

```bash
python3 -m pytest -q tests/test_m8_independent_cold_chain_consumer.py
PYTHONPATH=src:. python3 benchmarks/m8_independent_consumer/benchmark.py
```
