"""Asset evaluation must not reuse a calibration measurement as held-out truth."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[3]/"benchmarks/ws_mesh/hunyuan_freecad/evaluate_dimensions.py"


def test_dimension_evaluation_rejects_truth_leakage(tmp_path):
    prediction=tmp_path/"prediction.json";reference=tmp_path/"reference.json";output=tmp_path/"result.json"
    prediction.write_text(json.dumps({"used_measurement_ids":["anchor"],"dimensions_m":{"length":1.02}}))
    reference.write_text(json.dumps({"measurements":[{"id":"anchor","axis":"length","value_m":1.0}]}))
    result=subprocess.run([sys.executable,str(SCRIPT),"--prediction",str(prediction),"--reference",str(reference),"--output",str(output)],capture_output=True,text=True)
    assert result.returncode!=0 and not output.exists()
    reference.write_text(json.dumps({"measurements":[{"id":"holdout","axis":"length","value_m":1.0}]}))
    result=subprocess.run([sys.executable,str(SCRIPT),"--prediction",str(prediction),"--reference",str(reference),"--output",str(output)],capture_output=True,text=True)
    assert result.returncode==0
    assert abs(json.loads(output.read_text())["measurements"][0]["absolute_error_m"]-.02)<1e-9
