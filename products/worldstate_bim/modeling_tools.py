"""Bounded modeling operations suitable for an external Harness.

No sessions, network calls or agent loop live here. Tools exchange JSON-safe
room IR and deterministic validation results. An external agent may propose a
change but cannot bypass constraints, approval semantics or IFC compilation.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .room_ifc import export_room
from .room_ir import geometry_issues, revise_element, validate_room
from .room_sync import sync_external_ifc


def inspect_evidence(model: dict) -> list[dict]:
    """Return known provenance and uncertainty, without fetching source data."""
    validate_room(model)
    return copy.deepcopy(model["evidence"])


def propose_elements(model: dict) -> dict:
    """List existing unconfirmed candidates; this performs no new inference."""
    validate_room(model)
    candidates=[{"id":e["id"],"ifc_type":e["ifc_type"],"classification":e["classification"],
                 "unknown":e.get("unknown",[])} for e in model["elements"]
                if e["classification"]["status"] in {"inferred","assumed","unknown","conflict"}]
    return {"source":"existing_ir_only", "new_inference":False, "candidates":candidates,
            "quarantined":copy.deepcopy(model.get("quarantined",[]))}


def inspect_element(model: dict, element_id: str) -> dict:
    """Return a single element, its linked geometry and source IDs."""
    validate_room(model)
    selected=next((e for e in model["elements"] if e["id"]==element_id),None)
    if selected is None:raise ValueError("element not found")
    node_ids={selected.get("start"),selected.get("end")} | set(selected.get("outline",[]))
    return {"element":copy.deepcopy(selected),
            "nodes":[copy.deepcopy(n) for n in model["nodes"] if n["id"] in node_ids],
            "constraints":[copy.deepcopy(c) for c in model.get("constraints",[]) if element_id in {c.get("a"),c.get("b")}],
            "issues":[i for i in geometry_issues(model) if element_id in i["id"]]}


def apply_constraint(model: dict, *, kind: str, a: str, b: str, reason: str,
                     operator: str) -> tuple[dict,dict]:
    """Add a user-provided constraint only when current geometry satisfies it."""
    validate_room(model)
    if operator not in {"user","analyst"} or not isinstance(reason,str) or not reason.strip():
        raise ValueError("constraint requires an operator and reason")
    result=copy.deepcopy(model);revision=result["revision"]+1
    ref=f"revision-{revision}"
    result["evidence"].append({"id":ref,"kind":"constraint_revision","operator":operator,"reason":reason})
    constraint={"id":f"constraint-{revision}","kind":kind,"a":a,"b":b,
                "status":"human_confirmed" if operator=="user" else "inferred","evidence_refs":[ref]}
    result.setdefault("constraints",[]).append(constraint)
    result["revision"]=revision;result["validation"]={"status":"REQUIRES_REVALIDATION"}
    validate_room(result)
    issues=geometry_issues(result)
    if issues:raise ValueError("constraint conflict: "+json.dumps(issues))
    diff={"previous_revision":model["revision"],"revision":revision,"constraint":constraint,"reason_ref":ref}
    result.setdefault("history",[]).append(diff)
    return result,diff


def update_element(model: dict, element_id: str, attribute: str, value: float,
                   *,reason: str,operator: str) -> tuple[dict,dict]:
    """Revise a supported attribute with dependency propagation and checks."""
    return revise_element(model,element_id,attribute,value,reason=reason,operator=operator)


def validate_geometry(model: dict) -> dict:
    """Report explicit geometric conflicts, not engineering certification."""
    issues=geometry_issues(model)
    return {"status":"CONFLICT" if issues else "UNVERIFIED_DRAFT","issues":issues,
            "warning":"Passing geometric checks does not independently verify scene accuracy."}


def compile_ifc(model: dict, output: Path) -> Path:
    """Compile a validated draft to a new local IFC file."""
    return export_room(model,output)


def compare_revisions(before: dict, after: dict) -> dict:
    """Compare all product objects and nodes by stable ID."""
    validate_room(before);validate_room(after)
    if before["project_id"]!=after["project_id"]:
        raise ValueError("revisions belong to different projects")
    def changes(key):
        a={x["id"]:x for x in before[key]};b={x["id"]:x for x in after[key]}
        return {"added":sorted(set(b)-set(a)),"removed":sorted(set(a)-set(b)),
                "changed":sorted(k for k in set(a)&set(b) if a[k]!=b[k])}
    return {"from_revision":before["revision"],"to_revision":after["revision"],
            "elements":changes("elements"),"nodes":changes("nodes"),
            "history":copy.deepcopy(after.get("history",[]))}


def sync_ifc(model: dict, baseline_ifc: Path, edited_ifc: Path, *,element_id: str,
             attribute: str,reason: str,operator: str) -> tuple[dict,dict]:
    """Read back one supported external edit after whole-model checks."""
    return sync_external_ifc(model,baseline_ifc,edited_ifc,element_id=element_id,
                             attribute=attribute,reason=reason,operator=operator)
