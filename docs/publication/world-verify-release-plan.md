# WorldState × WORLD / VERIFY: evidence-first public research stories

**Date:** 2026-11-11  
**Status:** planning + a tested synthetic example, **not** a live integration or a production release.

## One technology brand, two independent stories

WorldState answers: **What is true about the world, and what is still unknown?**

Brand line: **让 AI 的世界有状态、有证据、有边界。**

Publication channel: 燕园时空. WORLD / VERIFY is the name of the research
story collection, not a competing technology brand. GeoTask and AgentReality
remain separate open projects with distinct contracts.

### Story 01: 从遥感楼517到地球

Public entry: https://skyswind.tailf4fad8.ts.net/aidc3d-artifacts/world-verify/?edition=pku#/0

Claim at issue: agreement of image projections does not uniquely determine
building scale. In the first evidence view, image reprojection is **simulated**
and absolute height remains **unknown** absent an independent scale reference.
The real website's model assets/availability and historical source permissions
must be verified before promotion.

### Story 02: AI 重建校园，颜色更像为什么空间可能错了？

Public entry: https://skyswind.tailf4fad8.ts.net/aidc3d-artifacts/world-verify/#/0

Claim at issue: visual agreement and color measurements are not sufficient
evidence of geometrical correctness. The second evidence view uses **only
synthetic** example claims to show simulated appearance, conflicting candidate
geometry, and unknown physical verification. It is **not** an evaluation of
the actual school, reconstruction methods, or experimental scores.

## Presentation architecture (consumer-owned)

```text
Authorized evidence + explicit time & source
                  |
           WorldStateProvider
                  |
        StateAssertion | Unknown | Conflict
                  |
  worldstate.state-query-result / 0.1 (unchanged)
                  |
    Independent WORLD / VERIFY read-only adapter
                  |
    Evidence View in each public research story
```

No novel `Task`, `Grounding`, `ActionAuthorization`, `RealityScore`, or
`3DReconstruction` concepts are added to WorldState Core. WorldState's
semantic ownership does not imply custody of the primary photographs, business
data, or reference models.

## Editorial plan

| Phase | Story 01 | Story 02 |
| --- | --- | --- |
| Hook | Four photos, one building, which scale? | Better color score, but correct geometry? |
| Evidence | Source photos, scale ambiguity, missing independent measure | Paired render and observations, geometry constraints, disclosed uncertainty |
| 90-second interaction | Change scale and inspect what remains invariant | Compare appearance with topology / geometry checks |
| Brand | State can be Unknown even when a picture looks right | Simulated results cannot be promoted to observed truth |
| Next step | Open verified evidence sources | Open comparison and provenance |

## Release gates

- [ ] Each entry has distinct external URL, metadata and Open Graph preview.
- [ ] Desktop, mobile and WeChat embedded browser tests pass.
- [ ] All embedded 3D assets load, or visible fallback clearly states limitations.
- [ ] Every factual assertion has a source, observation method and time bounds.
- [ ] Synthetic/inferred/predicted/simulated are **never** presented as observed.
- [ ] Unknown and Conflict remain visible; conflicts do not silently resolve.
- [ ] Copyright, historic campus image rights, sensitive data, and employer
      boundary are reviewed.
- [ ] GeoTask/AgentReality capabilities are not attributed to WorldState.
- [ ] Public deployment is separated from private developer services and
      protected development portals.
- [ ] The evidence-view adapter is proven against real, authorized inputs;
      before that, the website must describe it as a teaching illustration.

## Iterative public milestones

- **P0 — Positioning and proof:** independent story framing, contract-stable
  reference consumer, tests, evidence audit.
- **P1 — Read-only evidence adapters:** source-specific adapters outside
  WorldState Core, fixtures from authorized documents, deterministic snapshots.
- **P2 — Live Evidence View:** web UI consuming stable JSON with explicit
  Unknown/Conflict/freshness plus mobile fallback.
- **P3 — External adoption:** second independent non-campus consumer, quickstart,
  transparent benchmarks (Truth Fidelity, provenance coverage, unsupported state
  rate), versioned migration guidance.

**Do not remove or rewrite existing M0–M9 contracts, ADRs, reports,
benchmarks, migration receipts, or release history.**
