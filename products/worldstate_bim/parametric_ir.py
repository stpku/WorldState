"""Versioned, evidence-linked parametric BIM product intermediate model.

Version 0.2 currently implements a single, partial wall patch. Slabs, doors,
windows, openings, rooms, and richer topology are reserved and rejected.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

SCHEMA = "worldstate-bim-parametric-ir/0.2"
STATES = {"observed", "inferred", "human_confirmed", "assumed", "simulated", "unknown", "conflict"}


def digest(path: Path) -> str:
    """Hash an evidence file without retaining it in the repository."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def solve_scale(raw_distance: float, measured_distance_m: float) -> float:
    """Compute metres per reconstruction unit from an explicitly sourced anchor."""
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0
           for x in (raw_distance, measured_distance_m)):
        raise ValueError("anchor distances must be finite and positive")
    return measured_distance_m / raw_distance


def parameter(value: float | None, status: str, refs: list[str], *, note: str,
              alternatives: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create an evidence-bearing metric parameter."""
    if status not in STATES or not refs or not note.strip():
        raise ValueError("parameter requires a known epistemic status, source and note")
    if status in {"unknown", "conflict"}:
        if value is not None:
            raise ValueError("unknown or conflicting parameters cannot contain a resolved value")
        if status == "conflict" and (not isinstance(alternatives, list) or len(alternatives) < 2):
            raise ValueError("conflict requires at least two sourced alternatives")
        if status == "conflict":
            values = []
            for alternative in alternatives:
                if not isinstance(alternative, dict) or not alternative.get("evidence_refs"):
                    raise ValueError("each conflicting alternative needs evidence")
                candidate = alternative.get("value")
                if isinstance(candidate, bool) or not isinstance(candidate, (int, float)) or not math.isfinite(candidate) or candidate <= 0:
                    raise ValueError("each conflicting alternative must be a positive finite length")
                values.append(float(candidate))
            if len(set(values)) < 2:
                raise ValueError("conflicting alternatives must disagree")
        return {"value": None, "unit": "m", "status": status, "evidence_refs": refs, "note": note,
                **({"alternatives": alternatives} if alternatives is not None else {})}
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("implemented dimensions must be finite and positive")
    return {"value": float(value), "unit": "m", "status": status, "evidence_refs": refs, "note": note}


def validate_ir(model: dict[str, Any]) -> None:
    """Reject unsupported components, untraceable dimensions, and unscaled drafts."""
    if model.get("schema") != SCHEMA or model.get("mode") not in {"assisted", "automatic"}:
        raise ValueError("unsupported model schema or mode")
    if not isinstance(model.get("project_id"), str) or not model["project_id"].strip():
        raise ValueError("project_id is required")
    evidence = model.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("evidence is required")
    refs = {e.get("id") for e in evidence if isinstance(e, dict)}
    if None in refs or len(refs) != len(evidence):
        raise ValueError("evidence IDs must be unique")
    scale = model.get("scale", {})
    if scale.get("status") == "native_metric":
        source = next((e for e in evidence if e["id"] == scale.get("source_ref")), None)
        if (not source or source.get("kind") != "metric_point_cloud" or
                source.get("unit") != "m" or not source.get("source_url") or not source.get("sha256") or
                isinstance(scale.get("metres_per_unit"), bool) or scale.get("metres_per_unit") != 1.0):
            raise ValueError("native metric scale requires sourced metre point-cloud metadata")
    else:
        if scale.get("status") != "applied" or scale.get("anchor_ref") not in refs:
            raise ValueError("a sourced and applied scale anchor is required")
        factor = solve_scale(scale.get("raw_distance"), scale.get("distance_m"))
        if not math.isclose(factor, scale.get("metres_per_unit", -1), rel_tol=1e-9):
            raise ValueError("recorded scale does not match the anchor constraint")
        anchor = next(e for e in evidence if e["id"] == scale["anchor_ref"])
        points = anchor.get("raw_points")
        if (not isinstance(points, list) or len(points) != 2 or
                any(not isinstance(p, list) or len(p) != 3 or
                    any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in p)
                    for p in points)):
            raise ValueError("anchor must record two finite source-space coordinates")
        if not math.isclose(math.dist(*points), scale["raw_distance"], rel_tol=1e-9):
            raise ValueError("anchor coordinates do not match recorded distance")
        if scale.get("independence") != anchor.get("independence"):
            raise ValueError("anchor independence status is inconsistent")
    walls = model.get("elements")
    if not isinstance(walls, list) or not walls:
        raise ValueError("at least one wall candidate is required")
    ids: set[str] = set()
    for wall in walls:
        if wall.get("ifc_type") != "IfcWall":
            raise ValueError("only IfcWall is implemented in IR 0.2")
        if not isinstance(wall.get("id"), str) or not wall["id"].strip() or wall["id"] in ids:
            raise ValueError("wall IDs must be unique and nonempty")
        ids.add(wall["id"])
        for key in ("length", "visible_height", "thickness"):
            item = wall.get("parameters", {}).get(key, {})
            if item.get("unit") != "m" or not set(item.get("evidence_refs", [])) <= refs:
                raise ValueError(f"{key} has invalid units or unknown evidence")
            if any(not set(a.get("evidence_refs", [])) <= refs for a in item.get("alternatives", []) if isinstance(a, dict)):
                raise ValueError(f"{key} has an untraceable conflicting alternative")
            parameter(item.get("value"), item.get("status"), item.get("evidence_refs", []),
                      note=item.get("note", ""), alternatives=item.get("alternatives"))
