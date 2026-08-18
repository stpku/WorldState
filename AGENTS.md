# WorldState Repository Instructions

## Strategic authority

This repository implements the WorldState foundation defined by **AgentReality Stack Strategic Architecture Specification v2.1**.

WorldState answers exactly one question:

> **What is true about the world?**

It is an open, lightweight, domain-neutral foundation for representing evidence-grounded world state.

## Hard architectural invariants

1. **WorldState does not know the Task.** Task relevance, applicability, resolution adequacy, sufficiency, and context construction belong to GeoTask.
2. **WorldState does not run Agents.** Agent sessions, loops, tools, jobs, schedulers, retries, sandboxes, and generic traces belong to an Agent Harness.
3. **WorldState does not own domain judgment.** Domain assessment, recommendation, authorization, review, reporting, and business lifecycle belong to domain products such as Lowa.
4. **Semantic ownership does not imply data ownership.** WorldState MUST support native storage, projection from an existing System of Record, and external providers.
5. **Unknown and Conflict are first-class results.** Never coerce unknown or conflicting evidence into a known state merely to increase coverage.
6. **Observed, inferred, predicted, and simulated state MUST remain distinguishable.**
7. **Every resolved assertion MUST be traceable to provenance and validity information.**
8. **Contracts first, storage last.** Core contracts MUST NOT depend on a database, web framework, agent framework, GIS stack, or domain product.
9. **Foundation code stays domain-neutral.** No Lowa, aviation, telecom, FSS, airport, facility, GSTAR-internal, or other domain-specific business semantics in `src/worldstate`.
10. **No premature platform inflation.** Do not add distributed runtime, event bus, scheduler, workflow engine, vector database, knowledge graph server, or managed platform unless a later specification explicitly requires it.

## Initial engineering sequence

1. Freeze semantic contracts and invariants.
2. Build a deterministic in-memory reference engine.
3. Add conformance and replay tests.
4. Add provider/projection seams.
5. Prove independence in at least two unrelated example domains.
6. Only then consider optional persistence or streaming adapters.

## Code rules

- Python package: `worldstate`.
- Prefer Python standard library in Core. Add dependencies only when the semantic benefit is explicit and documented.
- Public contracts require type hints and docstrings.
- Resolution behavior must be deterministic for the same ordered input set and policy.
- State IDs and evidence references must be stable/replayable where practical.
- Mutation must not erase prior state history.
- Fail closed when required provenance/validity semantics are missing.

## Required checks

Before merging Core changes:

- unit tests pass;
- invariant tests pass;
- replay/determinism tests pass;
- no forbidden domain imports or vocabulary leak into Core;
- public API changes are documented.

## Current phase

**M4 — Integration Compatibility Proofs.**

M0 contracts, the M1 conservative reference engine, M2 provider modes, and M3 cross-domain generalization are frozen baselines. Prove thin, consumer-owned interoperability without importing GeoTask, AgentReality, Lowa, DeepSeek Harness, or domain runtime dependencies into Core. Integration fixtures MAY live outside `src/worldstate`; production adapters remain owned by the consuming project. Do not add production persistence, remote services, business writes, task policy, grounding policy, or domain authorization to WorldState in M4.
