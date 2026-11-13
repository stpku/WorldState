"""Fail-closed import of a bounded external IFC edit into multi-object room IR."""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from .parametric_ir import digest
from .room_ifc import export_room, stable_guid
from .room_ir import revise_element, validate_room


def _products(f) -> dict[str, Any]:
    return {e.GlobalId: e for e in f.by_type("IfcProduct") if e.GlobalId}


def _links(f) -> dict[str, list[tuple[str,str]]]:
    return {
        "voids": sorted((r.RelatingBuildingElement.GlobalId,r.RelatedOpeningElement.GlobalId) for r in f.by_type("IfcRelVoidsElement")),
        "fills": sorted((r.RelatingOpeningElement.GlobalId,r.RelatedBuildingElement.GlobalId) for r in f.by_type("IfcRelFillsElement")),
        "space": sorted((r.RelatingSpace.GlobalId,r.RelatedBuildingElement.GlobalId) for r in f.by_type("IfcRelSpaceBoundary") if r.RelatedBuildingElement),
        "contained": sorted((r.RelatingStructure.GlobalId,e.GlobalId) for r in f.by_type("IfcRelContainedInSpatialStructure") for e in r.RelatedElements),
    }


def _mesh(entity, settings) -> tuple:
    import ifcopenshell.geom
    if not getattr(entity, "Representation", None):
        return ()
    shape = ifcopenshell.geom.create_shape(settings, entity)
    vertices = np.asarray(shape.geometry.verts).reshape(-1,3)
    faces = np.asarray(shape.geometry.faces).reshape(-1,3)
    coords = [tuple(round(float(v),4) for v in p) for p in vertices]
    return tuple(sorted(tuple(sorted(coords[int(i)] for i in face)) for face in faces))


def _same_retriangulated_surface(a: np.ndarray, af: np.ndarray, b: np.ndarray, bf: np.ndarray,
                                 *, tolerance: float = 1e-5) -> bool:
    """Compare unchanged planar surfaces despite different triangle diagonals.

    Require a one-to-one vertex match within 0.01 mm, matching planes, and
    equal projected polygon topology and boundaries. This deliberately rejects
    arbitrary remeshing or very large meshes instead of guessing equivalence.
    """
    from scipy.spatial import cKDTree
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    if len(a)!=len(b) or len(af)!=len(bf) or not len(a) or len(af)>20000 or len(bf)>20000:
        return False
    distance,index=cKDTree(a).query(b)
    if np.max(distance)>tolerance or len(set(map(int,index)))!=len(a):
        return False
    groups=[]
    def plane(tri):
        n=np.cross(tri[1]-tri[0],tri[2]-tri[0]);length=float(np.linalg.norm(n))
        if length<1e-12:return None
        n=n/length
        if n[int(np.argmax(np.abs(n)))]<0:n=-n
        return n,float(np.dot(n,tri[0]))
    def locate(normal,offset):
        return next((group for group in groups if np.linalg.norm(group["normal"]-normal)<1e-6 and
                     abs(group["offset"]-offset)<tolerance),None)
    for face in af:
        triangle=a[face];p=plane(triangle)
        if p is None:return False
        group=locate(*p)
        if group is None:
            group={"normal":p[0],"offset":p[1],"left":[],"right":[]};groups.append(group)
        group["left"].append(triangle)
    for face in bf:
        triangle=b[face];p=plane(triangle)
        if p is None:return False
        group=locate(*p)
        if group is None:return False
        group["right"].append(triangle)
    def signature(polygon):
        if polygon.geom_type=="Polygon":return (1,(len(polygon.interiors),))
        if polygon.geom_type=="MultiPolygon":return (len(polygon.geoms),tuple(sorted(len(p.interiors) for p in polygon.geoms)))
        return None
    for group in groups:
        if not group["right"]:return False
        drop=int(np.argmax(np.abs(group["normal"])));axes=[i for i in range(3) if i!=drop]
        left=unary_union([Polygon(tri[:,axes]) for tri in group["left"]])
        right=unary_union([Polygon(tri[:,axes]) for tri in group["right"]])
        topology=signature(left)
        if not left.is_valid or not right.is_valid or topology is None or topology!=signature(right):return False
        if left.boundary.hausdorff_distance(right.boundary)>tolerance:return False
        if left.symmetric_difference(right).area>tolerance*(left.length+right.length)+tolerance*tolerance:return False
    return True


def _equivalent_retriangulation(left, right, settings) -> bool:
    import ifcopenshell.geom
    from shapely.errors import GEOSException
    if not getattr(left,"Representation",None) or not getattr(right,"Representation",None):return False
    arrays=[]
    for entity in (left,right):
        shape=ifcopenshell.geom.create_shape(settings,entity)
        arrays.append((np.asarray(shape.geometry.verts).reshape(-1,3),np.asarray(shape.geometry.faces,dtype=int).reshape(-1,3)))
    try:
        return _same_retriangulated_surface(arrays[0][0],arrays[0][1],arrays[1][0],arrays[1][1])
    except GEOSException:
        return False


def _verify_geometry(reference, candidate) -> None:
    import ifcopenshell.geom
    a, b = _products(reference), _products(candidate)
    if set(a) != set(b):
        raise ValueError("external IFC added, removed, or changed an object identity")
    if _links(reference) != _links(candidate):
        raise ValueError("external IFC changed unsupported topology")
    settings = ifcopenshell.geom.settings();settings.set("use-world-coords",True)
    for guid, left in a.items():
        right = b[guid]
        if left.is_a() != right.is_a() or left.Name != right.Name:
            raise ValueError("external IFC changed unsupported object class or name")
        for attr in ("Description", "ObjectType", "Tag", "PredefinedType", "OverallWidth", "OverallHeight"):
            if getattr(left,attr,None) != getattr(right,attr,None):
                raise ValueError(f"external IFC changed unsupported attribute: {left.Name}.{attr}")
        try:
            if _mesh(left, settings) != _mesh(right, settings) and not _equivalent_retriangulation(left,right,settings):
                raise ValueError(f"external IFC geometry differs outside supported edit: {left.Name}")
        except RuntimeError as exc:
            raise ValueError(f"external IFC geometry cannot be read: {left.Name}") from exc


def _verify_unmodified_metadata(before, after) -> None:
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    import ifcopenshell.util.unit
    a,b=_products(before),_products(after)
    if set(a) != set(b) or _links(before) != _links(after):
        raise ValueError("external IFC changed object identities or topology")
    if ifcopenshell.util.unit.calculate_unit_scale(before) != ifcopenshell.util.unit.calculate_unit_scale(after):
        raise ValueError("external IFC changed project length units")
    for guid, left in a.items():
        right=b[guid]
        def psets(e):
            data=ifcopenshell.util.element.get_psets(e)
            for value in data.values():
                if isinstance(value,dict): value.pop("id",None)
            return data
        if psets(left)!=psets(right):
            raise ValueError(f"external IFC changed unsupported properties: {left.Name}")
        if left.is_a()!=right.is_a() or left.Name!=right.Name:
            raise ValueError("external IFC changed unsupported object class or name")
        for attr in ("Elevation", "RefLatitude", "RefLongitude", "RefElevation", "LongName", "CompositionType"):
            if getattr(left,attr,None) != getattr(right,attr,None):
                raise ValueError(f"external IFC changed unsupported spatial attribute: {left.Name}.{attr}")
        if not getattr(left,"Representation",None):
            def placement(e):
                return (ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
                        if getattr(e,"ObjectPlacement",None) else np.eye(4))
            if not np.allclose(placement(left),placement(right),atol=1e-7):
                raise ValueError(f"external IFC changed unsupported spatial placement: {left.Name}")
        def material(e):
            value=ifcopenshell.util.element.get_material(e)
            if value is None:return None
            if value.is_a("IfcMaterialLayerSetUsage"):
                return (value.is_a(),value.LayerSetDirection,value.DirectionSense,value.OffsetFromReferenceLine,
                        tuple((layer.Material.Name if layer.Material else None,layer.LayerThickness)
                              for layer in value.ForLayerSet.MaterialLayers))
            if value.is_a("IfcMaterial"):
                return (value.is_a(),value.Name)
            raise ValueError(f"unsupported material structure for {e.Name}")
        if material(left)!=material(right):
            raise ValueError(f"external IFC changed unsupported material: {left.Name}")


def _read_value(f, model: dict, element_id: str, attribute: str) -> float:
    import ifcopenshell.geom
    import ifcopenshell.util.placement
    import ifcopenshell.util.representation
    elements={e["id"]:e for e in model["elements"]}; item=elements.get(element_id)
    if item is None:
        raise ValueError("element not found")
    entity=f.by_guid(stable_guid(model["project_id"],item["ifc_type"],element_id))
    if entity is None:
        raise ValueError("external IFC is missing the chosen element")
    if item["ifc_type"]=="IfcWall" and attribute=="length":
        a,b=ifcopenshell.util.representation.get_reference_line(entity)
        return float(np.linalg.norm(np.asarray(b)-np.asarray(a)))
    if item["ifc_type"]=="IfcWall" and attribute=="height":
        solids=[i for rep in entity.Representation.Representations for i in rep.Items if i.is_a("IfcExtrudedAreaSolid")]
        if len(solids)!=1:
            raise ValueError("wall is not a supported single extrusion")
        return float(solids[0].Depth)
    if item["ifc_type"]=="IfcOpeningElement" and attribute in {"offset","width","height","sill"}:
        if not entity.Representation:
            raise ValueError("external IFC opening has no readable geometry; synchronization refused")
        host=elements[item["host"]]
        wall=f.by_guid(stable_guid(model["project_id"],"IfcWall",host["id"]))
        settings=ifcopenshell.geom.settings();settings.set("use-world-coords",True)
        shape=ifcopenshell.geom.create_shape(settings,entity)
        xyz=np.asarray(shape.geometry.verts).reshape(-1,3)
        matrix=np.linalg.inv(ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement))
        local=(matrix @ np.column_stack((xyz,np.ones(len(xyz)))).T).T[:,:3]
        return float({"offset":local[:,0].min(),"width":np.ptp(local[:,0]),
                      "sill":local[:,2].min(),"height":np.ptp(local[:,2])}[attribute])
    raise ValueError("external readback supports only wall length/height and opening dimensions")


def sync_external_ifc(model: dict, baseline_ifc: Path, edited_ifc: Path, *, element_id: str,
                      attribute: str, reason: str, operator: str) -> tuple[dict,dict]:
    """Synchronize one supported edit only after whole-model verification.

    Exact triangles use 0.1 mm rounded coordinates. Alternative triangulation
    must pass a stricter 0.01 mm vertex, plane, surface and topology check.
    Unsupported geometry, relationships and checked metadata are rejected.
    """
    import ifcopenshell
    validate_room(model)
    original_hash,edited_hash=digest(baseline_ifc),digest(edited_ifc)
    original,edited=ifcopenshell.open(str(baseline_ifc)),ifcopenshell.open(str(edited_ifc))
    if original.schema!="IFC4" or edited.schema!="IFC4":
        raise ValueError("IFC4 required")
    _verify_unmodified_metadata(original,edited)
    value=_read_value(edited,model,element_id,attribute)
    if not math.isfinite(value):
        raise ValueError("non-finite external dimension")
    revised,diff=revise_element(model,element_id,attribute,value,reason=reason,operator=operator)
    # Generate both expected versions and compare the entire product geometry
    # and the supported relationship graph before accepting a single edit.
    with tempfile.TemporaryDirectory(prefix="worldstate-room-sync-") as temp:
        first=Path(temp)/"before.ifc";second=Path(temp)/"after.ifc"
        export_room(model,first);export_room(revised,second)
        _verify_geometry(ifcopenshell.open(str(first)),original)
        _verify_geometry(ifcopenshell.open(str(second)),edited)
    if digest(baseline_ifc)!=original_hash or digest(edited_ifc)!=edited_hash:
        raise ValueError("external IFC changed during synchronization")
    ref=f"external-ifc-{revised['revision']}"
    revised["evidence"].append({"id":ref,"kind":"external_ifc_edit","sha256":edited_hash,
        "baseline_sha256":original_hash,"note":"only the explicitly verified attribute is imported"})
    item=next(e for e in revised["elements"] if e["id"]==element_id)
    if attribute=="length" and item["ifc_type"]=="IfcWall":
        for node in revised["nodes"]:
            if node["id"] in diff["changed_nodes"]:node["evidence_refs"].append(ref)
    else:
        item["parameters"][attribute]["evidence_refs"].append(ref)
    diff["external_ifc_sha256"]=edited_hash
    diff["warnings"] = ["Only the requested geometry attribute is synchronized; IFC metadata outside the checked fields is not imported. Review before using the regenerated IFC."]
    validate_room(revised)
    return revised,diff
