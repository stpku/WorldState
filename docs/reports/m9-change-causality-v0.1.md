# WorldState M9 Change Causality v0.1

**Status:** PASS — deterministic owner-native causal semantics

## Owner-native progress

WorldState can now preserve effective, observation, and ingestion time separately and derive an order-independent canonical change frontier from explicit causal evidence.

Focused proof includes:

```text
late A after newer B                    no stale resurrection
transport duplicate                    no active/work amplification
resolution targeting a duplicate       canonical target resolved
new conflict after resolution           unresolved, not silently chosen
two concurrent resolution candidates   unresolved
same value with new provenance          not mislabeled duplicate
false supersession / cycles             rejected
input-order replay                      stable frontier
```

No Task, Agent, Harness, Lowa, provider runtime, scheduler, persistence, or event infrastructure was added.

Focused verification:

```text
M9 + M5 + M7 adjacent  24 / 24 PASS
WorldState full repository 131 / 131 PASS
```
