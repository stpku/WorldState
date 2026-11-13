"""Freeze a candidate, then evaluate it against separately held room references.

This tool implements measurable protocol checks. Independent IFC authoring,
GUID/edit review and reference preparation still require external evidence and
remain NOT_EVALUATED here. A report from this script alone cannot release V0.2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PRECISION_MIN = 0.90
RECALL_MIN = 0.80
DIMENSION_FLOOR_M = 0.05
DIMENSION_RELATIVE = 0.02
LABOR_REDUCTION_MIN = 0.20


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
    return h.hexdigest()


def write_new(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as stream:json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write("\n")


def freeze(candidate_dir: Path, evidence_index: Path | None = None) -> dict:
    """Hash model and input evidence before any private references are opened."""
    from products.worldstate_bim.room_ir import validate_room
    ir=candidate_dir/"model.json";ifc=candidate_dir/"model.ifc"
    model=json.loads(ir.read_text());validate_room(model)
    model_photos={e["sha256"] for e in model["evidence"] if e.get("kind")=="image" and e.get("sha256")}
    index=evidence_index or candidate_dir.parent/"evidence-index.json"
    index_hash=None;inventory_status="NOT_PROVIDED";uploads=set()
    if index.exists():
        if index.is_symlink():raise ValueError("evidence index cannot be a symlink")
        data=json.loads(index.read_text())
        if data.get("schema")!="worldstate-studio-evidence/0.1" or not isinstance(data.get("uploads"),list):
            raise ValueError("invalid Studio evidence inventory")
        for item in data["uploads"]:
            digest=item.get("sha256");extension=item.get("extension")
            if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest) or extension not in {".png",".jpg"}:
                raise ValueError("invalid Studio evidence inventory entry")
            photo=index.parent/"evidence"/(digest+extension)
            if photo.is_symlink() or not photo.is_file() or sha256(photo)!=digest:
                raise ValueError("uploaded image is missing or its hash changed")
            uploads.add(digest)
        if not model_photos<=uploads:raise ValueError("model photo evidence is missing from Studio inventory")
        index_hash=sha256(index);inventory_status="VERIFIED_STUDIO_INDEX"
    photos=sorted(model_photos|uploads)
    return {"schema":"ws-realroom-frozen-candidate/0.1","created_at":datetime.now(timezone.utc).isoformat(),
            "project_id":model["project_id"],"revision":model["revision"],"model_json_sha256":sha256(ir),
            "model_ifc_sha256":sha256(ifc),"input_photo_sha256":photos,"model_photo_sha256":sorted(model_photos),
            "evidence_index_sha256":index_hash,"evidence_inventory_status":inventory_status,
            "protocol":"benchmarks/ws_realroom/PROTOCOL.md",
            "warning":"Hashing is not proof of blind role separation; retain independent collection and access logs."}


def _safe_ref_file(root: Path, item: dict) -> Path:
    name=item.get("path");expected=item.get("sha256")
    if not isinstance(name,str) or not name or not isinstance(expected,str) or len(expected)!=64:
        raise ValueError("reference file requires relative path and SHA-256")
    path=(root/name).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file() or sha256(path)!=expected:
        raise ValueError("reference path is outside its private directory or SHA-256 does not match")
    return path


def _positive(value: Any, label: str, *, zero: bool=False) -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or (value<0 if zero else value<=0):
        raise ValueError(f"{label} must be a finite {'nonnegative' if zero else 'positive'} number")
    return float(value)


def _labor(data: dict | None) -> dict:
    if data is None:return {"status":"NOT_MEASURED","reason":"paired human and assisted runs were not supplied"}
    runs=data.get("pairs") if isinstance(data,dict) else None
    if not isinstance(runs,list) or len(runs)<3:
        return {"status":"NOT_MEASURED","reason":"at least three paired runs are required"}
    seen=set();accepted={"manual":[],"assisted":[]};success={"manual":0,"assisted":0}
    fields=("prepare","annotate","correct","review")
    for pair in runs:
        if not isinstance(pair,dict) or not pair.get("pair_id") or pair["pair_id"] in seen:
            raise ValueError("each paired run needs a unique ID")
        seen.add(pair["pair_id"])
        inputs=pair.get("input_manifest_sha256")
        if not isinstance(inputs,str) or len(inputs)!=64 or any(c not in "0123456789abcdef" for c in inputs):
            raise ValueError("each pair requires the same frozen input-manifest SHA-256")
        for mode in ("manual","assisted"):
            run=pair.get(mode)
            if (not isinstance(run,dict) or not isinstance(run.get("quality_passed"),bool) or not run.get("reviewer") or
                    run.get("input_manifest_sha256")!=inputs):
                raise ValueError("each run requires a quality decision, reviewer and matching input hash")
            times=run.get("human_seconds")
            if not isinstance(times,dict):raise ValueError("each run needs separate human time stages")
            total=sum(_positive(times.get(k),f"{mode} {k}",zero=True) for k in fields)
            _positive(run.get("automatic_seconds"),"automatic time",zero=True)
            _positive(run.get("gpu_seconds"),"GPU time",zero=True)
            _positive(run.get("cost"),"cost",zero=True)
            if not isinstance(run.get("failures"),int) or isinstance(run["failures"],bool) or run["failures"]<0:
                raise ValueError("failure counts must be nonnegative integers")
            if run["quality_passed"]:accepted[mode].append(total);success[mode]+=1
    if not accepted["manual"] or not accepted["assisted"]:
        return {"status":"NOT_MEASURED","reason":"no accepted model in at least one mode","runs":len(runs),"success":success}
    manual=statistics.median(accepted["manual"]);assisted=statistics.median(accepted["assisted"])
    if manual<=0:return {"status":"NOT_MEASURED","reason":"manual accepted-model median must be positive"}
    reduction=1-assisted/manual
    return {"status":"PASS" if reduction>=LABOR_REDUCTION_MIN and success["assisted"]>=success["manual"] else "FAIL",
            "pairs":len(runs),"manual_accepted":success["manual"],"assisted_accepted":success["assisted"],
            "manual_median_human_seconds":manual,"assisted_median_human_seconds":assisted,
            "reduction_fraction":reduction,"quality_status":"reviewer_attested_not_independently_rechecked"}


def evaluate(candidate_dir: Path, frozen: dict, reference_dir: Path, reference: dict, labor: dict | None,
             evidence_index: Path | None = None) -> dict:
    """Evaluate frozen output; private reference is read only by this function."""
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.validate
    from products.worldstate_bim.room_ifc import stable_guid
    from products.worldstate_bim.room_ir import validate_room
    c=candidate_dir.resolve(strict=True);r=reference_dir.resolve(strict=True)
    if c.is_relative_to(r) or r.is_relative_to(c):raise ValueError("private reference and candidate directories must be separate")
    if frozen.get("schema")!="ws-realroom-frozen-candidate/0.1":raise ValueError("invalid frozen manifest")
    ir=c/"model.json";ifc=c/"model.ifc"
    if sha256(ir)!=frozen.get("model_json_sha256") or sha256(ifc)!=frozen.get("model_ifc_sha256"):
        raise ValueError("candidate changed after freezing")
    model=json.loads(ir.read_text());validate_room(model)
    if model["project_id"]!=frozen.get("project_id") or model["revision"]!=frozen.get("revision"):
        raise ValueError("frozen model identity differs")
    current=freeze(c,evidence_index)
    for field in ("input_photo_sha256","model_photo_sha256","evidence_index_sha256","evidence_inventory_status"):
        if current[field]!=frozen.get(field):raise ValueError("frozen input inventory differs from candidate")
    if reference.get("schema")!="ws-realroom-reference/0.1":raise ValueError("invalid private reference schema")
    ref_ifc=_safe_ref_file(r,reference.get("reference_ifc",{}));ref=ifcopenshell.open(str(ref_ifc))
    if sha256(ref_ifc)==sha256(ifc):raise ValueError("reference IFC is identical to candidate IFC")
    ref_walls=reference.get("visible_wall_guids")
    if not isinstance(ref_walls,list) or not ref_walls or len(set(ref_walls))!=len(ref_walls):
        raise ValueError("visible reference walls must be unique")
    for guid in ref_walls:
        wall=ref.by_guid(guid)
        if wall is None or not wall.is_a("IfcWall"):raise ValueError("reference wall GUID missing from reference IFC")
    walls={e["id"]:e for e in model["elements"] if e["ifc_type"]=="IfcWall"}
    matches=reference.get("matches")
    if not isinstance(matches,list):raise ValueError("independently reviewed wall matches are required")
    pairs=[]
    for match in matches:
        if not isinstance(match,dict) or match.get("reference_guid") not in ref_walls or match.get("candidate_id") not in walls or not match.get("reviewer"):
            raise ValueError("each wall match needs valid IDs and an independent reviewer")
        pairs.append((match["reference_guid"],match["candidate_id"]))
    if len({x[0] for x in pairs})!=len(pairs) or len({x[1] for x in pairs})!=len(pairs):
        raise ValueError("wall matching must be one-to-one")
    precision=len(pairs)/len(walls) if walls else 0.0;recall=len(pairs)/len(ref_walls)
    mapping=dict(pairs);nodes={n["id"]:n for n in model["nodes"]};dimensions=[];measurement_ids=set()
    for measurement in reference.get("measurements",[]):
        mid=measurement.get("id");guid=measurement.get("reference_guid");attr=measurement.get("attribute")
        if not mid or mid in measurement_ids or guid not in ref_walls or attr not in {"length","height"} or not measurement.get("method") or not measurement.get("operator"):
            raise ValueError("each independent measurement needs unique ID, wall, length/height, method and operator")
        if mid in {e["id"] for e in model["evidence"]}:raise ValueError("measurement reference leaked into candidate evidence")
        measurement_ids.add(mid);actual=_positive(measurement.get("value_m"),"reference dimension")
        uncertainty=_positive(measurement.get("uncertainty_m"),"measurement uncertainty",zero=True)
        tolerance=max(DIMENSION_FLOOR_M,DIMENSION_RELATIVE*actual);candidate_id=mapping.get(guid);predicted=None
        if candidate_id:
            wall=walls[candidate_id]
            if attr=="height":predicted=wall["parameters"]["height"]["value"]
            else:
                a,b=nodes[wall["start"]],nodes[wall["end"]]
                if None not in (a["x"],a["y"],b["x"],b["y"]):predicted=math.dist((a["x"],a["y"]),(b["x"],b["y"]))
        error=abs(predicted-actual) if predicted is not None else None
        dimensions.append({"id":mid,"reference_guid":guid,"candidate_id":candidate_id,"attribute":attr,
            "reference_m":actual,"candidate_m":predicted,"error_m":error,"tolerance_m":tolerance,
            "uncertainty_m":uncertainty,"pass":error is not None and error<=tolerance and uncertainty<tolerance/3})
    holdouts=reference.get("holdout_photos",[])
    if not isinstance(holdouts,list):raise ValueError("holdout photo list required")
    holdout_hashes=[]
    for item in holdouts:
        path=_safe_ref_file(r,item);holdout_hashes.append(sha256(path))
    if len(set(holdout_hashes))!=len(holdout_hashes):raise ValueError("holdout photos must be distinct")
    all_evidence_hashes={e.get("sha256") for e in model["evidence"] if e.get("sha256")}|set(frozen["input_photo_sha256"])
    if set(holdout_hashes)&all_evidence_hashes:raise ValueError("holdout photo hash appears in candidate evidence")
    candidate=ifcopenshell.open(str(ifc));logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(candidate,logger)
    geometry=0
    for wall_id in walls:
        entity=candidate.by_guid(stable_guid(model["project_id"],"IfcWall",wall_id))
        if entity is not None and entity.is_a("IfcWall"):
            try:
                if ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),entity):geometry+=1
            except RuntimeError:pass
    labor_result=_labor(labor)
    gates={"input_photos":len(frozen.get("input_photo_sha256",[]))>=3 and len(frozen.get("model_photo_sha256",[]))>=3,
           "input_evidence_inventory":frozen.get("evidence_inventory_status")=="VERIFIED_STUDIO_INDEX",
           "visible_wall_count":len(ref_walls)>=3 and len(pairs)>=3,
           "wall_precision":precision>=PRECISION_MIN,"wall_recall":recall>=RECALL_MIN,
           "independent_dimensions":reference.get("independent_measurements_declared") is True and bool(reference.get("reference_reviewer")) and
               len(dimensions)>=3 and len({x["reference_guid"] for x in dimensions})>=3 and all(x["pass"] for x in dimensions),
           "holdout_photos":len(holdouts)>=2,
           "ifcopenshell_schema_geometry_diagnostic":candidate.schema=="IFC4" and not logger.statements and geometry==len(walls) and len(candidate.by_type("IfcWall"))==len(walls) and len(walls)>0,
           "human_cost":labor_result["status"],"independent_ifc_engine":"NOT_EVALUATED",
           "independent_authoring_edit":"NOT_EVALUATED","guid_retention":"NOT_EVALUATED","external_ir_sync":"NOT_EVALUATED"}
    return {"schema":"ws-realroom-evaluation/0.1","release_status":"NOT_RELEASE_READY",
            "candidate_sha256":frozen["model_ifc_sha256"],"reference_ifc_sha256":sha256(ref_ifc),
            "matching":"one-to-one reviewer-supplied mapping, not automatic matching",
            "wall_instances":{"candidate":len(walls),"reference_visible":len(ref_walls),"matched":len(pairs),"precision":precision,"recall":recall},
            "dimensions":dimensions,"holdout_sha256":holdout_hashes,"labor":labor_result,"gates":gates,
            "limitations":["input and reference separation requires procedural access control",
                "holdout images are hashed, not visually reviewed by this script",
                "IfcOpenShell is also used by the exporter; an independent IFC engine is still required",
                "independent application editing, GUID retention and external IR sync are not evaluated here",
                "this report alone cannot establish release readiness"]}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="command",required=True)
    f=sub.add_parser("freeze");f.add_argument("--candidate-dir",type=Path,required=True);f.add_argument("--output",type=Path,required=True)
    f.add_argument("--evidence-index",type=Path,help="Studio evidence index, if not in the candidate directory's parent")
    e=sub.add_parser("evaluate");e.add_argument("--candidate-dir",type=Path,required=True);e.add_argument("--frozen",type=Path,required=True)
    e.add_argument("--reference-dir",type=Path,required=True);e.add_argument("--reference",type=Path,required=True)
    e.add_argument("--labor",type=Path);e.add_argument("--evidence-index",type=Path);e.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="freeze":result=freeze(args.candidate_dir,args.evidence_index)
    else:
        reference_path=args.reference.resolve(strict=True);root=args.reference_dir.resolve(strict=True)
        if not reference_path.is_relative_to(root):raise ValueError("reference JSON must be inside private reference directory")
        result=evaluate(args.candidate_dir,json.loads(args.frozen.read_text()),root,json.loads(reference_path.read_text()),
                        json.loads(args.labor.read_text()) if args.labor else None,args.evidence_index)
    write_new(args.output,result);print(json.dumps({"output":str(args.output),"status":result.get("release_status","FROZEN")},ensure_ascii=False))
    return 0


if __name__=="__main__":raise SystemExit(main())
