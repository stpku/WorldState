"""Real RGB-D-assisted visible wall patch to versioned IFC4 draft.

The operator selects a visible region and supplies the anchor and thickness.
This is an assisted local patch, not automatic reconstruction of a whole room.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .contract import load_proposal, verify_images
from .ifc_export import export_ifc
from .parametric_ir import SCHEMA, digest, parameter, solve_scale, validate_ir
from .visible_surface import fit_visible_surface

def _raw_point(depth: np.ndarray, x: int, y: int, camera: np.ndarray) -> np.ndarray:
    if not (0 <= y < depth.shape[0] and 0 <= x < depth.shape[1]) or depth[y, x] == 0:
        raise ValueError("anchor pixels must have valid registered depth")
    z = float(depth[y, x])
    return np.array([(x-camera[0, 2])*z/camera[0, 0], (y-camera[1, 2])*z/camera[1, 1], z])


def create_candidate(image_path: Path, depth_path: Path, *, roi: tuple[int, int, int, int],
                     anchor_pixels: tuple[int, int, int, int], anchor_m: float,
                     anchor_description: str, anchor_independence: str, thickness_m: float,
                     project_id: str, operator: str, intrinsics: tuple[float, float, float, float],
                     vision_depth: np.ndarray | None = None,
                     vision_metadata: dict[str, Any] | None = None) -> tuple[dict[str, Any], np.ndarray]:
    """Derive a visible wall candidate from source pixels, depth and a scale anchor."""
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    depth = cv2.imread(str(depth_path), cv2.IMREAD_UNCHANGED)
    if image is None or depth is None or depth.dtype != np.uint16 or image.shape[:2] != depth.shape:
        raise ValueError("registered RGB and uint16 depth evidence of matching size are required")
    if not anchor_description.strip() or anchor_independence not in {"independent_user_declared", "same_sensor"}:
        raise ValueError("anchor provenance and independence status must be explicit")
    if operator not in {"analyst", "user"}:
        raise ValueError("operator must be analyst or user")
    fx, fy, cx, cy = intrinsics
    if not np.isfinite([fx, fy, cx, cy]).all() or fx <= 0 or fy <= 0:
        raise ValueError("explicit, finite pinhole intrinsics with positive focal lengths are required")
    camera = np.array([[fx, 0., cx], [0., fy, cy], [0., 0., 1.]])
    x0, y0, x1, y1 = roi
    h, w = depth.shape
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError("ROI must be inside the input image")
    xa, ya, xb, yb = anchor_pixels
    raw_a, raw_b = _raw_point(depth, xa, ya, camera), _raw_point(depth, xb, yb, camera)
    raw_distance = float(np.linalg.norm(raw_a - raw_b))
    factor = solve_scale(raw_distance, anchor_m)
    mask = np.zeros((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = True
    if (vision_depth is None) != (vision_metadata is None):
        raise ValueError("vision prediction and model provenance must be supplied together")
    if vision_depth is not None:
        if vision_depth.shape != depth.shape or not np.isfinite(vision_depth).all() or vision_metadata.get("id") != "vision-1":
            raise ValueError("invalid local vision output or provenance")
        sample = vision_depth[mask & (depth > 0)]
        if len(sample) < 100:
            raise ValueError("insufficient source depth for vision-assisted filtering")
        median = float(np.median(sample))
        mad = float(np.median(np.abs(sample-median)))
        tolerance = max(abs(median)*0.15, 3*1.4826*mad, 1e-6)
        mask &= np.abs(vision_depth-median) <= tolerance
    surface = fit_visible_surface(depth, mask, camera, depth_factor=1.0/factor)
    rows, cols = np.indices(depth.shape)
    selected = mask & (depth > 0) & (rows % 2 == 0) & (cols % 2 == 0)
    y, x = np.nonzero(selected)
    z = depth[y, x].astype(float)*factor
    points = np.column_stack(((x-cx)*z/fx, (y-cy)*z/fy, z))
    normal, centroid = surface.normal_camera, surface.centroid_camera_m
    points = points[np.abs((points-centroid) @ normal) <= 0.025]
    vertical = np.array([0., -1., 0.])
    vertical -= normal * np.dot(vertical, normal)
    if np.linalg.norm(vertical) < 1e-6:
        raise ValueError("cannot derive a vertical patch from the assumed image-up direction")
    vertical /= np.linalg.norm(vertical)
    horizontal = np.cross(vertical, normal)
    horizontal /= np.linalg.norm(horizontal)
    if horizontal[0] < 0:
        horizontal = -horizontal
    local_y = np.cross(vertical, horizontal)
    uv = np.column_stack(((points-centroid) @ horizontal, (points-centroid) @ vertical))
    low, high = np.percentile(uv, 2, axis=0), np.percentile(uv, 98, axis=0)
    length, visible_height = (high-low).tolist()
    origin = centroid + horizontal*low[0] + vertical*low[1]
    transform = np.eye(4)
    transform[:3, 0], transform[:3, 1], transform[:3, 2], transform[:3, 3] = horizontal, local_y, vertical, origin
    evidence = [
        {"id": "photo-1", "kind": "image", "name": image_path.name, "sha256": digest(image_path),
         "width_px": w, "height_px": h},
        {"id": "depth-1", "kind": "registered_depth", "name": depth_path.name, "sha256": digest(depth_path)},
        {"id": "anchor-1", "kind": "scale_reference", "description": anchor_description,
         "independence": anchor_independence, "pixels": list(anchor_pixels),
         "raw_points": [raw_a.tolist(), raw_b.tolist()], "source_refs": ["depth-1"]},
        {"id": "operator-1", "kind": "manual_selection", "operator": operator, "roi_xyxy": list(roi)},
        {"id": "assumption-1", "kind": "assumption", "description": "wall thickness supplied for a draft solid"},
    ]
    geometry_refs = ["photo-1", "depth-1", "anchor-1", "operator-1"]
    if vision_metadata is not None:
        evidence.append(vision_metadata)
        geometry_refs.append("vision-1")
    model: dict[str, Any] = {
        "schema": SCHEMA, "project_id": project_id, "mode": "assisted", "revision": 1,
        "evidence": evidence,
        "scale": {"status": "applied", "anchor_ref": "anchor-1", "raw_distance": raw_distance,
                  "distance_m": float(anchor_m), "metres_per_unit": factor,
                  "independence": anchor_independence},
        "coordinate_system": {"name": "visible_patch_local", "unit": "m", "local_to_color_camera": transform.tolist(),
                              "intrinsics_fx_fy_cx_cy": list(intrinsics),
                              "vertical_basis": "assumed camera image-up projected onto plane"},
        "elements": [{"id": "wall-patch-1", "ifc_type": "IfcWall", "scope": "visible_patch_only",
                      "classification": {"status": "human_confirmed" if operator == "user" else "inferred",
                                         "note": f"possible wall region manually selected by {operator}",
                                         "evidence_refs": ["photo-1", "operator-1"]},
                      "parameters": {
                          "length": parameter(length, "inferred", geometry_refs, note="visible support only, not complete wall length"),
                          "visible_height": parameter(visible_height, "inferred", geometry_refs, note="visible support only, not storey height"),
                          "thickness": parameter(thickness_m, "assumed", ["assumption-1"], note="explicit modelling assumption, not observed")},
                      "unknown": ["full wall boundary", "actual wall thickness", "full wall height", "building coordinates", "unseen openings"],
                      "relations": {"storey": "storey-ground-assumed"}, "depends_on": ["anchor-1", "depth-1", "operator-1"]}],
        "planned_unimplemented_types": ["IfcSlab", "IfcDoor", "IfcWindow", "IfcOpeningElement", "IfcSpace", "IfcBuildingStorey topology"],
        "validation": {"status": "UNVERIFIED_DRAFT", "depth_samples": surface.valid_depth_samples,
                       "plane_inliers": surface.inlier_samples, "fit_residual_m": surface.median_residual_m,
                       "warning": "fit residual is not independent accuracy; selected patch is not a complete wall"},
    }
    validate_ir(model)
    return model, points


def write_model(model: dict[str, Any], image_root: Path, output_dir: Path) -> tuple[Path, Path]:
    """Validate IR and write a v0.1-compatible semantic wall IFC plus metadata."""
    validate_ir(model)
    ifc_path, ir_path = output_dir / "model.ifc", output_dir / "model.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    if ifc_path.exists() or ir_path.exists():
        raise FileExistsError("output exists; choose a new revision directory")
    image = next(x for x in model["evidence"] if x["id"] == "photo-1")
    for source in (x for x in model["evidence"] if x["kind"] in {"image", "registered_depth"}):
        name = source["name"]
        if Path(name).name != name:
            raise ValueError("evidence path must be a simple filename")
        path = image_root / name
        if not path.is_file() or digest(path) != source["sha256"]:
            raise ValueError("source evidence is missing or its hash changed")
    walls = []
    for item in model["elements"]:
        p = item["parameters"]
        if any(p[key]["status"] in {"unknown", "conflict"} for key in ("length", "visible_height", "thickness")):
            raise ValueError("cannot export a wall solid with unknown or conflicting dimensions")
        walls.append({"element_id": item["id"], "start_m": [0., 0., 0.],
                      "end_m": [p["length"]["value"], 0., 0.],
                      "height_m": p["visible_height"]["value"], "thickness_m": p["thickness"]["value"],
                      "basis": "inferred", "evidence_refs": ["photo-1"]})
    raw = {"contract": "worldstate-bim-proposal/0.1", "project_id": model["project_id"],
           "project_name": "WorldState assisted wall patch", "images": [{"evidence_id": "photo-1",
           "path": image["name"], "sha256": image["sha256"], "captured_at": None,
           "provenance": "source image; full attribute evidence in accompanying IR"}],
           "anchors": [{"evidence_id": "photo-1", "distance_m": model["scale"]["distance_m"],
                        "basis": "measured"}], "walls": walls}
    proposal = load_proposal(raw)
    verify_images(proposal, image_root)
    export_ifc(proposal, ifc_path)
    import ifcopenshell
    import ifcopenshell.api.pset
    f = ifcopenshell.open(str(ifc_path))
    for wall in f.by_type("IfcWall"):
        pset = next(rel.RelatingPropertyDefinition for rel in wall.IsDefinedBy
                    if rel.is_a("IfcRelDefinesByProperties") and rel.RelatingPropertyDefinition.Name == "Pset_WorldStateEvidence")
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Scope": "VISIBLE_PATCH_ONLY", "ThicknessStatus": "ASSUMED_NOT_OBSERVED",
            "HeightStatus": "VISIBLE_PATCH_NOT_COMPLETE_WALL", "EvidenceManifest": "model.json",
            "ScaleIndependence": model["scale"]["independence"],
            "ScaleMetresPerRawUnit": model["scale"]["metres_per_unit"],
        })
    f.write(str(ifc_path))
    ir_path.write_text(json.dumps(model, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return ifc_path, ir_path


def revise_length(model: dict[str, Any], wall_id: str, length_m: float, reason: str,
                  *, operator: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Revise one wall dimension while preserving its identity and previous IR."""
    validate_ir(model)
    if not reason.strip() or operator not in {"analyst", "user"}:
        raise ValueError("manual revision reason and operator are required")
    result = copy.deepcopy(model)
    matches = [w for w in result["elements"] if w["id"] == wall_id]
    if len(matches) != 1:
        raise ValueError("wall ID not found")
    old = matches[0]["parameters"]["length"]
    new_ref = f"revision-{int(result['revision'])+1}"
    result["evidence"].append({"id": new_ref, "kind": "manual_revision", "reason": reason, "operator": operator})
    status = "human_confirmed" if operator == "user" else "inferred"
    new = parameter(length_m, status, old["evidence_refs"] + [new_ref], note="operator revision; not a new field measurement")
    matches[0]["parameters"]["length"] = new
    result["revision"] += 1
    result["validation"]["status"] = "REQUIRES_REVALIDATION"
    validate_ir(result)
    return result, {"wall_id": wall_id, "attribute": "length", "before": old, "after": new,
                    "previous_revision": model["revision"], "revision": result["revision"]}
