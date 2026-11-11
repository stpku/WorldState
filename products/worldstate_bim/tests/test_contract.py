"""Standard-library checks: runnable even in a minimal development environment."""

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from products.worldstate_bim.contract import (
    SCHEMA_VERSION,
    load_proposal,
    release_check,
    verify_images,
)


def fixture(photo_bytes=b"synthetic-test-photo-bytes"):
    digest = hashlib.sha256(photo_bytes).hexdigest()
    return {
        "contract": SCHEMA_VERSION,
        "project_id": "synthetic-room-01",
        "project_name": "Synthetic Teaching Room",
        "images": [
            {
                "evidence_id": "photo-01",
                "path": "photo-01.jpg",
                "sha256": digest,
                "captured_at": None,
                "provenance": "synthetic_test_input",
            }
        ],
        "anchors": [],
        "walls": [
            {
                "element_id": "wall-1",
                "start_m": [0.0, 0.0, 0.0],
                "end_m": [4.0, 0.0, 0.0],
                "height_m": 3.0,
                "thickness_m": 0.2,
                "basis": "inferred",
                "evidence_refs": ["photo-01"],
            }
        ],
    }


class ProposalTests(unittest.TestCase):
    def test_minimal_inferred_geometry_remains_draft(self):
        model = load_proposal(fixture())
        self.assertEqual(len(model.walls), 1)
        self.assertFalse(model.has_metric_anchor)
        with self.assertRaisesRegex(ValueError, "metric anchor"):
            release_check(model)
        release_check(model, allow_approximate=True)

    def test_independently_declared_scale_reference_allows_compiler(self):
        data = fixture()
        data["anchors"] = [
            {"evidence_id": "photo-01", "distance_m": 2.0, "basis": "documented"}
        ]
        model = load_proposal(data)
        self.assertTrue(model.has_metric_anchor)
        release_check(model)

    def test_rejects_untraceable_wall(self):
        data = fixture()
        data["walls"][0]["evidence_refs"] = ["invented-photo"]
        with self.assertRaisesRegex(ValueError, "unknown photo evidence"):
            load_proposal(data)

    def test_rejects_zero_length_and_invalid_units(self):
        data = fixture()
        data["walls"][0]["end_m"] = [0.0, 0.0, 0.0]
        with self.assertRaisesRegex(ValueError, "distinct"):
            load_proposal(data)
        data = fixture()
        data["walls"][0]["height_m"] = -1
        with self.assertRaisesRegex(ValueError, "positive"):
            load_proposal(data)

    def test_rejects_duplicate_elements(self):
        data = fixture()
        data["walls"].append(deepcopy(data["walls"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate BIM element"):
            load_proposal(data)

    def test_verify_photo_hashes_and_block_path_escape(self):
        payload = b"synthetic-test-photo-bytes"
        data = fixture(payload)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "photo-01.jpg").write_bytes(payload)
            model = load_proposal(data)
            verify_images(model, root)
            (root / "photo-01.jpg").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_images(model, root)
            data["images"][0]["path"] = "../other-file.jpg"
            with self.assertRaises((ValueError, FileNotFoundError)):
                verify_images(load_proposal(data), root)

    def test_reject_invalid_contract(self):
        data = fixture()
        data["contract"] = "unknown-contract"
        with self.assertRaisesRegex(ValueError, "contract"):
            load_proposal(data)


if __name__ == "__main__":
    unittest.main()
