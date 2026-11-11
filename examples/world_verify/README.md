# WORLD / VERIFY — WorldState evidence-view reference consumer

**Status: synthetic reference example, not connected to the live websites.**

This small *read-only consumer* demonstrates how WorldState's existing public
contracts can express the epistemic limits shown by two public research stories.
It does **not** generate 3D models, evaluate reconstruction quality, measure
buildings, run an Agent, or decide a domain action.

## Story A — From Room 517 to Earth

The example gives a *simulated* result for apparent image reprojection alignment
but returns `Unknown(no_evidence)` for the actual building height. A similar
projected image is not independent evidence of an absolute scale.

## Story B — Campus reconstruction

The example has a simulated claim for appearance similarity, **two conflicting
simulated** candidate roof orientations, and an explicit Unknown for geometric
verification. The contradictory candidate outputs are not contradictory
observations of a real historical building.

**Do not present these values as measured facts about either campus.** The
examples use deterministic illustrative data rather than the photos, models,
experimental logs, or measurements found in the two published sites.

## Run

From the repository root (Python 3.11+; no extra runtime dependencies):

```bash
PYTHONPATH=src python3 -m examples.world_verify.evidence_view --story pku_scale
PYTHONPATH=src python3 -m examples.world_verify.evidence_view --story campus_reconstruction
```

Each command prints a stable, JSON-safe, publication-consumer payload:

- `contract: world-verify.evidence-view` is **not** a new Core contract;
- each `facts[].outcome` is the **unchanged** `worldstate.state-query-result/0.1` wire;
- each assertion retains its epistemic mode and source/evidence references;
- Unknown and Conflict remain explicitly distinct from resolved assertions;
- all evidence carries `synthetic: true` and cannot be treated as a survey.

## Integration gate for the live experience

These are **proposed** steps, not completed deployments.

1. Create a separate, read-only adapter fed by authorized and versioned
   observations from the two web projects.
2. For every field define its exact source and observation time; only label
   something `observed` when there is independent verified observation.
3. Ensure each page renders `assertion | unknown | conflict` explicitly and
   does not imply task sufficiency or action authorization.
4. Add privacy/copyright and accuracy review, evidence provenance, mobile
   WeChat fallback, and independent public deployment.
5. Compare generated JSON against golden fixtures before public release.

WorldState Core must remain domain-neutral. GeoTask owns task-context
sufficiency, AgentReality owns grounding/re-grounding, and domain systems own
judgment and execution.
