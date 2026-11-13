"""Synthetic unit tests do not count as wall reconstruction acceptance."""

import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("numpy"), "numpy is optional for BIM product")
class VisibleSurfaceTests(unittest.TestCase):
    def test_planar_depth_is_fitted_in_metric_camera_frame(self):
        import numpy as np
        from products.worldstate_bim.visible_surface import fit_visible_surface

        depth = np.full((80, 100), 10000, dtype=np.uint16)
        mask = np.ones_like(depth, dtype=bool)
        k = np.array([[100, 0, 50], [0, 100, 40], [0, 0, 1]], dtype=float)
        result = fit_visible_surface(depth, mask, k, iterations=30)
        self.assertGreater(result.inlier_samples, 100)
        np.testing.assert_allclose(result.normal_camera, [0, 0, -1], atol=1e-8)
        self.assertAlmostEqual(result.offset_m, 2.0)
        self.assertLess(result.median_residual_m, 1e-8)

    def test_missing_depth_refuses_to_guess(self):
        import numpy as np
        from products.worldstate_bim.visible_surface import fit_visible_surface

        depth = np.zeros((30, 30), dtype=np.uint16)
        with self.assertRaisesRegex(ValueError, "valid depth"):
            fit_visible_surface(depth, np.ones_like(depth), np.eye(3))
