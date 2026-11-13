"""Compare held-out object dimensions after calibration, without using them to build a model."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--prediction",type=Path,required=True)
    p.add_argument("--reference",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    prediction=json.loads(args.prediction.read_text());reference=json.loads(args.reference.read_text())
    if set(prediction.get("used_measurement_ids",[])) & {x["id"] for x in reference["measurements"]}:
        raise ValueError("held-out measurement was used during modeling or calibration")
    results=[]
    for item in reference["measurements"]:
        observed=prediction["dimensions_m"][item["axis"]];truth=item["value_m"]
        if any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or x<=0 for x in (observed,truth)):
            raise ValueError("dimensions must be finite positive metres")
        results.append({"id":item["id"],"axis":item["axis"],"prediction_m":observed,"reference_m":truth,
                        "absolute_error_m":abs(observed-truth),"relative_error":abs(observed-truth)/truth})
    if not results:raise ValueError("independent measurements required")
    output={"status":"MEASURED_ON_PROVIDED_REFERENCE","measurements":results,
            "warning":"review reference provenance; visualization or bounds do not prove surface accuracy"}
    args.output.write_text(json.dumps(output,indent=2)+"\n");print(json.dumps(output,indent=2));return 0


if __name__=="__main__":raise SystemExit(main())
