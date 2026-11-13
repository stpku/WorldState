"""Conservative geometric baseline for one visible wall patch from metric XYZ.

This is not a complete Scan-to-BIM system. A vertical surface may be a board,
door, or other object. The wall class is an unconfirmed geometric inference.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from .parametric_ir import SCHEMA, digest, parameter, validate_ir
from .ifc_export import _add_editable_wall_axis


def infer_visible_wall(points: np.ndarray, *, seed: int = 20261113,
                       threshold_m: float = 0.04) -> tuple[dict[str, Any], np.ndarray]:
    """Select one dense vertical planar patch from XYZ only, returning its mask.

    Horizontal coordinates are X/Y, and Z is assumed to be gravity-aligned.
    RANSAC scoring and spatial selection never consume semantic labels.
    """
    xyz = np.asarray(points, dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 100 or not np.isfinite(xyz).all():
        raise ValueError("at least 100 finite XYZ points are required")
    if not np.isfinite(threshold_m) or threshold_m <= 0:
        raise ValueError("threshold must be positive")
    rng = np.random.default_rng(seed)
    fit = xyz[rng.choice(len(xyz), min(len(xyz), 16000), replace=False)]
    pairs = rng.integers(0, len(fit), size=(1800, 2))
    a, b = fit[pairs[:, 0], :2], fit[pairs[:, 1], :2]
    delta = b - a
    norm = np.linalg.norm(delta, axis=1)
    eligible = norm > 1.0
    if not np.any(eligible):
        raise ValueError("points do not span a metre in the horizontal plane")
    a, delta, norm = a[eligible], delta[eligible], norm[eligible]
    normals = np.column_stack((delta[:, 1], -delta[:, 0])) / norm[:, None]
    offsets = (normals * a).sum(axis=1)
    scores: list[int] = []
    for i in range(0, len(normals), 64):
        residual = np.abs(fit[:, :2] @ normals[i:i+64].T - offsets[i:i+64])
        scores.extend((residual < threshold_m).sum(axis=0).tolist())
    best = int(np.argmax(scores))
    normal, offset = normals[best], float(offsets[best])
    tangent = np.array([-normal[1], normal[0]])
    u = xyz[:, :2] @ tangent
    near = np.abs(xyz[:, :2] @ normal - offset) < threshold_m
    # Restrict the infinite plane to a 2.5 m support region, selected purely by
    # point density. It is a visible patch, not a complete wall boundary.
    lo, hi = np.floor(u[near].min()*4)/4, np.ceil(u[near].max()*4)/4
    edges = np.arange(lo, hi + .251, .25)
    if len(edges) < 11:
        raise ValueError("candidate is too short to select a 2.5 m region")
    hist, _ = np.histogram(u[near], bins=edges)
    window = np.convolve(hist, np.ones(10, dtype=int), mode="valid")
    start_index = int(np.argmax(window))
    selected = near & (u >= edges[start_index]) & (u < edges[start_index + 10])
    if selected.sum() < 100:
        raise ValueError("insufficient support for a visible wall patch")
    u0, u1 = np.percentile(u[selected], [2, 98])
    z0, z1 = np.percentile(xyz[selected, 2], [2, 98])
    selected &= (u >= u0) & (u <= u1) & (xyz[:, 2] >= z0) & (xyz[:, 2] <= z1)
    p0, p1 = normal * offset + tangent * u0, normal * offset + tangent * u1
    return ({"start_m": [float(p0[0]), float(p0[1]), float(z0)],
             "end_m": [float(p1[0]), float(p1[1]), float(z0)],
             "length_m": float(u1-u0), "visible_height_m": float(z1-z0),
             "normal_xy": normal.tolist(), "plane_offset_m": offset,
             "plane_threshold_m": threshold_m, "support_count": int(selected.sum()),
             "fit_seed": seed, "scope": "single_visible_patch"}, selected)


def make_scan_ir(candidate: dict[str, Any], xyz_file: Path, *, project_id: str,
                 source_url: str, archive_sha256: str, thickness_m: float = .12) -> dict[str, Any]:
    """Create the common product IR with explicit native metric scan provenance."""
    refs = ["scan-1", "algorithm-1"]
    model: dict[str, Any] = {
        "schema": SCHEMA, "project_id": project_id, "mode": "automatic", "revision": 1,
        "evidence": [
            {"id": "scan-1", "kind": "metric_point_cloud", "unit": "m", "sha256": digest(xyz_file),
             "source_url": source_url, "source_archive_sha256": archive_sha256,
             "note": "native sensor coordinates; dataset documentation states metres"},
            {"id": "algorithm-1", "kind": "geometric_inference", "description": "vertical plane and dense patch; no semantic labels used"},
            {"id": "thickness-assumption", "kind": "assumption", "description": "solid thickness not measured"}],
        "scale": {"status": "native_metric", "source_ref": "scan-1", "metres_per_unit": 1.0},
        "coordinate_system": {"name": "source_scan", "unit": "m", "z_axis": "assumed vertical",
                              "registration_to_reference_ifc": "UNKNOWN"},
        "elements": [{"id": "scan-wall-patch-1", "ifc_type": "IfcWall", "scope": "visible_patch_only",
                      "classification": {"status": "inferred", "evidence_refs": refs,
                                         "note": "vertical-plane heuristic; not human-confirmed; may be furniture or a door"},
                      "start_m": candidate["start_m"], "end_m": candidate["end_m"],
                      "parameters": {"length": parameter(candidate["length_m"], "inferred", refs, note="visible support only"),
                                     "visible_height": parameter(candidate["visible_height_m"], "inferred", refs, note="visible support only"),
                                     "thickness": parameter(thickness_m, "assumed", ["thickness-assumption"], note="not measured")},
                      "unknown": ["full wall extent", "actual thickness", "openings", "reference IFC registration"],
                      "relations": {"storey": "storey-assumed"}, "depends_on": refs}],
        "validation": {"status": "UNVERIFIED_DRAFT", "method": "vertical geometric prior",
                       "warning": "no claim of complete room or independently measured geometric error"},
        "planned_unimplemented_types": ["IfcSlab", "IfcDoor", "IfcWindow", "IfcOpeningElement", "IfcSpace"]}
    validate_ir(model)
    return model


def export_scan_ifc(model: dict[str, Any], destination: Path) -> None:
    """Export a single inferred scan patch as a semantic IFC4 IfcWall."""
    validate_ir(model)
    if model["scale"].get("status") != "native_metric" or len(model["elements"]) != 1:
        raise ValueError("one native-metric scan wall is required")
    element = model["elements"][0]
    if any(element["parameters"][name]["status"] in {"unknown", "conflict"}
           for name in ("length", "visible_height", "thickness")):
        raise ValueError("cannot export a wall solid with unknown or conflicting dimensions")
    p1, p2 = element.get("start_m"), element.get("end_m")
    if (not isinstance(p1, list) or not isinstance(p2, list) or len(p1) != 3 or len(p2) != 3 or
            any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in p1+p2) or
            not math.isclose(p1[2], p2[2], abs_tol=1e-9) or
            not math.isclose(math.dist(p1[:2], p2[:2]), element["parameters"]["length"]["value"], rel_tol=1e-9)):
        raise ValueError("scan wall endpoints must agree with the finite metric length")
    if destination.exists():
        raise FileExistsError(destination)
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    import ifcopenshell.api.project
    import ifcopenshell.api.pset
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.unit
    import ifcopenshell.guid

    f = ifcopenshell.api.project.create_file(version="IFC4")
    stable = lambda name: ifcopenshell.guid.compress(uuid5(NAMESPACE_URL, f"worldstate-bim:{model['project_id']}:{name}").hex)
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="WorldState scan patch")
    project.GlobalId = stable("project")
    units = [ifcopenshell.api.unit.add_si_unit(f, unit_type=x) for x in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT")]
    ifcopenshell.api.unit.assign_unit(f, units=units)
    context = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=context)
    plan = ifcopenshell.api.context.add_context(f, context_type="Plan")
    axis = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis", target_view="GRAPH_VIEW", parent=plan)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Assumed storey")
    for name, obj in (("site", site), ("building", building), ("storey", storey)):
        obj.GlobalId = stable(name)
    for parent, child in ((project, site), (site, building), (building, storey)):
        ifcopenshell.api.aggregate.assign_object(f, products=[child], relating_object=parent)
    e = model["elements"][0]
    wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=e["id"])
    wall.GlobalId = stable("wall:" + e["id"])
    rep = ifcopenshell.api.geometry.create_2pt_wall(f, element=wall, context=body,
        p1=e["start_m"][:2], p2=e["end_m"][:2], elevation=e["start_m"][2],
        height=e["parameters"]["visible_height"]["value"], thickness=e["parameters"]["thickness"]["value"], is_si=True)
    ifcopenshell.api.geometry.assign_representation(f, product=wall, representation=rep)
    _add_editable_wall_axis(f, wall, axis, e["parameters"]["length"]["value"], e["parameters"]["thickness"]["value"])
    ifcopenshell.api.spatial.assign_container(f, products=[wall], relating_structure=storey)
    pset = ifcopenshell.api.pset.add_pset(f, product=wall, name="Pset_WorldStateEvidence")
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"EvidenceManifest": "scan-ir.json",
        "ClassificationStatus": "INFERRED_GEOMETRIC_PRIOR", "Scope": "VISIBLE_PATCH_ONLY",
        "ThicknessStatus": "ASSUMED_NOT_OBSERVED", "ReferenceAlignment": "UNKNOWN"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(destination))
