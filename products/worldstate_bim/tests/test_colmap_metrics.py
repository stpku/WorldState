"""Pose alignment must not mistake arbitrary reconstruction scale for metres."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(all(importlib.util.find_spec(x) for x in ("numpy", "scipy", "pycolmap")),
                     "COLMAP benchmark dependencies are optional")
class ColmapMetricsTests(unittest.TestCase):
    def test_anchor_alignment_uses_scale_and_leaves_two_held_out_poses(self):
        from benchmarks.ws_geometry.run_colmap import evaluate
        names = [f"{n}.png" for n in range(4)]
        candidate = {"registered_cameras": [{"name": name, "center": [float(i), 0., 0.],
                     "rotation_camera_from_world": [[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]}
                     for i, name in enumerate(names)]}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"gt.txt"
            path.write_text("\n".join(f"{i} {i*2} 0 0 0 0 0 1" for i in range(4)))
            result = evaluate(candidate, path, names)
        self.assertAlmostEqual(result["oracle_scale_m_per_unit"], 2.0)
        self.assertEqual(result["heldout_pose_count"], 2)
        self.assertAlmostEqual(result["position_median_error_m"], 0.0)
        self.assertAlmostEqual(result["rotation_median_error_deg"], 0.0)
