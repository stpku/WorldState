# ADR-0002 — MIT License for WorldState Core

**Status:** Accepted
**Date:** 2026-08-18

## Context

The strategic architecture requires WorldState Core to be **fully open**, but intentionally does not inherit a license choice from GeoTask, AgentReality, Lowa, or any other project. The M0 acceptance criteria therefore require an explicit repository-local license decision.

WorldState is intended to be a small, dependency-light semantic foundation and interoperability contract that can be embedded in commercial, academic, public-sector, and open-source systems without forcing a specific deployment or business model.

## Decision

WorldState is licensed under the **MIT License**.

The repository root `LICENSE` file is the normative license text.

## Rationale

MIT is selected for the initial foundation because it:

- is permissive and simple to consume;
- permits commercial and private use, modification, redistribution, and sublicensing subject to retaining the license notice;
- does not impose copyleft on systems that implement or consume the WorldState contracts;
- fits the architectural goal of maximizing adoption of a domain-neutral foundation while keeping domain products and grounding extensions independently governed.

This decision is specific to the WorldState repository. It is not inferred from another project and does not automatically determine the licenses of GeoTask, AgentReality, Lowa, GSTAR, adapters, datasets, provider content, or third-party dependencies.

## Consequences

1. Public source code in this repository is reusable under MIT terms.
2. Provider data, external evidence, datasets, and adapter-specific assets retain their own rights and licenses.
3. Contributions must not introduce code whose license is incompatible with repository distribution under MIT.
4. A future license change would require an explicit governance decision and appropriate contributor-rights handling; it is not an incidental engineering refactor.
