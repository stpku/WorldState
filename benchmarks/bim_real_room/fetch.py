"""Fetch hash-pinned public dev inputs without overwriting existing files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(file: dict[str, str], destination: Path) -> None:
    """Verify existing bytes or download and atomically install new bytes."""
    name = file["name"]
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("manifest name must be a simple filename")
    target = destination / name
    if target.is_symlink():
        raise ValueError(f"refusing symlink target: {target}")
    if target.exists():
        if target.is_file() and file_hash(target) == file["sha256"]:
            print(f"verified existing {target}")
            return
        raise ValueError(f"refusing to overwrite a different file: {target}")
    for attempt in range(3):
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination, prefix=".download-", delete=False) as out:
                temporary = out.name
                request = urllib.request.Request(file["url"], headers={"User-Agent": "WorldState-BIM-benchmark/0.1"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    while block := response.read(1024 * 1024):
                        out.write(block)
            if file_hash(Path(temporary)) != file["sha256"]:
                raise ValueError(f"SHA-256 mismatch: {name}")
            # Hard linking is an atomic create and never overwrites an existing file.
            os.link(temporary, target)
            print(f"downloaded and verified {target}")
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise RuntimeError(f"could not download {name} after 3 attempts") from exc
            print(f"transient download failure for {name}; retrying")
            time.sleep(attempt + 1)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--with-model", action="store_true", help="Also download the ~100 MB model")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(__file__).with_name("manifest.json").read_text())
    for item in manifest["files"]:
        if item["kind"] == "dataset" or args.with_model:
            fetch(item, args.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
