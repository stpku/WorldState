# M6 Unknown / Conflict Fidelity Benchmark v0.1

## Purpose

This benchmark measures whether explicit conflict-resolution policy can increase useful state coverage **without** manufacturing unsupported truth.

Baseline:

```text
ReferenceResolver only
```

Policy-enabled method:

```text
ReferenceResolver
→ explicit Conflict
→ benchmark-local source-priority policy
→ ConflictResolutionDecision
→ resolved StateAssertion OR preserved Conflict
```

The benchmark-local policy reads only explicit `policy_priority` input. It does not read `expected_kind` or `expected_value` labels.

## Frozen metrics

```text
Expected assertion cases              3
Baseline correct assertions           2
Policy correct assertions             3

Baseline Useful State Coverage    66.67%
Policy Useful State Coverage     100.00%
Coverage delta                  +33.33 pp

Policy resolution count               1
False Resolution Count                0
False Resolution Rate              0.00
Frozen threshold                   0.00

Expected Conflict cases               2
Conflict Preservation Rate       100.00%

Expected Unknown cases                1
Unknown Preservation Rate        100.00%

Policy Provenance Coverage       100.00%
Unsupported Assertion Count            0
Unknown → Resolved transition         PASS

Safety Gate                           PASS
Utility Gate                          PASS
Promotion Gate                        PASS
```

## Safety interpretation

The benchmark deliberately requires two things at once:

```text
useful state coverage ↑
AND
false resolution does not ↑
```

A higher assertion count is not success by itself.

Mutation tests prove:

1. reversing the explicit authority order selects the wrong candidate and raises `False Resolution Rate` to `1.0`;
2. forcing an ambiguous disagreement to one value creates an unsupported assertion and reduces `Conflict Preservation Rate`;
3. changing only the independent expected truth label does not change policy behavior, proving the policy does not read the evaluator label.

All three mutations fail the safety/promotion gate.

## Fixture coverage

The deterministic fixture includes:

- one supported single-source assertion;
- one missing-evidence Unknown;
- one agreeing multi-source assertion;
- one explicitly ranked source disagreement that can be resolved;
- one ambiguous material disagreement that must remain Conflict;
- one epistemic-mode disagreement that must remain Conflict;
- one separate Unknown → resolved transition after missing support becomes available.

## Claim limits

This benchmark proves only a deterministic fixture-bound method property.

It does **not** claim:

- a universal source-authority order;
- real-world truth accuracy;
- production provider performance;
- that every Conflict should be resolved;
- that confidence or recency is a valid implicit truth policy.

The source-priority policy exists only in the benchmark. Core supplies the explicit policy contract and fail-closed application boundary.

## Run

```bash
PYTHONPATH=src:. python3 benchmarks/m6_unknown_conflict_fidelity/benchmark.py
pytest -q tests/test_m6_conflict_resolution.py tests/test_m6_unknown_conflict_benchmark.py
```
