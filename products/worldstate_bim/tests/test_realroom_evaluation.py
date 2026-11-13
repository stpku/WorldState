"""Synthetic-only tests for frozen independent-room evaluation mechanics."""
import json
from pathlib import Path
import pytest
from PIL import Image
from benchmarks.ws_realroom.evaluate import evaluate, freeze, sha256
from examples.bim_synthetic_room_round3.generate import synthetic_room
from products.worldstate_bim.room_cli import save_version


def fixture(tmp_path):
    import ifcopenshell
    candidate=tmp_path/"candidate";save_version(synthetic_room(),candidate)
    private=tmp_path/"private-reference";private.mkdir()
    ref=private/"reference.ifc";ref.write_bytes((candidate/"model.ifc").read_bytes())
    f=ifcopenshell.open(str(ref));walls=f.by_type("IfcWall")
    holdouts=[]
    for i,color in enumerate(("red","blue")):
        path=private/f"holdout-{i}.png";Image.new("RGB",(5,5),color).save(path)
        holdouts.append({"path":path.name,"sha256":sha256(path)})
    reference={"schema":"ws-realroom-reference/0.1","reference_ifc":{"path":ref.name,"sha256":sha256(ref)},
        "visible_wall_guids":[w.GlobalId for w in walls],
        "matches":[{"reference_guid":w.GlobalId,"candidate_id":w.Name,"reviewer":"synthetic reviewer"} for w in walls],
        "measurements":[{"id":f"hidden-{i}","reference_guid":w.GlobalId,"attribute":"length",
            "value_m":4 if w.Name in {"wall-1","wall-3"} else 3,"uncertainty_m":0.001,
            "method":"synthetic","operator":"synthetic reviewer"} for i,w in enumerate(walls[:3])],
        "holdout_photos":holdouts}
    def run(seconds):return {"quality_passed":True,"reviewer":"synthetic reviewer",
        "human_seconds":{"prepare":seconds,"annotate":0,"correct":0,"review":0},
        "automatic_seconds":0,"gpu_seconds":0,"cost":0,"failures":0}
    labor={"pairs":[{"pair_id":str(i),"manual":run(100),"assisted":run(70)} for i in range(3)]}
    return candidate,private,reference,labor


def test_frozen_room_metrics_and_cost_never_claim_release_without_independent_checks(tmp_path):
    candidate,private,reference,labor=fixture(tmp_path)
    report=evaluate(candidate,freeze(candidate),private,reference,labor)
    assert report["wall_instances"]["precision"]==1 and report["wall_instances"]["recall"]==1
    assert report["gates"]["independent_dimensions"] and report["gates"]["holdout_photos"]
    assert report["labor"]["status"]=="PASS" and report["labor"]["reduction_fraction"]==pytest.approx(.3)
    assert report["gates"]["input_photos"] is False and report["gates"]["independent_authoring_edit"]=="NOT_EVALUATED"
    assert report["release_status"]=="NOT_RELEASE_READY"


def test_changed_candidate_and_holdout_leak_are_rejected(tmp_path):
    candidate,private,reference,labor=fixture(tmp_path);frozen=freeze(candidate)
    model_path=candidate/"model.json";model=json.loads(model_path.read_text());model["revision"]+=1
    model_path.write_text(json.dumps(model))
    with pytest.raises(ValueError,match="changed after freezing"):evaluate(candidate,frozen,private,reference,labor)
    model["evidence"].append({"id":"leaked-image","kind":"image","sha256":reference["holdout_photos"][0]["sha256"]})
    model_path.write_text(json.dumps(model));frozen=freeze(candidate)
    with pytest.raises(ValueError,match="holdout photo hash"):evaluate(candidate,frozen,private,reference,labor)


def test_uncertain_measurements_and_failed_assisted_runs_do_not_pass(tmp_path):
    candidate,private,reference,labor=fixture(tmp_path)
    reference["measurements"][0]["uncertainty_m"]=1
    labor["pairs"][0]["assisted"]["quality_passed"]=False
    report=evaluate(candidate,freeze(candidate),private,reference,labor)
    assert not report["gates"]["independent_dimensions"] and report["labor"]["status"]=="FAIL"
