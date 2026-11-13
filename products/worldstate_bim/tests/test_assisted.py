"""Synthetic regression checks for actual scaling and IFC revision semantics."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(all(importlib.util.find_spec(x) for x in ("numpy", "cv2", "ifcopenshell")),
                     "assisted BIM dependencies are optional")
class AssistedTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "photo.png"
        self.depth = self.root / "depth.png"
        cv2.imwrite(str(self.image), np.full((80, 100, 3), 127, dtype=np.uint8))
        cv2.imwrite(str(self.depth), np.full((80, 100), 10000, dtype=np.uint16))

    def tearDown(self):
        self.temp.cleanup()

    def candidate(self, anchor_m):
        from products.worldstate_bim.assisted import create_candidate
        return create_candidate(self.image, self.depth, roi=(5, 5, 95, 75),
            anchor_pixels=(20, 40, 80, 40), anchor_m=anchor_m,
            anchor_description="synthetic scale test", anchor_independence="same_sensor",
            thickness_m=0.12, project_id="test-assisted", operator="analyst", intrinsics=(525,525,319.5,239.5))[0]

    def test_anchor_scale_changes_geometry_and_tampered_anchor_fails(self):
        from products.worldstate_bim.parametric_ir import validate_ir
        first, second = self.candidate(0.5), self.candidate(1.0)
        p = lambda m: m["elements"][0]["parameters"]
        self.assertAlmostEqual(p(second)["length"]["value"], p(first)["length"]["value"]*2)
        self.assertAlmostEqual(p(second)["visible_height"]["value"], p(first)["visible_height"]["value"]*2)
        self.assertEqual(p(first)["thickness"]["status"], "assumed")
        self.assertEqual(p(second)["thickness"]["value"], p(first)["thickness"]["value"])
        broken = copy.deepcopy(first)
        broken["scale"]["metres_per_unit"] *= 2
        with self.assertRaisesRegex(ValueError, "scale"):
            validate_ir(broken)

    def test_ifc_revision_retains_guid_and_preserves_prior_model(self):
        import ifcopenshell
        from products.worldstate_bim.assisted import revise_length, write_model
        first = self.candidate(0.5)
        original_length = first["elements"][0]["parameters"]["length"]["value"]
        second, diff = revise_length(first, "wall-patch-1", original_length+0.1, "synthetic edit", operator="analyst")
        before_ifc, _ = write_model(first, self.root, self.root / "v1")
        after_ifc, _ = write_model(second, self.root, self.root / "v2")
        a = ifcopenshell.open(str(before_ifc)).by_type("IfcWall")[0]
        b = ifcopenshell.open(str(after_ifc)).by_type("IfcWall")[0]
        self.assertEqual(a.GlobalId, b.GlobalId)
        self.assertEqual(first["elements"][0]["parameters"]["length"]["value"], original_length)
        self.assertEqual(diff["after"]["status"], "inferred")
        self.assertEqual(second["validation"]["status"], "REQUIRES_REVALIDATION")

    def test_anchor_with_missing_depth_fails_closed(self):
        from products.worldstate_bim.assisted import create_candidate
        with self.assertRaisesRegex(ValueError, "anchor pixels"):
            create_candidate(self.image, self.depth, roi=(5, 5, 95, 75),
                anchor_pixels=(0, 0, 200, 400), anchor_m=0.5, anchor_description="test",
                anchor_independence="same_sensor", thickness_m=0.1, project_id="x", operator="analyst", intrinsics=(525,525,319.5,239.5))

    def test_unknown_thickness_is_preserved_but_not_exported_as_solid(self):
        from products.worldstate_bim.assisted import write_model
        from products.worldstate_bim.parametric_ir import parameter, validate_ir
        model = self.candidate(0.5)
        model["elements"][0]["parameters"]["thickness"] = parameter(None, "unknown", ["depth-1"], note="not observed")
        validate_ir(model)
        with self.assertRaisesRegex(ValueError, "unknown or conflicting"):
            write_model(model, self.root, self.root / "unknown")
