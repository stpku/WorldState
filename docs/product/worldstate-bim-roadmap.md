# WorldState: from evidence records to buildable, editable BIM assets

**Architecture revision: 2026-11-11**  
**Decision:** Product priority is **evidence-driven BIM reconstruction**. Truth
Fidelity and Unknown/Conflict remain enabling reliability semantics, not the
user-facing final product. First vertical application: **WorldState BIM**.

## North Star — Evidence-to-Editable World

> **Evidence-to-Editable World：用最低的人工成本，将真实世界证据转化为可编辑、可迭代、可复用、可验证的数字模型。**

The four properties are joint acceptance requirements, not interchangeable labels:

1. **Editable** — native semantic BIM elements (IFC walls, openings, floors and relations), rather than an unstructured visual mesh.
2. **Iterable** — a reviewer or DSH can change an identified element, preserve its stable identity and regenerate only affected geometry where supported.
3. **Reusable** — units, coordinates, object identifiers, element relationships, source references and IFC interoperability survive export and reimport.
4. **Verifiable** — each element carries linked source evidence and an explicit epistemic status; geometry is checked against independent metric references, held-out views and semantic/topology constraints with reproducible results and known gaps.

**Lowest human cost** must be measured as correction/review effort and total cost per *accepted* model, never just model generation time. A model is not considered verified simply because its IFC file parses, its geometry renders, or an LLM reports confidence. Verification must produce inspectable evidence and report uncertainty, unresolved errors and the validation scope.

The intended future output is an **editable IFC model + element-level evidence/provenance + validation report + versioned corrections**, with explicit attribution of observed, inferred and simulated properties. These are product acceptance goals, not existing V0.1 capabilities.

## Outcome, not a slogan

A user gives a small set of permitted photographs and one independent physical
dimension, then interacts with a DSH modeling agent to obtain an **editable IFC4
building model**, reviews its elements, corrects wrong geometry, and exports a
revision. A GLB/3D preview alone does not pass acceptance.

The existing `src/worldstate` M0–M9 Core remains a domain-neutral, versioned,
evidence-grounded state provider. Do not embed Blender, IfcOpenShell, GPU model
weights, DSH Agent logic or customer engineering policies in Core.

## Production architecture

```text
Photographs / video / plans / point cloud / verified measurement
   ↓ manifest + raw evidence retention
Evidence intake (timestamp, reference, permission, source hashes)
   ↓
DSH orchestration + multimodal LLM / vision tools
   ├─ photo semantic objects: wall, slab, column, door, window...
   ├─ feature correspondences / camera pose (SfM if enough overlap)
   ├─ metric anchor alignment / bounded geometry optimization
   └─ typed parametric intermediate model (never arbitrary IFC text)
   ↓
BIM compiler (IfcOpenShell / optional Blender / Bonsai review)
   ├─ metric coordinate system, IFC4 hierarchy, native element classes
   ├─ geometry & topology / relationships / parameter sets
   └─ editable IFC + GLB review proxy
   ↓
Reprojection / dimensional / topology evaluation
   ↓
DSH narrow repair -> human BIM reviewer -> versioned IFC
   ↕
WorldState Core: evidence-to-object state, provenance, unknown, history
```

WorldState Core is not the authoring product; WorldState BIM is the product.
AIDC engineering review and customer-specific CAD/BIM remain private,
consumer-owned adaptations rather than public-repository features.

## Practical task slicing

- **P0**: a single room with 4 walls, **one known distance**, several
  images from the same building phase. Produce editable IFC walls, not a mesh.
- **P1**: infer a subset of doors/windows/slabs and assign to a building storey.
- **P2**: add a DSH human-guided repair tool: pick incorrect opening/height,
  re-estimate only affected elements, maintain history.
- **P3**: integrate the existing public NEXUS/Blender photo-model work as
  *consumer-owned*, not copied into Core. Start with licensed public samples.
- **P4**: DCF room trial in **private** engineering repo with customer-approved
  data, using the same typed BIM proposal and IFC compiler interface.

## Quality and readiness gates

Before claims of automated photo-to-BIM or engineering-ready geometry, measure:

1. IFC correctness: independent parser opens file; hierarchy, wall counts,
   geometric representations and editability verified in Bonsai.
2. Geometric fidelity: use **held-out** image views, independent dimensions and
   reported per-element errors; never evaluate only the training photograph.
3. Semantic fidelity: wall/door/window type precision and recall on manually
   labeled ground truth, topology and openings checked independently.
4. Provenance: every emitted element records exactly which photos, dimensions,
   or documented rules support it; unsupported geometry explicitly approximate.
5. Production value: manual correction time, complete model creation time,
   review workload, failed/retry rate, cost per accepted room.
6. Security: public synthetic data separate from customer/enterprise data;
   DSH must not treat photo-embedded text as authority for tool execution.

**Initial proposal-only milestones (not measured performance):** demonstrate
one room through two independently checked photo views; edit four walls in
Bonsai, export/import IFC4, then build a gold set of at least 10 rooms of varied
geometry before claiming generalizable accuracy.

## Current reality

The first vertical slice validates an evidence-linked **wall-only
parametric proposal** and has generated a synthetic IFC4 room containing four
semantic, geometrically parseable IfcWall objects with stable GUIDs using
IfcOpenShell 0.9.0post1. It does not yet perform automatic image recognition,
camera calibration, DSH orchestration, independent BIM-authoring-tool review,
opening modeling, or actual engineering validation.
The synthetic JSON fixture is not a photograph and must not be advertised as
real-world reconstruction.

The public NEXUS project already has a Blender/GLB modeling chain and research
notes on single-photo camera alignment and Text2BIM. These are inputs to
integration planning, not evidence of native IFC delivery. Treat evidence
metadata, time identity and construction stage as versioned source facts.
