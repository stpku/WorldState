# WorldState BIM changelog

## Unreleased — 2026-11-13

- Start reproducible real-image research with a calibrated sparse two-view baseline, a CPU relative-depth model, and a manually selected RGB-D surface candidate. See the [benchmark](../../benchmarks/bim_real_room/README.md) for inputs, licensing, results and failure cases.
- Document the product/Core/Harness boundaries and draft product roadmap; preserve the existing `worldstate-bim-proposal/0.1` contract and synthetic IFC exporter.
- Add an assisted, real RGB-D-photo-to-IFC local wall patch, actual anchor constraint, parameter revision, stable GUID, local browser and provenance-bearing `parametric-ir/0.2`. The demonstration anchor uses the same depth sensor, not an independent measurement.
- Add CPU COLMAP development evaluation and a CRASLAB real scan-to-semantic-IFC wall patch; retain failed cases and distinguish unconfirmed inferred classes and assumed thickness.
- Exercise web-ifc and Blender/Bonsai read/edit/write. Add IFC wall axis and an unspecified-material geometric layer so Bonsai can change length without losing the extrusion; safely synchronize only that length change back to IR. No complete room, independent measurement acceptance, assessed labor saving or release-ready milestone is claimed.
