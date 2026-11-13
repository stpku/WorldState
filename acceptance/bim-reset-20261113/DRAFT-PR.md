# Start Evidence-to-Editable World BIM research

Target: `main` ← `feat/worldstate-bim-vertical-slice-20261111`

State: **draft**, V0.2 not complete.

Start WorldState BIM's evidence-to-editable product direction while keeping the domain-neutral Core and its existing contracts unchanged. This draft brings together the existing synthetic proposal-to-IFC prototype, the product-scope ADR and roadmap, and reproducible experiments using real, publicly sourced room evidence.

## Evidence

- Two RGB photos produce sparse geometry: 66 triangulated points, 0.299 px median reprojection error and 0.338 m median depth error over 52 valid points using an oracle trajectory baseline.
- A CPU monocular model produces relative depth on the same image; reported metric depth uses dense same-frame sensor calibration and is not a fair independent comparison with the two-view route.
- An operator-selected RGB-D region produces a visible surface candidate; complete wall dimensions, semantic certainty and IFC output remain unknown.
- Committed-head verification: 146 tests passed, with four IfcOpenShell deprecation warnings. Inputs and model weights stay outside the repository; the benchmark records versions, licensing and SHA-256 hashes.

## Remaining before V0.2

- Obtain an authorized, fully observable room with independent scale, dimensional ground truth and held-out photos.
- Produce and independently edit/read back a real-photo-driven semantic IFC; measure dimensions, evidence coverage and human effort.
- Run the multimodal/Harness-to-IFC route and compare a current multi-view foundation model and COLMAP. The local DSH headless probe failed due to a missing provider credential.

This is research in progress and is not release-ready or a production cutover.
