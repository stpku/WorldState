"""Optional real IFC test; skips when IfcOpenShell is not available."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from products.worldstate_bim.contract import load_proposal
from products.worldstate_bim.ifc_export import export_ifc
from products.worldstate_bim.tests.test_contract import fixture


class IfcExporterTests(unittest.TestCase):
    def test_ifc_wall_is_semantic_editable_object_if_dependency_present(self):
        try:
            import ifcopenshell
            import ifcopenshell.geom
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
            geom = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), walls[0])
            self.assertGreater(len(geom.geometry.verts), 0)
            second = Path(td) / "draft-revision.ifc"
            export_ifc(proposal, second, allow_approximate=True)
            replay = ifcopenshell.open(str(second))
            self.assertEqual(walls[0].GlobalId, replay.by_type("IfcWall")[0].GlobalId)
            self.assertEqual(
                model.by_type("IfcBuilding")[0].GlobalId,
                replay.by_type("IfcBuilding")[0].GlobalId,
            )

    def test_parameter_revision_changes_geometry_and_keeps_wall_identity(self):
        """Synthetic proposal revision: not an independent authoring-tool test."""
        try:
            import ifcopenshell
            import ifcopenshell.geom
        except ImportError:
            self.skipTest("ifcopenshell is not installed in this environment")
        proposal = load_proposal(fixture())
        changed_wall = replace(proposal.walls[0], end_m=(5.0, 0.0, 0.0), height_m=3.5)
        revised = replace(proposal, walls=(changed_wall,))
        with tempfile.TemporaryDirectory() as td:
            first_path = export_ifc(proposal, Path(td) / "first.ifc", allow_approximate=True)
            second_path = export_ifc(revised, Path(td) / "second.ifc", allow_approximate=True)
            first = ifcopenshell.open(str(first_path)).by_type("IfcWall")[0]
            second = ifcopenshell.open(str(second_path)).by_type("IfcWall")[0]
            self.assertEqual(first.GlobalId, second.GlobalId)
            def extent(wall):
                geometry = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), wall).geometry
                z = geometry.verts[2::3]
                return max(z) - min(z)
            self.assertAlmostEqual(extent(first), 3.0, places=6)
            self.assertAlmostEqual(extent(second), 3.5, places=6)


if __name__ == "__main__":
    unittest.main()
