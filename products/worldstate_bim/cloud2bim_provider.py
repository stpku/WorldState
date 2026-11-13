"""Conservative adapter from Cloud2BIM IFC candidates to room IR 0.3.

The source is an unverified provider result, not evidence that its geometry,
material or classifications are observed. Unsupported or conflicting objects
are explicitly quarantined and never silently repaired or exported.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .parametric_ir import digest
from .room_ir import SCHEMA, geometry_issues, quantity, validate_room


def _fingerprint(kind: str, values: Any) -> str:
    data = json.dumps([kind, values], separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()[:16]


def import_cloud2bim(source: Path, *, project_id: str, registry: dict | None = None,
                     point_cloud_evidence: dict | None = None) -> tuple[dict, dict, dict]:
    """Import supported source objects and report every omission and assumption."""
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    import ifcopenshell.util.unit
    import ifcopenshell.validate
    from shapely.geometry import Polygon

    f = ifcopenshell.open(str(source))
    if f.schema != "IFC4":
        raise ValueError("Cloud2BIM IFC4 source required")
    if ifcopenshell.util.unit.calculate_unit_scale(f) != 1.0:
        raise ValueError("provider currently requires IFC length units in metres")
    mapping = json.loads(json.dumps(registry or {"schema": "cloud2bim-identities/0.1", "external": {}, "fingerprint": {}}))
    if mapping.get("schema") != "cloud2bim-identities/0.1":
        raise ValueError("unsupported identity registry")
    external, fingerprints = mapping["external"], mapping["fingerprint"]
    source_sha = digest(source)
    known_cloud = {"id": "craslab-source-1", "kind": "metric_point_cloud", "unit": "m",
        "source": "https://doi.org/10.5281/zenodo.7948116", "license": "CC-BY-4.0",
        "sha256": "5ce630c757205f68e33cd6ee52727275f21a44b11ca225b7dee20045997e5576",
        "archive_sha256": "933732e81910116cec5e74c9205074b82d1f571f3d9816386b68a0a909112671",
        "coordinate_frame": "CRASLAB source scan"}
    if point_cloud_evidence is None:
        point_cloud_evidence = mapping.get("point_cloud_evidence")
    if point_cloud_evidence is None and source_sha == "7e1ba673649b7bdabd8995705c5104b48ce3b00a4412560e7ea16d7fe74a2942":
        point_cloud_evidence = known_cloud
    if not isinstance(point_cloud_evidence,dict):
        raise ValueError("unrecognized provider IFC requires an explicit point-cloud evidence manifest")
    point_cloud_evidence=json.loads(json.dumps(point_cloud_evidence))
    if (point_cloud_evidence.get("kind") != "metric_point_cloud" or point_cloud_evidence.get("unit") != "m" or
            not isinstance(point_cloud_evidence.get("id"),str) or not point_cloud_evidence["id"] or
            point_cloud_evidence["id"] == "cloud2bim-ifc-1" or not point_cloud_evidence.get("source") or
            not point_cloud_evidence.get("license") or not point_cloud_evidence.get("coordinate_frame") or
            not isinstance(point_cloud_evidence.get("sha256"),str) or
            len(point_cloud_evidence["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in point_cloud_evidence["sha256"])):
        raise ValueError("point-cloud evidence requires ID, metre unit, source, license, coordinate frame and SHA-256")
    mapping["point_cloud_evidence"]=point_cloud_evidence
    used: set[str] = set()
    def identity(kind: str, guid: str, geometry: Any) -> str:
        fp = kind + ":" + _fingerprint(kind, geometry)
        key = kind + ":" + guid
        ident = external.get(key) or fingerprints.get(fp) or (kind.lower() + "-" + fp.split(":")[1])
        if ident in used:
            raise ValueError(f"ambiguous source identity for {key}; provide a distinct registry mapping")
        used.add(ident)
        external[key], fingerprints[fp] = ident, ident
        return ident
    refs = ["cloud2bim-ifc-1", point_cloud_evidence["id"]]
    prov = lambda status="inferred": {"status": status, "evidence_refs": refs.copy()}
    val = lambda x, status="inferred", note="Cloud2BIM candidate, not verified": quantity(float(x), status, refs.copy(), note)
    model: dict[str, Any] = {"schema": SCHEMA, "project_id": project_id, "mode": "automatic", "revision": 1,
        "coordinate_system": {"name": point_cloud_evidence["coordinate_frame"], "unit": "m", "georeferencing": "UNKNOWN"},
        "evidence": [{"id": "cloud2bim-ifc-1", "kind": "provider_result", "sha256": source_sha,
                      "provider": "Cloud2BIM", "status": "unverified_candidate"},
                     point_cloud_evidence],
        "nodes": [], "storeys": [], "elements": [], "constraints": [], "quarantined": [],
        "validation": {"status": "UNVERIFIED_DRAFT", "note": "source classifications and geometry require human and independent verification"}}
    node_index: dict[tuple[str,float,float], str] = {}
    def node(x: float, y: float, scope: str) -> str:
        # Merge exact endpoints only within the same source wall/storey plane.
        # Slab boundaries get their own scope until a user confirms dependency.
        key = (scope,round(float(x),6),round(float(y),6))
        if key not in node_index:
            ident = "node-" + _fingerprint("node", key)
            node_index[key] = ident
            model["nodes"].append({"id": ident, "x": key[1], "y": key[2], **prov()})
        return node_index[key]
    def quarantine(source_entity, reason: str) -> None:
        model["quarantined"].append({"source_guid": source_entity.GlobalId, "ifc_type": source_entity.is_a(),
                                      "reason": reason, "status": "conflict", "evidence_refs": refs.copy()})
    storey_map = {}
    for s in f.by_type("IfcBuildingStorey"):
        elevation = float(s.Elevation or 0.)
        ident = identity("storey", s.GlobalId, round(elevation,6))
        storey_map[s.GlobalId] = ident
        model["storeys"].append({"id":ident, "source_guid":s.GlobalId,
            "elevation":val(elevation, "inferred", "provider storey elevation; not independent measurement")})
    if not storey_map:
        raise ValueError("source has no building storey")
    def storey(e):
        container=ifcopenshell.util.element.get_container(e)
        if not container or container.GlobalId not in storey_map:
            raise ValueError("source element lacks a supported storey")
        return storey_map[container.GlobalId]
    def extrusion(e):
        found=[i for r in e.Representation.Representations for i in r.Items if i.is_a("IfcExtrudedAreaSolid")]
        if len(found)!=1:
            raise ValueError("requires one directly extruded solid")
        return found[0]
    source_walls={}
    for w in f.by_type("IfcWall"):
        try:
            axis=next(r for r in w.Representation.Representations if r.RepresentationType=="Curve2D")
            line=axis.Items[0]
            if not line.is_a("IfcPolyline") or len(line.Points)!=2:
                raise ValueError("wall axis is not a two-point polyline")
            matrix=ifcopenshell.util.placement.get_local_placement(w.ObjectPlacement)
            pts=[matrix @ np.array([*p.Coordinates[:2],0.,1.]) for p in line.Points]
            p1,p2=pts[0][:2],pts[1][:2]
            ex=extrusion(w)
            if not ex.SweptArea.is_a("IfcRectangleProfileDef"):
                raise ValueError("wall profile is not rectangular")
            thick,height=float(ex.SweptArea.YDim),float(ex.Depth)
            length=float(np.linalg.norm(p2-p1))
            if thick < .05:
                raise ValueError("provider thickness below the 0.05 m review threshold; requires confirmation")
            if length<=0 or height<=0:
                raise ValueError("invalid wall dimensions")
            # Geometry fingerprint is fallback for provider reruns that generate new GUIDs;
            # supplied registry preserves IDs if the same external object later changes.
            normalized=sorted([[round(float(x),5) for x in p] for p in (p1,p2)])
            ident=identity("wall",w.GlobalId,[normalized,round(float(matrix[2,3]),5)])
            storey_id=storey(w)
            scope=f"walls:{storey_id}:{float(matrix[2,3]):.6f}"
            item={"id":ident,"ifc_type":"IfcWall","source_guid":w.GlobalId,"storey":storey_id,
                  "start":node(*p1,scope),"end":node(*p2,scope),"axis_reference":"centerline","classification":prov(),
                  "parameters":{"height":val(height),"thickness":val(thick,"assumed","provider-inferred thickness, not independently measured"),
                                "base_elevation":val(matrix[2,3])},
                  "unknown":["actual wall class", "actual thickness and extent", "unobserved openings", "material"]}
            model["elements"].append(item)
            source_walls[w.GlobalId]=(item,p1,p2,float(matrix[2,3]))
        except (ValueError,StopIteration,TypeError,AttributeError) as exc:
            quarantine(w,str(exc))
    if not source_walls:
        raise ValueError("no valid wall candidates imported")
    for s in f.by_type("IfcSlab"):
        try:
            ex=extrusion(s)
            curve=ex.SweptArea.OuterCurve
            if not curve.is_a("IfcPolyline"):
                raise ValueError("unsupported slab outline")
            matrix=ifcopenshell.util.placement.get_local_placement(s.ObjectPlacement)
            if ex.Position:
                matrix=matrix @ ifcopenshell.util.placement.get_axis2placement(ex.Position)
            coordinates=[]
            for p in curve.Points:
                raw=list(p.Coordinates)
                vertex=matrix @ np.array([raw[0],raw[1],raw[2] if len(raw)>2 else 0.,1.])
                coordinates.append((float(vertex[0]),float(vertex[1])))
            if coordinates[0]==coordinates[-1]:coordinates.pop()
            polygon=Polygon(coordinates)
            if not polygon.is_valid or polygon.area<=1e-8:
                raise ValueError("provider slab boundary self-intersects or is degenerate")
            ident=identity("slab",s.GlobalId,[[(round(x,5),round(y,5)) for x,y in coordinates],round(float(matrix[2,3]),5)])
            model["elements"].append({"id":ident,"ifc_type":"IfcSlab","source_guid":s.GlobalId,"storey":storey(s),
                "classification":prov(),"outline":[node(x,y,f"slab:{ident}") for x,y in coordinates],"outline_status":prov(),
                "parameters":{"thickness":val(ex.Depth,"assumed","provider slab thickness not measured"),
                              "elevation":val(matrix[2,3])},"unknown":["actual slab thickness", "material", "room membership"]})
        except (ValueError,StopIteration,TypeError,AttributeError) as exc:
            quarantine(s,str(exc))
    settings=ifcopenshell.geom.settings();settings.set("use-world-coords",True)
    for o in f.by_type("IfcOpeningElement"):
        try:
            if len(o.VoidsElements)!=1 or len(o.HasFillings)!=1:
                raise ValueError("opening must have one wall host and one filling")
            wall=o.VoidsElements[0].RelatingBuildingElement
            if wall.GlobalId not in source_walls:
                raise ValueError("host wall quarantined or missing")
            host,p1,p2,base=source_walls[wall.GlobalId]
            shape=ifcopenshell.geom.create_shape(settings,o)
            verts=np.asarray(shape.geometry.verts).reshape(-1,3)
            direction=(p2-p1)/np.linalg.norm(p2-p1)
            along=(verts[:,:2]-p1) @ direction
            offset,width=float(along.min()),float(along.max()-along.min())
            sill,height=float(verts[:,2].min()-base),float(np.ptp(verts[:,2]))
            wall_length=float(np.linalg.norm(p2-p1))
            if offset < -1e-6 or sill < -1e-6 or offset+width>wall_length+1e-6 or sill+height>host["parameters"]["height"]["value"]+1e-6:
                raise ValueError("source opening extends outside host wall")
            # Values extremely close to zero are numerical noise, not fabricated geometry.
            offset=max(offset,0.);sill=max(sill,0.)
            fill=o.HasFillings[0].RelatedBuildingElement
            if fill.is_a() not in {"IfcDoor","IfcWindow"}:
                raise ValueError("unsupported opening filling")
            ident=identity("opening",o.GlobalId,[host["id"],round(offset,5),round(width,5),round(sill,5),round(height,5)])
            fill_id=identity(fill.is_a(),fill.GlobalId,[ident,fill.is_a()])
            op={"id":ident,"ifc_type":"IfcOpeningElement","source_guid":o.GlobalId,"host":host["id"],"fill":fill_id,
                "storey":host["storey"],"classification":prov(),"parameters":{
                "offset":val(offset),"width":val(width),"height":val(height),"sill":val(sill)},
                "unknown":["opening physical extent", "occluded surfaces"]}
            panel={"id":fill_id,"ifc_type":fill.is_a(),"source_guid":fill.GlobalId,"opening":ident,
                   "storey":host["storey"],"classification":prov(),
                   "parameters":{"panel_thickness":val(.04,"assumed","placeholder panel thickness; source does not establish actual thickness")},
                   "unknown":["true filling type", "material", "panel thickness"]}
            model["elements"].extend([op,panel])
            if geometry_issues(model):
                model["elements"][-2:]=[]
                raise ValueError("opening conflicts with another accepted opening")
        except (ValueError,StopIteration,TypeError,AttributeError,RuntimeError) as exc:
            quarantine(o,str(exc))
            for relationship in o.HasFillings:
                fill = relationship.RelatedBuildingElement
                if fill:
                    quarantine(fill, "filling omitted because its source opening was quarantined")
    validate_room(model)
    issues=geometry_issues(model)
    if issues:
        raise ValueError(f"provider adapter produced invalid candidate: {issues}")
    from collections import Counter
    counts=dict(Counter(e["ifc_type"] for e in model["elements"]))
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(f,logger)
    schema_issues={}
    for issue in logger.statements:
        key=str(issue.get("attribute",issue.get("message","unknown")))
        schema_issues[key]=schema_issues.get(key,0)+1
    report={"source_sha256":source_sha,"source_ifc_schema":f.schema,
        "source_counts":{x:len(f.by_type(x)) for x in ("IfcWall","IfcSlab","IfcOpeningElement","IfcDoor","IfcWindow","IfcSpace")},
        "imported_counts":counts,"quarantined":model["quarantined"],
        "source_schema_errors":schema_issues,
        "type_definitions":"unsupported source type definitions are not imported",
        "geographic_location":"UNKNOWN: source geographic location is not imported",
        "material":"UNKNOWN: discarded source material assignments",
        "warning":"candidate geometry and semantic classes are inferred, not independently verified"}
    return model,mapping,report
