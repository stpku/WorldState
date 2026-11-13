"""Integration checks against the public CRASLAB provider artifact."""
from pathlib import Path
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.guid
import ifcopenshell.validate
import numpy as np
from products.worldstate_bim.cloud2bim_provider import import_cloud2bim
from products.worldstate_bim.room_ifc import export_room

SOURCE=Path(__file__).resolve().parents[3]/"examples/bim_real_scan_craslab/cloud2bim-unverified.ifc"


def test_real_provider_ir_to_ifc_preserves_wall_bounds_and_quarantines_errors(tmp_path):
    model,mapping,report=import_cloud2bim(SOURCE,project_id="craslab-test")
    assert report["imported_counts"]=={"IfcWall":8,"IfcSlab":1,"IfcOpeningElement":5,"IfcWindow":5}
    assert len(report["quarantined"])==4
    assert {q["ifc_type"] for q in report["quarantined"]}=={"IfcWall","IfcSlab","IfcOpeningElement","IfcWindow"}
    assert all(e["classification"]["status"]=="inferred" for e in model["elements"])
    path=export_room(model,tmp_path/"room.ifc")
    before,after=ifcopenshell.open(str(SOURCE)),ifcopenshell.open(str(path))
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(after,logger)
    assert not logger.statements
    assert len(after.by_type("IfcRelVoidsElement"))==len(after.by_type("IfcRelFillsElement"))==5
    assert after.by_type("IfcSite")[0].RefLatitude is None
    assert not after.by_type("IfcWindowType")
    settings=ifcopenshell.geom.settings();settings.set("use-world-coords",True)
    def bounds(entity):
        shape=ifcopenshell.geom.create_shape(settings,entity)
        points=np.asarray(shape.geometry.verts).reshape(-1,3)
        return np.r_[points.min(axis=0),points.max(axis=0)]
    for item in model["elements"]:
        if item["ifc_type"]=="IfcWall":
            source_wall=before.by_guid(item["source_guid"])
            exported=next(w for w in after.by_type("IfcWall") if w.Name==item["id"])
            assert np.allclose(bounds(source_wall),bounds(exported),atol=1e-5)
    assert mapping["schema"]=="cloud2bim-identities/0.1"


def test_provider_reuses_identity_if_external_guid_changes_but_geometry_matches(tmp_path):
    first,mapping,_=import_cloud2bim(SOURCE,project_id="craslab-test")
    source=ifcopenshell.open(str(SOURCE));wall=source.by_type("IfcWall")[0]
    previous=wall.GlobalId
    wall.GlobalId=ifcopenshell.guid.new()
    changed=tmp_path/"same-geometry.ifc";source.write(str(changed))
    second,_,_=import_cloud2bim(changed,project_id="craslab-test",registry=mapping)
    assert next(w["id"] for w in first["elements"] if w.get("source_guid")==previous)==next(
        w["id"] for w in second["elements"] if w.get("source_guid")==wall.GlobalId)
