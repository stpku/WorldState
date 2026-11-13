"""Room constraints and revision tests use explicit synthetic evidence."""
import copy
import math
import pytest
from products.worldstate_bim.room_ir import SCHEMA, geometry_issues, quantity, revise_element, validate_room


def fixture():
    refs=["manual-1"]
    q=lambda x: quantity(x,"human_confirmed",refs,"synthetic fixture")
    status={"status":"human_confirmed","evidence_refs":refs}
    nodes=[{"id":n,"x":x,"y":y,**status} for n,x,y in [("n1",0,0),("n2",4,0),("n3",4,3),("n4",0,3)]]
    walls=[{"id":f"wall-{i}","ifc_type":"IfcWall","start":a,"end":b,"storey":"storey-1",
            "classification":status,"parameters":{"height":q(2.8),"thickness":q(.12),"base_elevation":q(0)}}
           for i,(a,b) in enumerate([("n1","n2"),("n2","n3"),("n3","n4"),("n4","n1")],1)]
    opening={"id":"opening-1","ifc_type":"IfcOpeningElement","host":"wall-1","fill":"door-1",
             "storey":"storey-1","classification":status,
             "parameters":{"offset":q(1),"width":q(.9),"sill":q(0),"height":q(2.1)}}
    door={"id":"door-1","ifc_type":"IfcDoor","opening":"opening-1","storey":"storey-1",
          "classification":status,"parameters":{"panel_thickness":q(.04)}}
    slab={"id":"slab-1","ifc_type":"IfcSlab","storey":"storey-1","classification":status,
          "outline":["n1","n2","n3","n4"],"outline_status":status,"parameters":{"elevation":q(-.15),"thickness":q(.15)}}
    space={"id":"room-1","ifc_type":"IfcSpace","storey":"storey-1","classification":status,
           "boundary_walls":["wall-1","wall-2","wall-3","wall-4"],"boundary_status":"closed_confirmed","parameters":{}}
    constraints=[{"id":f"perp-{i}","kind":"perpendicular","a":a,"b":b,**status} for i,(a,b) in enumerate(
        [("wall-1","wall-2"),("wall-2","wall-3"),("wall-3","wall-4"),("wall-4","wall-1")])]
    return {"schema":SCHEMA,"project_id":"fixture-room","mode":"assisted","revision":1,
            "coordinate_system":{"name":"local","unit":"m"},
            "evidence":[{"id":"manual-1","kind":"synthetic_fixture"}],"nodes":nodes,
            "storeys":[{"id":"storey-1","elevation":q(0)}],"elements":walls+[opening,door,slab,space],"constraints":constraints}


def test_resize_wall_propagates_corner_constraints_and_dependencies():
    model=fixture()
    assert geometry_issues(model)==[]
    updated,diff=revise_element(model,"wall-1","length",5.,reason="synthetic change",operator="user")
    assert model["nodes"][1]["x"]==4
    assert updated["nodes"][1]["x"]==pytest.approx(5.)
    assert updated["nodes"][2]["x"]==pytest.approx(5.,abs=1e-5)
    assert {"wall-1","wall-2","wall-3","opening-1","door-1","slab-1","room-1"} <= set(diff["affected_elements"])
    assert geometry_issues(updated)==[]
    assert updated["history"][-1]["reason_ref"]=="revision-2"


def test_invalid_opening_is_rejected_without_mutating_previous_version():
    model=fixture()
    original=copy.deepcopy(model)
    with pytest.raises(ValueError,match="OPENING_OUTSIDE_WALL"):
        revise_element(model,"opening-1","offset",3.5,reason="out of bounds",operator="user")
    assert model==original


def test_open_room_and_unknown_dimensions_remain_explicit():
    model=fixture()
    room=next(e for e in model["elements"] if e["id"]=="room-1")
    room["boundary_status"]="open"
    wall=next(e for e in model["elements"] if e["id"]=="wall-1")
    wall["parameters"]["thickness"]=quantity(None,"unknown",["manual-1"],"unseen")
    validate_room(model)
    assert room["boundary_status"]=="open" and wall["parameters"]["thickness"]["value"] is None


def test_multiwall_ifc_opening_relationships_and_stable_guids(tmp_path):
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate
    from products.worldstate_bim.room_ifc import export_room
    model=fixture()
    path=export_room(model,tmp_path/"original.ifc")
    f=ifcopenshell.open(str(path))
    assert f.schema=="IFC4" and len(f.by_type("IfcWall"))==4
    assert len(f.by_type("IfcSlab"))==len(f.by_type("IfcDoor"))==1
    assert len(f.by_type("IfcOpeningElement"))==len(f.by_type("IfcRelVoidsElement"))==len(f.by_type("IfcRelFillsElement"))==1
    assert len(f.by_type("IfcRelSpaceBoundary"))==4
    for wall in f.by_type("IfcWall"):
        shape=ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),wall)
        assert len(shape.geometry.verts)>0
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(f,logger)
    assert logger.statements==[]
    updated,_=revise_element(model,"wall-1","length",5,reason="edit",operator="user")
    revised=ifcopenshell.open(str(export_room(updated,tmp_path/"revised.ifc")))
    assert {w.Name:w.GlobalId for w in f.by_type("IfcWall")}=={w.Name:w.GlobalId for w in revised.by_type("IfcWall")}


def test_wall_height_and_opening_position_detect_conflicts():
    model=fixture()
    result,diff=revise_element(model,"wall-2","height",3.1,reason="height correction",operator="user")
    assert next(e for e in result["elements"] if e["id"]=="wall-2")["parameters"]["height"]["value"]==3.1
    result,diff=revise_element(result,"opening-1","offset",1.4,reason="move opening",operator="user")
    assert next(e for e in result["elements"] if e["id"]=="opening-1")["parameters"]["offset"]["value"]==1.4
    with pytest.raises(ValueError,match="OPENING_ABOVE_WALL"):
        revise_element(model,"wall-1","height",1.5,reason="too short",operator="user")


def test_unknown_geometry_never_exports_or_becomes_known(tmp_path):
    from products.worldstate_bim.room_ifc import export_room
    model=fixture()
    node=model["nodes"][0]
    node.update(x=None,y=None,status="unknown")
    assert any(i["code"]=="UNKNOWN_WALL_COORDINATE" for i in geometry_issues(model))
    with pytest.raises(ValueError,match="conflicting geometry"):
        export_room(model,tmp_path/"invalid.ifc")
