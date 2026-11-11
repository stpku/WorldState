# DSH → WorldState BIM contract (proposed)

**Not implemented:** This describes a specific integration task for the
existing DeepSeek Harness environment. No live DSH endpoint is called by the
prototype today.

## Input

- Evidence manifest: photo IDs, paths, hashes, provenance, capture date if known
- Additional context: floor plan when licensed, camera pose if known
- Metric anchors: checked dimension + source (not model-generated assumptions)
- Target IFC scope, e.g. simple room walls first
- Human objective: model which building phase / room / date, and excluded regions

## Required tools

```text
inspect_images(manifest)                  -> image-level features and evidence refs
propose_parametric_geometry(context)     -> worldstate-bim-proposal/0.1
check_metric_scale(anchors, cameras)     -> anchored / unanchored with reasons
validate_proposal(proposal, evidence)    -> typed errors, no vague success
compile_ifc(proposal, mode=draft)         -> IFC file path, export warnings
compare_projection(ifc, cameras, images) -> residuals per visible evidence
request_human_review(changes, unknowns)  -> accept / correct / reject
```

## DSH output contract

The current compiler supports only `walls`, each as a line-based semantic
`IfcWall` with `start_m`, `end_m`, `height_m`, `thickness_m`, `basis`
and non-empty `evidence_refs`. Use `images[].sha256` to bind source files.
Set all geometry that is inferred from photos to `inferred`, not `measured`.

Dangers to explicitly detect:
- no independent metric anchor (no silent conversion to real metres);
- missing or inaccessible photo evidence;
- inconsistent building phase/camera date;
- DSH claims of unseen walls or room layout without supporting evidence;
- invented doors/windows/equipment dimensions;
- IFC successfully written but wrong room topology / physically impossible wall;
- model confidence labels treated as engineering acceptance.

The loop must return actionable tool errors to DSH but MUST NOT automatically
approve construction or overwrite authoritative design records.
