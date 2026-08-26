# WorldState M8 Independent Consumer Generalization

**Status:** PASS — deterministic independent-consumer exit evidence

## Scope

M8 proves WorldState utility outside the Lowa / GeoTask / AgentReality execution path with a Cold-Chain Shipment Monitor.

The consumer directly consumes existing WorldState public contracts:

```text
ProjectionWorldStateProvider
+
DirectExternalWorldStateProvider / InMemoryWorldState conflict fixture
        ↓
ColdChainMonitor
        ↓
StateAssertion / Unknown / Conflict views
        +
M7 ProviderChangeCursor / WorldStateDelta
```

No WorldState Core fork or cold-chain-specific resolver is introduced.

## Frozen evidence

```text
Static scenarios                         4
Fact expectations                        8
State correctness                      8/8 = 100%
Assertion provenance coverage          100%
Unknown fidelity                       100%
Conflict preservation                  100%
Unsupported State Rate                 0.00
Temporal change fidelity               PASS
Provider-outage change fidelity        PASS
Replay stability                       PASS
Stack Dependency Count                    0
Core Domain Leakage Count                 0
Domain Decision Leakage Count             0
Truth Fidelity Gate                    PASS
Change Gate                            PASS
Independence Gate                      PASS
Promotion Gate                         PASS
```

## Decision boundary

A supported temperature reading such as `12.0°C` is surfaced as a fact, not a release/discard/compliance/safety decision.

```text
WorldState Truth
≠ Cold-Chain Domain Decision
```

## Mutation evidence

- changing the independent truth label for a sensor Conflict does not change consumer output and fails Truth Fidelity Gate;
- deleting a registry update while retaining the expected change label fails Change Gate;
- relabeling provider outage as a temperature state change does not fabricate a delta and fails Change Gate.

## Claim boundary

This proof is deterministic and repository-local. It does not claim production cold-chain compliance, live provider reliability, universal logistics semantics, or domain decision authority.

## Engineering boundary

M8 is implemented entirely under `examples/`, `benchmarks/`, `tests/`, `docs/roadmap/`, and `docs/reports/`.

```text
src/worldstate changes = 0
```

The independent consumer therefore proves cross-domain reuse of the existing M0–M7 foundation rather than extending Core for the second domain.
