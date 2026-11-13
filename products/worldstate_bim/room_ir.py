"""Versioned, evidence-bearing room model and bounded geometric edits.

This product-only IR is separate from the frozen Core and the wall-only v0.2
contract. Unknown geometry is retained; exporters must not invent solids.
"""
from __future__ import annotations

import copy
import math
from typing import Any

SCHEMA = "worldstate-bim-room-ir/0.3"
STATES = {"observed", "inferred", "human_confirmed", "assumed", "simulated", "unknown", "conflict"}
TYPES = {"IfcWall", "IfcSlab", "IfcOpeningElement", "IfcDoor", "IfcWindow", "IfcSpace"}
DIMENSIONS = {"IfcWall": ("height", "thickness", "base_elevation"), "IfcSlab": ("thickness", "elevation"),
              "IfcOpeningElement": ("offset", "width", "height", "sill"),
              "IfcDoor": ("panel_thickness",), "IfcWindow": ("panel_thickness",), "IfcSpace": ()}
NONNEGATIVE = {"offset", "sill"}
SIGNED = {"elevation", "base_elevation"}


def quantity(value: float | None, status: str, refs: list[str], note: str) -> dict[str, Any]:
    """A signed metric quantity with explicit epistemic state and provenance."""
    if status not in STATES or not isinstance(refs, list) or not refs or not note.strip():
        raise ValueError("quantity requires valid status, evidence and a note")
    if status in {"unknown", "conflict"}:
        if value is not None:
            raise ValueError("unknown or conflict cannot be resolved to a value")
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("known quantities must be finite")
    return {"value": float(value) if value is not None else None, "unit": "m", "status": status,
            "evidence_refs": refs, "note": note}


def _ids(items: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(f"{label} must be a list")
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] or item["id"] in result:
            raise ValueError(f"{label} IDs must be unique nonempty strings")
        result[item["id"]] = item
    return result


def validate_room(model: dict[str, Any]) -> None:
    """Validate identity, provenance, geometry contracts and relationships."""
    if model.get("schema") != SCHEMA or model.get("mode") not in {"assisted", "automatic"}:
        raise ValueError("unsupported room IR schema or mode")
    if not isinstance(model.get("project_id"), str) or not model["project_id"].strip():
        raise ValueError("project ID required")
    if not isinstance(model.get("revision"), int) or isinstance(model["revision"], bool) or model["revision"] < 1:
        raise ValueError("positive revision required")
    if model.get("coordinate_system", {}).get("unit") != "m" or not model["coordinate_system"].get("name"):
        raise ValueError("named metric coordinate frame required")
    evidence = _ids(model.get("evidence"), "evidence")
    if not evidence:
        raise ValueError("evidence required")
    nodes = _ids(model.get("nodes"), "nodes")
    storeys = _ids(model.get("storeys"), "storeys")
    elements = _ids(model.get("elements"), "elements")
    if not storeys or not elements:
        raise ValueError("at least one storey and one element required")
    def provenance(item: Any, label: str) -> None:
        if (not isinstance(item, dict) or item.get("status") not in STATES or
                not isinstance(item.get("evidence_refs"), list) or not item["evidence_refs"] or
                not set(item["evidence_refs"]) <= set(evidence)):
            raise ValueError(f"{label} has invalid status or evidence")
    def dimension(item: Any, name: str) -> None:
        provenance(item, name)
        if item.get("unit") != "m":
            raise ValueError(f"{name} unit must be m")
        value = item.get("value")
        if item["status"] in {"unknown", "conflict"}:
            if value is not None:
                raise ValueError(f"{name} cannot resolve unknown/conflict")
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        if name not in SIGNED and (value < 0 if name in NONNEGATIVE else value <= 0):
            raise ValueError(f"{name} must be positive or an allowed zero")
    for node in nodes.values():
        provenance(node, "node")
        for k in ("x", "y"):
            v = node.get(k)
            if node["status"] in {"unknown", "conflict"}:
                if v is not None:
                    raise ValueError("unknown or conflicting node coordinates must be unresolved")
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError("node coordinates must be finite")
    for storey in storeys.values():
        dimension(storey.get("elevation"), "elevation")
    for item in elements.values():
        kind = item.get("ifc_type")
        if kind not in TYPES or item.get("storey") not in storeys:
            raise ValueError("unsupported element or missing storey")
        provenance(item.get("classification"), "classification")
        for name in DIMENSIONS[kind]:
            dimension(item.get("parameters", {}).get(name), name)
        if kind == "IfcWall":
            if item.get("start") not in nodes or item.get("end") not in nodes or item["start"] == item["end"]:
                raise ValueError("wall endpoints must reference distinct nodes")
            if item.get("axis_reference", "face") not in {"face", "centerline"}:
                raise ValueError("wall axis reference must be face or centerline")
        if kind == "IfcSlab":
            outline = item.get("outline")
            if not isinstance(outline, list) or len(outline) < 3 or any(n not in nodes for n in outline) or len(set(outline)) < 3:
                raise ValueError("slab needs at least three distinct observed or explicitly assumed outline nodes")
            provenance(item.get("outline_status"), "slab outline")
        if kind == "IfcOpeningElement":
            if elements.get(item.get("host"), {}).get("ifc_type") != "IfcWall":
                raise ValueError("opening needs a host wall")
            fill = item.get("fill")
            if fill is not None and (elements.get(fill, {}).get("ifc_type") not in {"IfcDoor", "IfcWindow"} or elements[fill].get("opening") != item["id"]):
                raise ValueError("opening and filling relationship is inconsistent")
        if kind in {"IfcDoor", "IfcWindow"}:
            if elements.get(item.get("opening"), {}).get("ifc_type") != "IfcOpeningElement" or elements[item["opening"]].get("fill") != item["id"]:
                raise ValueError("filling must point to its opening")
        if kind == "IfcSpace":
            walls = item.get("boundary_walls")
            if (not isinstance(walls, list) or len(set(walls)) != len(walls) or
                    any(elements.get(w, {}).get("ifc_type") != "IfcWall" for w in walls)):
                raise ValueError("space boundary must reference walls")
            if item.get("boundary_status") not in {"open", "closed_confirmed", "unknown"}:
                raise ValueError("space boundary state is required")
    constraints = _ids(model.get("constraints", []), "constraints")
    for constraint in constraints.values():
        provenance(constraint, "constraint")
        kind = constraint.get("kind")
        if kind in {"parallel", "perpendicular", "intersection"}:
            if any(elements.get(constraint.get(k), {}).get("ifc_type") != "IfcWall" for k in ("a", "b")) or constraint["a"] == constraint["b"]:
                raise ValueError("angular constraint needs two distinct walls")
        elif kind == "coincident":
            if constraint.get("a") not in nodes or constraint.get("b") not in nodes:
                raise ValueError("coincident constraint needs two nodes")
        else:
            raise ValueError("unsupported constraint")


def geometry_issues(model: dict[str, Any], *, tolerance: float = 1e-5) -> list[dict[str, str]]:
    """Report wall/opening/constraint problems without guessing unknown values."""
    validate_room(model)
    nodes = {x["id"]: x for x in model["nodes"]}
    elements = {x["id"]: x for x in model["elements"]}
    issues: list[dict[str, str]] = []
    def point(n):
        return (nodes[n]["x"], nodes[n]["y"])
    def vector(w):
        a, b = point(w["start"]), point(w["end"])
        if None in a or None in b:
            return None
        return (b[0]-a[0], b[1]-a[1])
    for e in elements.values():
        if e["ifc_type"] == "IfcWall":
            v = vector(e)
            if v is None:
                issues.append({"id": e["id"], "code": "UNKNOWN_WALL_COORDINATE"})
            elif math.hypot(*v) <= tolerance:
                issues.append({"id": e["id"], "code": "ZERO_WALL"})
        if e["ifc_type"] == "IfcOpeningElement":
            p = e["parameters"]
            if any(p[k]["value"] is None for k in ("offset", "width", "height", "sill")):
                issues.append({"id": e["id"], "code": "UNKNOWN_OPENING_DIMENSION"})
                continue
            wall = elements[e["host"]]
            v = vector(wall)
            if v is None:
                issues.append({"id": e["id"], "code": "UNKNOWN_HOST_COORDINATE"})
                continue
            length = math.hypot(*v)
            wall_height = wall["parameters"]["height"]["value"]
            if p["offset"]["value"] + p["width"]["value"] > length + tolerance:
                issues.append({"id": e["id"], "code": "OPENING_OUTSIDE_WALL"})
            if wall_height is None or p["sill"]["value"] + p["height"]["value"] > wall_height + tolerance:
                issues.append({"id": e["id"], "code": "OPENING_ABOVE_WALL"})
        if e["ifc_type"] == "IfcSlab":
            from shapely.geometry import Polygon
            vertices = [point(n) for n in e["outline"]]
            if any(None in p for p in vertices):
                issues.append({"id": e["id"], "code": "UNKNOWN_SLAB_BOUNDARY"})
            else:
                polygon = Polygon(vertices)
                if not polygon.is_valid or polygon.area <= tolerance*tolerance:
                    issues.append({"id": e["id"], "code": "INVALID_SLAB_BOUNDARY"})
        if e["ifc_type"] == "IfcSpace" and e["boundary_status"] == "closed_confirmed":
            wall_ids = e["boundary_walls"]
            adjacency: dict[str, set[str]] = {}
            for wall_id in wall_ids:
                wall = elements[wall_id]
                adjacency.setdefault(wall["start"], set()).add(wall["end"])
                adjacency.setdefault(wall["end"], set()).add(wall["start"])
            if len(wall_ids) < 3 or any(len(v) != 2 for v in adjacency.values()):
                issues.append({"id": e["id"], "code": "ROOM_BOUNDARY_NOT_CLOSED"})
            elif adjacency:
                pending, seen = [next(iter(adjacency))], set()
                while pending:
                    node = pending.pop()
                    if node not in seen:
                        seen.add(node)
                        pending.extend(adjacency[node] - seen)
                if len(seen) != len(adjacency):
                    issues.append({"id": e["id"], "code": "ROOM_BOUNDARY_DISCONNECTED"})
    openings = [e for e in elements.values() if e["ifc_type"] == "IfcOpeningElement"]
    for i, a in enumerate(openings):
        for b in openings[i+1:]:
            if a["host"] != b["host"]:
                continue
            pa, pb = a["parameters"], b["parameters"]
            if any(pa[k]["value"] is None or pb[k]["value"] is None for k in ("offset", "width", "sill", "height")):
                continue
            overlap_x = min(pa["offset"]["value"]+pa["width"]["value"], pb["offset"]["value"]+pb["width"]["value"]) - max(pa["offset"]["value"], pb["offset"]["value"])
            overlap_z = min(pa["sill"]["value"]+pa["height"]["value"], pb["sill"]["value"]+pb["height"]["value"]) - max(pa["sill"]["value"], pb["sill"]["value"])
            if overlap_x > tolerance and overlap_z > tolerance:
                issues.append({"id": a["id"]+":"+b["id"], "code": "OPENINGS_OVERLAP"})
    for c in model.get("constraints", []):
        if c["kind"] == "coincident":
            if None in point(c["a"]) or None in point(c["b"]) or math.dist(point(c["a"]), point(c["b"])) > tolerance:
                issues.append({"id": c["id"], "code": "COINCIDENCE_CONFLICT"})
        else:
            v, w = vector(elements[c["a"]]), vector(elements[c["b"]])
            if v is None or w is None:
                issues.append({"id": c["id"], "code": "UNKNOWN_CONSTRAINT_COORDINATE"})
                continue
            denom = math.hypot(*v)*math.hypot(*w)
            if denom <= tolerance*tolerance:
                issues.append({"id": c["id"], "code": "DEGENERATE_CONSTRAINT"})
                continue
            if c["kind"] == "intersection":
                cross = v[0]*w[1]-v[1]*w[0]
                a = point(elements[c["a"]]["start"]); b = point(elements[c["b"]]["start"])
                delta = (b[0]-a[0], b[1]-a[1])
                if abs(cross) <= tolerance or not (-tolerance <= (delta[0]*w[1]-delta[1]*w[0])/cross <= 1+tolerance and
                                                   -tolerance <= (delta[0]*v[1]-delta[1]*v[0])/cross <= 1+tolerance):
                    issues.append({"id": c["id"], "code": "INTERSECTION_CONFLICT"})
                continue
            score = (v[0]*w[0]+v[1]*w[1])/denom if c["kind"] == "perpendicular" else (v[0]*w[1]-v[1]*w[0])/denom
            if abs(score) > tolerance:
                issues.append({"id": c["id"], "code": "ANGULAR_CONSTRAINT_CONFLICT"})
    return issues


def revise_element(model: dict[str, Any], element_id: str, attribute: str, value: float,
                   *, reason: str, operator: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a revision, propagating shared corners and angular constraints."""
    validate_room(model)
    if operator not in {"user", "analyst"} or not isinstance(reason, str) or not reason.strip():
        raise ValueError("revision operator and reason required")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("finite numeric revision required")
    result = copy.deepcopy(model)
    nodes = {n["id"]: n for n in result["nodes"]}
    elements = {e["id"]: e for e in result["elements"]}
    if element_id not in elements:
        raise ValueError("element not found")
    element = elements[element_id]
    kind = element["ifc_type"]
    ref = f"revision-{result['revision'] + 1}"
    result["evidence"].append({"id": ref, "kind": "manual_revision", "operator": operator, "reason": reason})
    status = "human_confirmed" if operator == "user" else "inferred"
    changed_nodes: set[str] = set()
    if kind == "IfcWall" and attribute == "length":
        if value <= 0:
            raise ValueError("wall length must be positive")
        a, b = nodes[element["start"]], nodes[element["end"]]
        dx, dy = b["x"]-a["x"], b["y"]-a["y"]
        old = math.hypot(dx, dy)
        if old <= 1e-9:
            raise ValueError("cannot resize degenerate wall")
        b["x"], b["y"] = a["x"] + dx*value/old, a["y"] + dy*value/old
        changed_nodes.add(b["id"])
        # Solve connected angular/coincidence constraints while holding the edited
        # wall's start/end fixed and minimizing movement of other nodes.
        if result.get("constraints"):
            from scipy.optimize import least_squares
            import numpy as np
            fixed = {element["start"], element["end"]}
            keys = [k for k in nodes if k not in fixed]
            original = {k: (nodes[k]["x"], nodes[k]["y"]) for k in keys}
            if keys:
                x0 = np.asarray([coord for k in keys for coord in original[k]], dtype=float)
                def residual(x):
                    pos = {k: (nodes[k]["x"], nodes[k]["y"]) for k in fixed}
                    pos.update({k: (x[2*i], x[2*i+1]) for i, k in enumerate(keys)})
                    out = ((x-x0)*0.001).tolist()
                    for c in result["constraints"]:
                        if c["kind"] == "coincident":
                            pa, pb = pos[c["a"]], pos[c["b"]]
                            out.extend([pa[0]-pb[0], pa[1]-pb[1]])
                        elif c["kind"] != "intersection":
                            wa, wb = elements[c["a"]], elements[c["b"]]
                            va = np.asarray(pos[wa["end"]])-pos[wa["start"]]
                            vb = np.asarray(pos[wb["end"]])-pos[wb["start"]]
                            denominator = max(float(np.linalg.norm(va)*np.linalg.norm(vb)), 1e-12)
                            out.append(float((np.dot(va,vb) if c["kind"] == "perpendicular" else va[0]*vb[1]-va[1]*vb[0])/denominator))
                    return out
                solved = least_squares(residual, x0, max_nfev=300, ftol=1e-12, xtol=1e-12, gtol=1e-12)
                if not solved.success:
                    raise ValueError("geometry constraint solver did not converge")
                for i, key in enumerate(keys):
                    nodes[key]["x"], nodes[key]["y"] = map(float, solved.x[2*i:2*i+2])
                    if math.dist(original[key], (nodes[key]["x"], nodes[key]["y"])) > 1e-7:
                        changed_nodes.add(key)
        for node_id in changed_nodes:
            nodes[node_id]["status"] = status if node_id == b["id"] else "inferred"
            nodes[node_id]["evidence_refs"].append(ref)
        before, after = old, float(value)
    else:
        if attribute not in DIMENSIONS[kind]:
            raise ValueError("unsupported element parameter")
        old_param = element["parameters"][attribute]
        before = old_param["value"]
        element["parameters"][attribute] = quantity(value, status, old_param["evidence_refs"]+[ref], reason)
        after = float(value)
    result["revision"] += 1
    result["validation"] = {"status": "REQUIRES_REVALIDATION"}
    validate_room(result)
    issues = geometry_issues(result)
    if issues:
        raise ValueError("revision creates geometric conflicts: " + ", ".join(f"{x['id']}:{x['code']}" for x in issues))
    affected = {element_id}
    for e in elements.values():
        if e["ifc_type"] == "IfcWall" and ({e["start"], e["end"]} & changed_nodes):
            affected.add(e["id"])
        if e["ifc_type"] == "IfcSlab" and set(e["outline"]) & changed_nodes:
            affected.add(e["id"])
    for e in elements.values():
        if e["ifc_type"] == "IfcOpeningElement" and e["host"] in affected:
            affected.add(e["id"])
            if e.get("fill"):
                affected.add(e["fill"])
        if e["ifc_type"] == "IfcSpace" and set(e["boundary_walls"]) & affected:
            affected.add(e["id"])
    diff = {"previous_revision": model["revision"], "revision": result["revision"], "element_id": element_id,
            "attribute": attribute, "before": before, "after": after, "changed_nodes": sorted(changed_nodes),
            "affected_elements": sorted(affected), "reason_ref": ref}
    result.setdefault("history", []).append(diff)
    return result, diff
