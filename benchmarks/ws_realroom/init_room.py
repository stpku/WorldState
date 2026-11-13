"""Create a private WS-RealRoom collection workspace without source data.

This initializes folders only. It does not create measurements, authorize data,
or run the frozen acceptance protocol. Existing destination is never changed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def initialize(destination: Path, room_id: str) -> None:
    if not room_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in room_id):
        raise ValueError("room ID must contain only letters, numbers, underscore or dash")
    destination.mkdir(parents=True, exist_ok=False)
    for directory in ("input/photos", "private-reference/holdout", "runs/manual", "runs/assisted", "reports"):
        (destination / directory).mkdir(parents=True)
    (destination / ".gitignore").write_text("*\n!.gitignore\n")
    manifest = {"schema": "ws-realroom-capture/0.1", "room_id": room_id, "status": "NOT_COLLECTED",
                "authorization": "UNKNOWN", "source_license": "UNKNOWN", "capture_time": "UNKNOWN",
                "input_photos": [], "scale_anchor": "input/anchor.json", "annotations": "input/annotations.json",
                "assumptions": "input/assumptions.json", "reference_is_private": True,
                "protocol": "benchmarks/ws_realroom/PROTOCOL.md", "final_acceptance_run": False}
    for path, data in (("capture-manifest.json", manifest),
                       ("input/anchor.json", {"status": "UNKNOWN", "value_m": None, "source": None, "uncertainty_m": None}),
                       ("input/annotations.json", {"status": "NOT_COLLECTED", "annotations": []}),
                       ("input/assumptions.json", {"status": "NOT_COLLECTED", "assumptions": []})):
        (destination / path).write_text(json.dumps(data, indent=2) + "\n")
    (destination / "LICENSE-and-consent.txt").write_text("NOT COLLECTED: record permission, rights, scope and publication restrictions.\n")
    (destination / "private-reference/dimensions.csv").write_text("measurement_id,object_id,start,end,value_m,uncertainty_m,measurement_method,operator,time\n")
    (destination / "COLLECTION-CHECKLIST.md").write_text(
        "# 数据采集清单\n\n"
        "- [ ] 确认房间和照片的采集、处理及公开许可。\n"
        "- [ ] 采集至少三张可见多个墙角的建模照片，另留两张视角独立的照片。\n"
        "- [ ] 独立测量并记录一项建模尺度参照及工具误差。\n"
        "- [ ] 由独立评测人测量至少三项不用于建模的墙体尺寸及误差。\n"
        "- [ ] 在 private-reference 制作有来源与未知状态的参考 IFC，冻结并哈希。\n"
        "- [ ] 同输入记录三组手工和辅助建模的配对耗时、失败及复核。\n"
        "- [ ] 严格执行仓库 benchmarks/ws_realroom/PROTOCOL.md 的现有冻结门槛。\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--room-id", required=True)
    args = parser.parse_args()
    initialize(args.destination, args.room_id)
    print(f"Created private collection template at {args.destination}; no data or acceptance results created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
