# WorldState BIM — Evidence-to-Editable-BIM vertical slice

**Status: experimental assisted Photo/Scan-to-BIM and local Studio; V0.2 is NOT release-ready.**

**Round 4:** Studio can create a local photo project, record image annotations, and generate editable room candidates using either a user-drawn metric sketch or pinhole backprojection of manually marked ground points with explicitly supplied camera assumptions. A [real TUM photo partial-wall workflow](../../examples/bim_real_photo_tum/round4/README.md) and external Bonsai readback were run. It is not automatic visual recognition, multiview triangulation, or a validated three-wall room.

**Round 3:** the [real CRASLAB multi-object example](../../examples/bim_real_scan_craslab/room_round3/README.md) has eight inferred walls, one slab and five windows/openings; four conflicting source objects are quarantined. The multi-wall IR, constraints, IFC export, Bonsai edit and restricted readback run locally. No independent real-room accuracy or labor-savings acceptance is claimed.

A separate [synthetic room](../../examples/bim_synthetic_room_round3/README.md) demonstrates four connected walls, a slab, door, window, openings and a versioned wall edit; its inputs are invented and must not be treated as measured evidence.

**Round 2:** an [assisted real-photo + RGB-D wall-patch IFC example](../../examples/bim_real_photo_tum/README.md) and local editing viewer are available. The example's scale is derived from the same sensor, its thickness is assumed, and it is not a complete room or V0.2 acceptance.

The product boundary is recorded in [SCOPE.md](SCOPE.md). A separate
[real-room benchmark](../../benchmarks/bim_real_room/README.md) now exercises
photo-only sparse geometry, monocular relative depth and an operator-selected
RGB-D surface patch. The real-photo result is still a single visible patch; the
multi-object example is scan-driven and not a complete verified room.

[Download the synthetic four-wall IFC example](examples/synthetic_room.ifc) to inspect the native `IfcWall` objects. This is a teaching model made from explicit simulated coordinates, **not** a photo reconstruction. Its IFC file, four wall geometric representations and stable IFC object GUIDs were checked with IfcOpenShell 0.9.0post1 in an isolated Python 3.12 environment; native Bonsai authoring review remains pending.

## North Star

> **Evidence-to-Editable World：用最低的人工成本，将真实世界证据转化为可编辑、可迭代、可复用、可验证的数字模型。**

Verification is a first-class deliverable alongside IFC: element-level source links, explicit inferred/simulated status, independent geometric and semantic tests, and an auditable revision trail. These are **target capabilities**; the existing real-photo wall patch and scan-driven objects are not evidence of independently measured, photo-only room reconstruction accuracy.

Goal: user photographs, measurement references and optional plans → DSH
multimodal modeling agent → structured parametric building proposal → editable
IFC4 objects → review and revision. WorldState Core remains independent,
domain-neutral and unchanged.

The historical v0.1 path accepts a bounded **DSH output proposal** and
converts supported `IfcWall` elements to an IFC4 BIM model (with IfcOpenShell
installed). That historical path does **not** independently infer geometry
from photographs; the assisted paths require operator selections and explicit assumptions.

## Run WorldState Studio locally

Install the Python 3.12 product dependencies as described in [Benchmark setup](../../benchmarks/README.md), then run from the repository root. Omit `--model-dir` to create a new local photo project in an unused workspace:

```bash
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.studio_server \
  --workspace /tmp/worldstate-photo-room-NEW --port 8766
```

Open `http://127.0.0.1:8766/`, create a project, upload photos, annotate a visible wall boundary for each candidate wall, and select a geometry path. The schematic path uses user-drawn proportions; the camera path requires ordered ground-corner annotations in one photo, explicit pinhole intrinsics and pitch, a level-floor/zero-roll assumption and a metric reference. It does not triangulate multiple photographs or compensate lens distortion. Both paths require a user-provided height and an explicit thickness assumption; the result remains an unverified draft. Door/window dimensions must be supplied separately. Sources, assumptions, unknowns and interaction timestamps are recorded; automated runs are marked simulated and do not measure human labor.

To inspect the existing real scan instead, specify its model directory:

```bash
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.studio_server \
  --model-dir examples/bim_real_scan_craslab/room_round3 \
  --workspace /tmp/worldstate-studio --port 8766
```

The workspace must be **outside** the source repository; the server binds only to loopback. It renders triangles extracted from the current IFC, lists evidence and quarantined objects, permits selection and supported parameter changes, and exports IFC, IR, evidence and validation reports. In a photo project, annotated images are linked to components; later uploads remain unassociated until annotated and regenerated. The command field uses a small local rule parser and is explicitly **not DSH**. Supported single-attribute external IFC edits can be selected and synchronized through the UI; unsupported changes are rejected or explicitly warned.

Optionally append `--point-cloud /path/to/xyz.npy` for an explicitly selected local `N×3` metre-coordinate point cloud. At most 8,000 points are shown; its alignment with the IFC is not automatically verified. Multi-wall edit and IFC readback commands are in the [example](../../examples/bim_real_scan_craslab/room_round3/README.md).

## Historical proposal/0.1 functionality

- Read a structured proposal with image evidence identifiers and SHA-256 hashes.
- Verify local image bytes and block traversal outside the evidence directory.
- Require evidence linkage for every inferred construction element.
- Require a documented/measured metric anchor for normal export; allow
  approximate IFC only with an **explicit** CLI flag.
- Create native `IfcWall` objects inside project/site/building/storey hierarchy.
- Attach `Pset_WorldStateEvidence` with evidence references and
  `UNVERIFIED_DRAFT` status. This is a traceability marker, **not** certification.
- Retain a JSON proposal for later human adjustment and Agent retries.

**Important:** Declaring an anchor to be measured or documented is not itself
independent verification. A production adapter must validate the actual
scale source. Merely having multiple images does not recover absolute scale
when camera geometry is inadequate.

## Verify proposal contract (no extra dependencies)

```bash
python3 -m products.worldstate_bim.cli \
  --proposal products/worldstate_bim/examples/synthetic_room_proposal.json
```

The above fixture uses an invented photo reference and is only suitable for
testing the JSON proposal parser. It **cannot** pass source-image verification
or produce a true reconstructed BIM model.

## Export a draft IFC from real, authorized evidence and DSH geometry proposal

1. Collect real source images into an isolated evidence directory.
2. Create a proposal JSON using the contract shown in the synthetic fixture,
   replacing paths and SHA-256 with the real images' values.
3. Obtain dimension/scale information from an independent measurement or
   reference drawing; record its source and declared `basis`.
4. Review each DSH-proposed wall dimension, orientation and image reference.
5. Install optional product-only packages into a dedicated environment:

```bash
pip install ifcopenshell numpy
```

6. Compile the draft (the synthetic IFC4 writer was parsed and its geometry
   generated by IfcOpenShell; real-photo and authoring-tool acceptance remain pending):

```bash
python3 -m products.worldstate_bim.cli \
  --proposal proposal.json \
  --evidence-root ./evidence \
  --output-ifc ./output/draft.ifc
```

For an intentionally approximate, unscaled *draft*, add
`--allow-approximate-scale`; this does **not** make dimensions reliable.
Open and inspect the IFC in Bonsai or an independent IFC viewer before use.

## Historical proposal roadmap

The current release gates and product sequence are in the [reset roadmap](../../docs/roadmap/worldstate-bim-product-reset.md); the table below describes the earlier proposal-stage plan.

| Iteration | Working capability | Acceptance evidence |
| --- | --- | --- |
| V0.1 (this slice) | Proposal validation + wall-only IFC compiler | Source hash checks, editable IFC walls in external viewer, tests |
| V0.2 | DSH multimodal image analysis → typed scene proposal | Real photos → wall candidates with image-region provenance; independent validation |
| V0.3 | Doors, windows, slabs, floor levels, room spaces and opening semantics | Editable IFC4 elements and verified topology, not meshes alone |
| V0.4 | Camera alignment, scale anchors, geometry optimization and revision | Unseen-view check, dimensional error, before/after diffs |
| V0.5 | DSH interactive repair loop + BIM author review | Human selects issue → rerun local affected elements → versioned IFC output |
| V1.0 | One public-room building case + one approved DCF room case | Measured comparison of cost, edit effort and geometric accuracy |

## DSH responsibilities (integration contract; deployed service not connected)

DSH orchestrates: image OCR/vision or segmentation → scale/camera hints →
structured `worldstate-bim-proposal/0.1` → call IFC compiler →
read errors → request narrow corrections → human approval.

The multimodal model must **not** directly emit IFC source text. Its output is
a constrained intermediate representation with explicit evidence references.
The exporter is deterministic and does not invent missing components.

Read [DSH integration interface](DSH_INTERFACE.md) and
[product architecture roadmap](../../docs/product/worldstate-bim-roadmap.md).

## Boundary and privacy

- Public examples only use synthetic or explicitly public/authorized assets.
- Customer drawings, IFC, contracts, detailed DC design and acceptance workflows
  belong in a separate private engineering product, not this public repository.
- WorldState Core owns state semantics; it is not responsible for inferring
  building geometry or for professional construction sign-off.
