"""Download the 32 fixed, SHA-256-pinned TUM development photos."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path

from benchmarks.bim_real_room.fetch import fetch

BASE = ("https://huggingface.co/datasets/voviktyl/TUM_RGBD-SLAM/resolve/"
        "76818471ae555dd6cd4e100b7cedcccda660448d/rgbd_dataset_freiburg1_room/rgb/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    items = json.loads(Path(__file__).with_name("tum-32-manifest.json").read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, {"name": x["name"], "sha256": x["sha256"], "url": BASE+x["name"]}, args.output_dir) for x in items]
        for future in futures:
            future.result()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
