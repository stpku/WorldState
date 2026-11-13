"""Whole-model external edit readback, including failure on unrelated edits."""
import json
from pathlib import Path
import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np
import pytest

from products.worldstate_bim.room_ifc import stable_guid
from products.worldstate_bim.room_sync import sync_external_ifc, _same_retriangulated_surface

ROOT=Path(__file__).resolve().parents[3]/"examples/bim_real_scan_craslab/room_round3"
ROUND4=ROOT.parent/"room_round4"


def real_model():
    return json.loads((ROOT/"model.json").read_text())


def test_real_bonsai_multi_object_edit_roundtrip():
    model=real_model()
    updated,diff=sync_external_ifc(model,ROOT/"model.ifc",ROOT/"bonsai-edited.ifc",
        element_id="wall-cf1d15bbd93c2d52",attribute="length",reason="Bonsai edit",operator="analyst")
    assert diff["after"]==pytest.approx(5.3,abs=1e-5)
    assert diff["affected_elements"]==["wall-cf1d15bbd93c2d52"]
    assert updated["revision"]==2 and updated["evidence"][-1]["kind"]=="external_ifc_edit"


def test_reject_unrelated_external_geometry_or_material_change(tmp_path):
    model=real_model()
    f=ifcopenshell.open(str(ROOT/"bonsai-edited.ifc"))
    other=next(w for w in f.by_type("IfcWall") if w.Name!="wall-cf1d15bbd93c2d52")
    material=ifcopenshell.util.element.get_material(other)
    material.ForLayerSet.MaterialLayers[0].LayerThickness += .02
    path=tmp_path/"bad.ifc";f.write(str(path))
    with pytest.raises(ValueError,match="unsupported material"):
        sync_external_ifc(model,ROOT/"model.ifc",path,element_id="wall-cf1d15bbd93c2d52",
                          attribute="length",reason="edit",operator="analyst")


def test_wall_height_external_readback(tmp_path):
    model=real_model();f=ifcopenshell.open(str(ROOT/"model.ifc"))
    wall=next(w for w in f.by_type("IfcWall") if w.Name=="wall-cf1d15bbd93c2d52")
    solid=next(i for r in wall.Representation.Representations for i in r.Items if i.is_a("IfcExtrudedAreaSolid"))
    solid.Depth=3.6
    path=tmp_path/"height.ifc";f.write(str(path))
    updated,diff=sync_external_ifc(model,ROOT/"model.ifc",path,element_id=wall.Name,
                                    attribute="height",reason="height edit",operator="analyst")
    assert diff["after"]==pytest.approx(3.6)
    assert next(e for e in updated["elements"] if e["id"]==wall.Name)["parameters"]["height"]["value"]==pytest.approx(3.6)


def test_opening_offset_readback_updates_filling(tmp_path):
    model=real_model();f=ifcopenshell.open(str(ROOT/"model.ifc"))
    opening=next(e for e in model["elements"] if e["ifc_type"]=="IfcOpeningElement")
    wall=next(e for e in model["elements"] if e["id"]==opening["host"])
    wall_obj=f.by_guid(stable_guid(model["project_id"],"IfcWall",wall["id"]))
    direction=ifcopenshell.util.placement.get_local_placement(wall_obj.ObjectPlacement)[:3,0]
    for item_id,kind in ((opening["id"],"IfcOpeningElement"),(opening["fill"],"IfcWindow")):
        entity=f.by_guid(stable_guid(model["project_id"],kind,item_id))
        matrix=ifcopenshell.util.placement.get_local_placement(entity.ObjectPlacement)
        matrix[:3,3]+=direction*.1
        ifcopenshell.api.geometry.edit_object_placement(f,product=entity,matrix=matrix)
    path=tmp_path/"opening.ifc";f.write(str(path))
    updated,diff=sync_external_ifc(model,ROOT/"model.ifc",path,element_id=opening["id"],
                                    attribute="offset",reason="move window",operator="analyst")
    assert diff["after"]==pytest.approx(opening["parameters"]["offset"]["value"]+.1,abs=1e-5)
    assert opening["fill"] in diff["affected_elements"]


def test_retriangulation_must_preserve_vertices_and_full_surface():
    vertices=np.array([[0.,0.,0.],[1.,0.,0.],[1.,1.,0.],[0.,1.,0.]])
    first=np.array([[0,1,2],[0,2,3]]);alternate=np.array([[0,1,3],[1,2,3]])
    assert _same_retriangulated_surface(vertices,first,vertices,alternate)
    assert not _same_retriangulated_surface(vertices,first,vertices,alternate[:1])
    assert not _same_retriangulated_surface(vertices,first,vertices,np.array([[0,1,2],[0,1,3]]))
    moved=vertices.copy();moved[2,0]+=.001
    assert not _same_retriangulated_surface(vertices,first,moved,alternate)


def test_real_bonsai_wall_height_and_window_position_readback():
    model=real_model()
    height,diff=sync_external_ifc(model,ROOT/"model.ifc",ROUND4/"height-bonsai.ifc",
        element_id="wall-cf1d15bbd93c2d52",attribute="height",reason="Bonsai height",operator="analyst")
    assert diff["after"]==pytest.approx(3.5) and height["revision"]==2
    window,diff=sync_external_ifc(model,ROOT/"model.ifc",ROUND4/"window-bonsai.ifc",
        element_id="opening-34fcb929a4856871",attribute="offset",reason="Bonsai window move",operator="analyst")
    assert diff["after"]==pytest.approx(1.25,abs=1e-5)
    assert "ifcwindow-2ad5a81694a7ff78" in diff["affected_elements"] and window["revision"]==2
    with pytest.raises(ValueError,match="opening has no readable geometry"):
        sync_external_ifc(model,ROOT/"model.ifc",ROUND4/"window-recalculate-failed.ifc",
            element_id="opening-34fcb929a4856871",attribute="offset",reason="bad Bonsai edit",operator="analyst")
