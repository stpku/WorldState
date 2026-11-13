"""Check integrity and no-overwrite semantics without network access."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from benchmarks.bim_real_room.fetch import fetch


class BenchmarkFetchTests(unittest.TestCase):
    def test_checks_hash_and_refuses_to_replace_existing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.write_bytes(b"public evidence")
            output = root / "output"
            output.mkdir()
            item = {"name": "frame.png", "url": source.as_uri(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
            fetch(item, output)
            self.assertEqual((output / "frame.png").read_bytes(), b"public evidence")
            (output / "frame.png").write_bytes(b"existing work")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                fetch(item, output)
            self.assertEqual((output / "frame.png").read_bytes(), b"existing work")

    def test_hash_mismatch_does_not_leave_partial_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.write_bytes(b"unexpected")
            item = {"name": "frame.png", "url": source.as_uri(), "sha256": "0" * 64}
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                fetch(item, root)
            self.assertFalse((root / "frame.png").exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["source"])
