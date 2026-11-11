"""Optional real IFC test; skips when IfcOpenShell is not available."""

import tempfile
import unittest
from pathlib import Path

from products.worldstate_bim.contract import load_proposal
from products.worldstate_bim.ifc_export import export_ifc
from products.worldstate_bim.tests.test_contract import fixture


class IfcExporterTests(unittest.TestCase):
    def test_ifc_wall_is_semantic_editable_object_if_dependency_present(self):
        try:
            import ifcopenshell
        except ImportError:
            self.skipTest("ifcopenshell is not installed in this environment")
        proposal = load_proposal(fixture())
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "draft.ifc"
            export_ifc(proposal, out, allow_approximate=True)
            model = ifcopenshell.open(str(out))
            walls = model.by_type("IfcWall")
            self.assertEqual(len(walls), 1)
            self.assertEqual(walls[0].Name, "wall-1")
            self.assertTrue(model.by_type("IfcBuildingStorey"))
            self.assertTrue(model.by_type("IfcRelContainedInSpatialStructure"))
            self.assertTrue(model.by_type("IfcPropertySet"))
            self.assertTrue(walls[0].Representation)


if __name__ == "__main__":
    unittest.main()
