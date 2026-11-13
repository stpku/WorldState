"""Compile room IR 0.3 to IFC4 using bounded native semantic entities."""
from __future__ import annotations

import json
import math
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .room_ir import geometry_issues, validate_room
from .ifc_export import _add_editable_wall_axis


def stable_guid(project_id: str, kind: str, element_id: str) -> str:
    """Derive a GUID from semantic identity, never from mutable geometry."""
    import ifcopenshell.guid
    return ifcopenshell.guid.compress(uuid5(NAMESPACE_URL, f"worldstate-bim-room:{project_id}:{kind}:{element_id}").hex)


def export_room(model: dict, destination: Path) -> Path:
    """Write an IFC4 model; reject conflicts or unknown solid dimensions."""
    validate_room(model)
    issues = geometry_issues(model)
    if issues:
        raise ValueError("cannot export conflicting geometry: " + ", ".join(f"{x['id']}:{x['code']}" for x in issues))
    if destination.exists():
        raise FileExistsError(destination)
    for e in model["elements"]:
        if e["classification"]["status"] in {"unknown", "conflict"}:
            raise ValueError(f"cannot export {e['id']} with unresolved classification")
        if e["ifc_type"] == "IfcSlab" and e["outline_status"]["status"] in {"unknown", "conflict"}:
            raise ValueError(f"cannot export {e['id']} with unresolved outline")
        for name, p in e.get("parameters", {}).items():
            if p.get("status") in {"unknown", "conflict"}:
                raise ValueError(f"cannot export {e['id']} with unresolved {name}")
    for s in model["storeys"]:
        if s["elevation"]["value"] is None:
            raise ValueError("cannot export an unknown storey elevation")
    import numpy as np
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.feature
    import ifcopenshell.api.geometry
    import ifcopenshell.api.project
    import ifcopenshell.api.pset
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.unit
    import ifcopenshell.util.placement

    f = ifcopenshell.api.project.create_file(version="IFC4")
    guid = lambda kind, ident: stable_guid(model["project_id"], kind, ident)
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=model["project_id"])
    project.GlobalId = guid("project", "project")
    units = [ifcopenshell.api.unit.add_si_unit(f, unit_type=u) for u in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT")]
    ifcopenshell.api.unit.assign_unit(f, units=units)
    root_context = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=root_context)
    plan = ifcopenshell.api.context.add_context(f, context_type="Plan")
    axis = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis", target_view="GRAPH_VIEW", parent=plan)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site (location unspecified)")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building (unverified)")
    site.GlobalId, building.GlobalId = guid("site", "site"), guid("building", "building")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    storeys = {}
    for s in model["storeys"]:
        obj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=s["id"])
        obj.GlobalId = guid("storey", s["id"])
        obj.Elevation = s["elevation"]["value"]
        ifcopenshell.api.aggregate.assign_object(f, products=[obj], relating_object=building)
        storeys[s["id"]] = obj
    nodes = {n["id"]: n for n in model["nodes"]}
    items = {e["id"]: e for e in model["elements"]}
    entities = {}

    def evidence(obj, item):
        pset = ifcopenshell.api.pset.add_pset(f, product=obj, name="Pset_WorldStateEvidence")
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "IRSchema": model["schema"], "Revision": model["revision"],
            "EvidenceJSON": json.dumps({"classification": item["classification"],
                "parameters": item.get("parameters", {}), "unknown": item.get("unknown", []),
                "source_guid": item.get("source_guid")}, ensure_ascii=True, separators=(",", ":")),
            "ReconstructionStatus": "UNVERIFIED_DRAFT"})

    for e in model["elements"]:
        kind = e["ifc_type"]
        if kind not in {"IfcWall", "IfcSlab", "IfcSpace"}:
            continue
        obj = ifcopenshell.api.root.create_entity(f, ifc_class=kind, name=e["id"])
        obj.GlobalId = guid(kind, e["id"])
        entities[e["id"]] = obj
        p = e.get("parameters", {})
        if kind == "IfcWall":
            a, b = nodes[e["start"]], nodes[e["end"]]
            z = p["base_elevation"]["value"]
            dx, dy = b["x"]-a["x"], b["y"]-a["y"]
            length = math.hypot(dx, dy)
            if e.get("axis_reference", "face") == "centerline":
                representation = ifcopenshell.api.geometry.add_wall_representation(f, context=body,
                    length=length, height=p["height"]["value"], thickness=p["thickness"]["value"],
                    offset=-p["thickness"]["value"]/2)
                transform = np.eye(4)
                transform[:3, :3] = [[dx/length, -dy/length, 0.], [dy/length, dx/length, 0.], [0., 0., 1.]]
                transform[:3, 3] = (a["x"], a["y"], z)
                ifcopenshell.api.geometry.edit_object_placement(f, product=obj, matrix=transform)
            else:
                representation = ifcopenshell.api.geometry.create_2pt_wall(f, element=obj, context=body,
                    p1=(a["x"],a["y"]), p2=(b["x"],b["y"]), elevation=z,
                    height=p["height"]["value"], thickness=p["thickness"]["value"], is_si=True)
            ifcopenshell.api.geometry.assign_representation(f, product=obj, representation=representation)
            _add_editable_wall_axis(f, obj, axis, length, p["thickness"]["value"])
            if e.get("axis_reference", "face") == "centerline":
                import ifcopenshell.util.element
                usage = ifcopenshell.util.element.get_material(obj)
                usage.OffsetFromReferenceLine = -p["thickness"]["value"]/2
            ifcopenshell.api.spatial.assign_container(f, products=[obj], relating_structure=storeys[e["storey"]])
        elif kind == "IfcSlab":
            polygon = [(nodes[n]["x"], nodes[n]["y"]) for n in e["outline"]]
            representation = ifcopenshell.api.geometry.add_slab_representation(f, context=body,
                depth=p["thickness"]["value"], polyline=polygon + [polygon[0]])
            ifcopenshell.api.geometry.assign_representation(f, product=obj, representation=representation)
            matrix = np.eye(4); matrix[2, 3] = p["elevation"]["value"]
            ifcopenshell.api.geometry.edit_object_placement(f, product=obj, matrix=matrix)
            ifcopenshell.api.spatial.assign_container(f, products=[obj], relating_structure=storeys[e["storey"]])
        else:
            ifcopenshell.api.aggregate.assign_object(f, products=[obj], relating_object=storeys[e["storey"]])
        evidence(obj, e)
    for e in model["elements"]:
        if e["ifc_type"] != "IfcOpeningElement":
            continue
        wall = entities[e["host"]]
        host = items[e["host"]]
        p = e["parameters"]
        opening = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement", name=e["id"])
        opening.GlobalId = guid("IfcOpeningElement", e["id"])
        entities[e["id"]] = opening
        # Overcut by 1 cm on each side so the boolean opening crosses the wall.
        thickness = host["parameters"]["thickness"]["value"]
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=p["width"]["value"],
             height=p["height"]["value"], thickness=thickness+0.02)
        ifcopenshell.api.geometry.assign_representation(f, product=opening, representation=rep)
        transform = np.eye(4)
        wall_y = -thickness/2 if host.get("axis_reference", "face") == "centerline" else 0.
        transform[:3, 3] = (p["offset"]["value"], wall_y-0.01, p["sill"]["value"])
        matrix = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement) @ transform
        ifcopenshell.api.geometry.edit_object_placement(f, product=opening, matrix=matrix)
        ifcopenshell.api.feature.add_feature(f, feature=opening, element=wall)
        evidence(opening, e)
        if e.get("fill"):
            fill = items[e["fill"]]
            panel = ifcopenshell.api.root.create_entity(f, ifc_class=fill["ifc_type"], name=fill["id"])
            panel.GlobalId = guid(fill["ifc_type"], fill["id"])
            panel.OverallWidth, panel.OverallHeight = p["width"]["value"], p["height"]["value"]
            entities[fill["id"]] = panel
            rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=p["width"]["value"],
                 height=p["height"]["value"], thickness=fill["parameters"]["panel_thickness"]["value"])
            ifcopenshell.api.geometry.assign_representation(f, product=panel, representation=rep)
            panel_transform = np.eye(4)
            panel_transform[:3, 3] = (p["offset"]["value"],
                (-fill["parameters"]["panel_thickness"]["value"]/2 if host.get("axis_reference", "face") == "centerline" else 0.),
                p["sill"]["value"])
            panel_matrix = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement) @ panel_transform
            ifcopenshell.api.geometry.edit_object_placement(f, product=panel, matrix=panel_matrix)
            ifcopenshell.api.spatial.assign_container(f, products=[panel], relating_structure=storeys[e["storey"]])
            ifcopenshell.api.feature.add_filling(f, opening=opening, element=panel)
            evidence(panel, fill)
    for e in model["elements"]:
        if e["ifc_type"] == "IfcSpace":
            for wall_id in e["boundary_walls"]:
                f.create_entity("IfcRelSpaceBoundary", GlobalId=guid("boundary", e["id"]+":"+wall_id),
                    RelatingSpace=entities[e["id"]], RelatedBuildingElement=entities[wall_id],
                    PhysicalOrVirtualBoundary="PHYSICAL", InternalOrExternalBoundary="NOTDEFINED")
    destination.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(destination))
    return destination
