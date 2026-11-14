# WorldState BIM changelog

## Unreleased — 2026-11-14

- Add experimental multiview wall-floor line fitting, attributed corner triangulation and Studio inspection using the shared semantic floor. Compare both routes on the same real development input; reject an unstable third wall candidate. New-room accuracy, independent scale and human savings remain unmeasured.

- Fuse real registered multiview semantic tracks into provisional 3D surfaces and plane intersections; bind a triangulated two-view scale to observations and camera poses, preserve evidence, and compile selected partial surfaces to IFC. The real example has two candidates and assumed, non-independent scale; no three-wall or release acceptance is claimed.

- Add optional local CPU semantic vision proposals, overlay inspection, explicit accept/reject and model provenance; a real-photo scripted preview generates three disconnected editable IFC wall-segment candidates with **assumed** scale and height. That earlier single-photo workflow does not triangulate wall corners; semantic surface hypotheses remain research.
- Bind scale to source photo, physical endpoint observations, selected wall, measurement and camera; changed inputs require explicit rechecking and rebinding. Historical unbound photo projects must bind before regeneration.

- Add local photo-project creation, image annotation, explicit camera-floor backprojection or manually drawn floor-layout geometry, scale application, versioned IFC generation, and browser IFC readback. The real-photo result is a partial, unverified wall; scripted annotations are marked simulated.
- Exercise Bonsai wall-height and window/opening edits on the real CRASLAB development model. Preserve a failed opening edit, and accept alternative triangulation only after strict vertex, plane, surface and topology checks.
- Add frozen-candidate, reference-isolation and paired-cost evaluation tools. They do not independently establish authoring-tool acceptance or release readiness.

## Unreleased — 2026-11-13

- Add experimental room IR 0.3 with multiple walls, corner propagation, angular/intersection checks, slabs, spaces, doors/windows and IFC opening/filling relationships; preserve earlier Core and product contracts.
- Import the real CRASLAB Cloud2BIM output into the IR, quarantine invalid source objects, recompile IFC4 and perform a Bonsai multi-object wall edit/readback. Source classes and dimensions remain unverified.
- Add a loopback Studio that renders IFC triangles, edits versioned parameters, previews an explicitly selected point cloud and keeps uploaded photos unassociated. Its local command parser is not DSH; the deployed DSH web and gateway require authentication.
- Start reproducible real-image research with a calibrated sparse two-view baseline, a CPU relative-depth model, and a manually selected RGB-D surface candidate. See the [benchmark](../../benchmarks/bim_real_room/README.md) for inputs, licensing, results and failure cases.
- Document the product/Core/Harness boundaries and draft product roadmap; preserve the existing `worldstate-bim-proposal/0.1` contract and synthetic IFC exporter.
- Add an assisted, real RGB-D-photo-to-IFC local wall patch, actual anchor constraint, parameter revision, stable GUID, local browser and provenance-bearing `parametric-ir/0.2`. The demonstration anchor uses the same depth sensor, not an independent measurement.
- Add CPU COLMAP development evaluation and a CRASLAB real scan-to-semantic-IFC wall patch; retain failed cases and distinguish unconfirmed inferred classes and assumed thickness.
- Exercise web-ifc and Blender/Bonsai read/edit/write. Add IFC wall axis and an unspecified-material geometric layer so Bonsai can change length without losing the extrusion; safely synchronize only that length change back to IR. No complete room, independent measurement acceptance, assessed labor saving or release-ready milestone is claimed.
