"""Bounded modeling operations suitable for an external Harness.

No sessions, network calls or agent loop live here. Tools exchange JSON-safe
room IR and deterministic validation results. An external agent may propose a
change but cannot bypass constraints, approval semantics or IFC compilation.
"""
from __future__ import annotations

import copy
import json
import math
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
    related=[]
    for e in model['elements']:
        if (e.get('host') == element_id or e.get('opening') == element_id or
            e['id'] in {selected.get('host'), selected.get('fill'), selected.get('opening')} or
            (e.get('ifc_type') == 'IfcWall' and e['id'] != element_id and
             node_ids.intersection({e.get('start'), e.get('end')}) - {None})):
            related.append({'id':e['id'], 'ifc_type':e['ifc_type'],
                            'host':e.get('host'), 'fill':e.get('fill'), 'opening':e.get('opening')})
    dimensions={};reference_geometry=None
    if selected['ifc_type'] == 'IfcWall':
        nodes={n['id']:n for n in model['nodes']};a=nodes[selected['start']];b=nodes[selected['end']]
        if all(isinstance(n.get(k),(float,int)) for n in (a,b) for k in ('x','y')):
            dimensions={'length_m':math.hypot(b['x']-a['x'],b['y']-a['y']),
                        'position_x_m':a['x'], 'position_y_m':a['y']}
            reference_geometry={'kind':'wall_axis_xy_m','start':[a['x'],a['y']],'end':[b['x'],b['y']]}
    if selected['ifc_type'] in {'IfcOpeningElement','IfcDoor','IfcWindow'}:
        by_id={e['id']:e for e in model['elements']}
        opening=selected if selected['ifc_type']=='IfcOpeningElement' else by_id[selected['opening']]
        wall=by_id[opening['host']];nodes={n['id']:n for n in model['nodes']}
        a,b=nodes[wall['start']],nodes[wall['end']];p=opening['parameters']
        values=[a.get('x'),a.get('y'),b.get('x'),b.get('y'),p['offset']['value'],p['width']['value'],
                p['sill']['value'],p['height']['value'],wall['parameters']['base_elevation']['value']]
        if all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
            dx,dy=b['x']-a['x'],b['y']-a['y'];length=math.hypot(dx,dy)
            if length>1e-9:
                x,y=a['x']+dx*p['offset']['value']/length,a['y']+dy*p['offset']['value']/length
                z=wall['parameters']['base_elevation']['value']+p['sill']['value']
                reference_geometry={'kind':'host_axis_projection_m','start':[x,y,z],
                    'end':[x+dx*p['width']['value']/length,y+dy*p['width']['value']/length,z],
                    'height_m':p['height']['value'],'warning':'Host-axis reference, not verified wall face or full opening solid.'}
    return {"element":copy.deepcopy(selected), "derived_dimensions":dimensions, "reference_geometry":reference_geometry, "related_elements":related,
            "nodes":[copy.deepcopy(n) for n in model["nodes"] if n["id"] in node_ids],
            "constraints":[copy.deepcopy(c) for c in model.get("constraints",[]) if element_id in {c.get("a"),c.get("b")}],
            "issues":[i for i in geometry_issues(model) if element_id in i["id"]]}


def list_elements(model: dict) -> list[dict]:
    """List identities and actual relations to support evidence-bound object selection."""
    validate_room(model)
    result=[]
    for e in model['elements']:
        detail=inspect_element(model,e['id'])
        result.append({'id':e['id'], 'name':e.get('name'), 'ifc_type':e['ifc_type'],
                       'storey':e['storey'], 'classification_status':e['classification']['status'],
                       'dimensions':detail['derived_dimensions'],
                       'parameters_m':{k:v['value'] for k,v in e.get('parameters',{}).items()},
                       'related_elements':detail['related_elements']})
    return result


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


def wall_intersection_warnings(model: dict) -> list[dict]:
    """Find unlinked wall-axis intersections; this is not a full 3-D clash test."""
    from shapely.geometry import LineString
    validate_room(model)
    nodes={n['id']:n for n in model['nodes']};walls=[e for e in model['elements'] if e['ifc_type']=='IfcWall']
    warnings=[]
    for i,a in enumerate(walls):
        for b in walls[i+1:]:
            if {a['start'],a['end']} & {b['start'],b['end']}:
                continue  # Explicit shared topology is not an unlinked intersection.
            points=[nodes[a['start']],nodes[a['end']],nodes[b['start']],nodes[b['end']]]
            if any(p.get(k) is None for p in points for k in ('x','y')):continue
            ah=a['parameters']['height']['value'];bh=b['parameters']['height']['value']
            az=a['parameters']['base_elevation']['value'];bz=b['parameters']['base_elevation']['value']
            if None in (ah,bh,az,bz):continue
            if min(az+ah,bz+bh)<=max(az,bz):continue
            first=LineString([(p['x'],p['y']) for p in points[:2]])
            second=LineString([(p['x'],p['y']) for p in points[2:]])
            if first.intersects(second):
                warnings.append({'elements':sorted((a['id'],b['id'])),
                                 'code':'UNLINKED_WALL_AXIS_INTERSECTION_REQUIRES_REVIEW'})
    return warnings


def validate_geometry(model: dict) -> dict:
    """Report explicit geometric conflicts, not engineering certification."""
    issues=geometry_issues(model)
    return {"status":"CONFLICT" if issues else "UNVERIFIED_DRAFT","issues":issues,
            "wall_axis_warnings":wall_intersection_warnings(model),
            "warning":"Axis intersections are a limited diagnostic, not a full solid clash test or scene verification."}


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
