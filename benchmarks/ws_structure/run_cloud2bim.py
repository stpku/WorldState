"""Run pinned upstream Cloud2BIM on the CRASLAB development XYZ sample.

Only plotting is adapted: LaTeX text rendering is disabled for headless hosts.
Output metadata includes an explicitly fictitious 0/0 site coordinate and
assumed floor, ceiling and wall material properties; this is a research run.
"""
from __future__ import annotations

import argparse
import os
import runpy
import subprocess
import sys
from pathlib import Path

import numpy as np
import yaml

REVISION = "cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source_checkout.resolve(), args.output_dir.resolve()
    revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain"], check=True, capture_output=True, text=True).stdout
    if revision != REVISION or dirty:
        raise ValueError("Cloud2BIM checkout must be clean and match the pinned revision")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "images/pdf").mkdir(parents=True)
    xyz = np.load(args.points, allow_pickle=False)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 100 or not np.isfinite(xyz).all():
        raise ValueError("expected finite XYZ points")
    xyz_path = output / "sample.xyz"
    np.savetxt(xyz_path, xyz, header="X Y Z", comments="", fmt="%.6f")
    config = yaml.safe_load((source / "config.yaml").read_text())
    config.update({"e57_input": False, "xyz_files": [str(xyz_path)], "dilute": False,
        "pc_resolution": 0.02, "grid_coefficient": 5, "output_ifc": str(output / "cloud2bim.ifc"),
        "ifc_project_name": "CRASLAB development experiment", "ifc_project_long_name": "WorldState reproduction",
        "ifc_author_name": "WorldState", "ifc_author_surname": "Research", "ifc_author_organization": "WorldState",
        "ifc_building_name": "CRASLAB", "ifc_building_type": "Unknown", "ifc_building_phase": "Research",
        "ifc_site_latitude": [0, 0, 0], "ifc_site_longitude": [0, 0, 0], "ifc_site_elevation": 0.0,
        "material_for_objects": "UNSPECIFIED-ASSUMED"})
    config_path = output / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    os.chdir(output)
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    old_rc = plt.rc
    def headless_rc(group, **kwargs):
        if group == "text" and "usetex" in kwargs:
            kwargs["usetex"] = False
        return old_rc(group, **kwargs)
    plt.rc = headless_rc
    sys.path.insert(0, str(source))
    sys.argv = [str(source / "cloud2entities.py"), str(config_path)]
    runpy.run_path(str(source / "cloud2entities.py"), run_name="__main__")


if __name__ == "__main__":
    main()
