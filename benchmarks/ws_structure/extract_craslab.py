"""Create a deterministic labelled development sample from the CRASLAB archive.

The 4.27 GB original is streamed; no raw dataset is committed. Labels are
written separately so geometry inference can operate on XYZ without seeing
the reference classes. This systematically sampled subset is not an independent scene test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np

ARCHIVE_SHA256 = "933732e81910116cec5e74c9205074b82d1f571f3d9816386b68a0a909112671"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stride", type=int, default=2000)
    args = parser.parse_args()
    if args.stride < 1 or sha256(args.archive) != ARCHIVE_SHA256:
        raise ValueError("invalid stride or CRASLAB archive SHA-256")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if (args.output_dir / "xyz.npy").exists():
        raise FileExistsError("output exists")
    xyz, labels = [], []
    processed = 0
    with zipfile.ZipFile(args.archive) as archive, archive.open("CRASLAB_annotated.asc") as stream:
        header, count = stream.readline(), stream.readline()
        if not header.startswith(b"//X") or int(count.strip()) != 584701977:
            raise ValueError("unexpected CRASLAB input format")
        remainder = b""
        while True:
            block = stream.read(8*1024*1024)
            if not block:
                break
            data = remainder + block
            end = data.rfind(b"\n")
            if end < 0:
                remainder = data
                continue
            lines = data[:end].split(b"\n")
            remainder = data[end+1:]
            offset = (-processed) % args.stride
            for line in lines[offset::args.stride]:
                row = line.split()
                if len(row) != 8:
                    raise ValueError("unexpected CRASLAB point record")
                label = int(float(row[7]))
                if label < 0 or label > 33:
                    raise ValueError(f"unknown CRASLAB class: {label}")
                xyz.append([float(row[0]), float(row[1]), float(row[2])])
                labels.append(label)
            processed += len(lines)
            if processed % 50000000 < len(lines):
                print(f"processed {processed} records", flush=True)
    points = np.asarray(xyz, dtype=np.float64)
    gt = np.asarray(labels, dtype=np.uint8)
    if len(points) == 0 or not np.any(gt == 3):
        raise ValueError("no labelled wall samples found")
    np.save(args.output_dir/"xyz.npy", points)
    np.save(args.output_dir/"labels.npy", gt)
    unique, counts = np.unique(gt, return_counts=True)
    report = {"dataset": "CRASLAB", "license": "CC-BY-4.0", "archive_sha256": ARCHIVE_SHA256,
              "selection": "every Nth source record across the full archive; development sample, not an independent scene",
              "stride": args.stride, "processed_records_approx": processed,
              "xyz_sha256": sha256(args.output_dir/"xyz.npy"), "labels_sha256": sha256(args.output_dir/"labels.npy"),
              "labels": {str(int(k)): int(v) for k,v in zip(unique, counts)},
              "class_map": {"0": "unassigned", "1": "ceiling", "2": "floor", "3": "wall"}}
    (args.output_dir/"sample.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
