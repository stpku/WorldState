"""The harness-facing tools operate on validated product data, not a mock runtime."""
import json
from pathlib import Path
import pytest
from products.worldstate_bim.modeling_tools import (apply_constraint,compare_revisions,inspect_element,
    inspect_evidence,propose_elements,update_element,validate_geometry)

ROOT=Path(__file__).resolve().parents[3]/"examples/bim_real_scan_craslab/room_round3"


def test_toolchain_real_provider_model_and_error_feedback():
    model=json.loads((ROOT/"model.json").read_text())
    assert inspect_evidence(model)[0]["kind"]=="provider_result"
    assert propose_elements(model)["new_inference"] is False
    target=next(e for e in model["elements"] if e["ifc_type"]=="IfcOpeningElement")
    assert inspect_element(model,target["id"])["element"]["id"]==target["id"]
    assert validate_geometry(model)["issues"]==[]
    with pytest.raises(ValueError,match="OPENING_OUTSIDE_WALL"):
        update_element(model,target["id"],"offset",100,reason="invalid trial",operator="analyst")
    revised,diff=update_element(model,target["id"],"offset",1.25,reason="corrected trial",operator="analyst")
    assert target["id"] in compare_revisions(model,revised)["elements"]["changed"]
    assert target["fill"] in diff["affected_elements"]


def test_conflicting_constraint_is_not_silently_applied():
    model=json.loads((ROOT/"model.json").read_text())
    walls=[e["id"] for e in model["elements"] if e["ifc_type"]=="IfcWall"]
    with pytest.raises(ValueError):
        apply_constraint(model,kind="perpendicular",a=walls[0],b=walls[0],reason="invalid",operator="user")
