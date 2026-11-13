"""Geometry checks use synthetic data and are not real-scene acceptance."""

import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec("cv2") and importlib.util.find_spec("numpy"),
                     "two-view research dependencies are optional")
class TwoViewTests(unittest.TestCase):
    def test_featureless_photos_fail_closed(self):
        import numpy as np
        from products.worldstate_bim.two_view import reconstruct

        image = np.zeros((240, 320, 3), dtype=np.uint8)
        camera = np.array([[250, 0, 160], [0, 250, 120], [0, 0, 1]], dtype=float)
        with self.assertRaisesRegex(ValueError, "features"):
            reconstruct(image, image, camera)

    def test_synthetic_perspective_recovers_motion_direction(self):
        import cv2
        import numpy as np
        from products.worldstate_bim.two_view import reconstruct

        rng = np.random.default_rng(7)
        camera = np.array([[500, 0, 320], [0, 500, 240], [0, 0, 1]], dtype=float)
        first = np.zeros((480, 640), dtype=np.uint8)
        second = np.zeros_like(first)
        # Unique image patches are projected from different depths so the two
        # images have actual parallax rather than a single planar homography.
        for _ in range(300):
            point = np.array([rng.uniform(-2, 2), rng.uniform(-1.4, 1.4), rng.uniform(3, 8)])
            other = point + np.array([-0.45, 0.0, 0.0])
            p = np.rint((camera @ point)[:2] / point[2]).astype(int)
            q = np.rint((camera @ other)[:2] / other[2]).astype(int)
            if not (7 <= p[0] < 633 and 7 <= p[1] < 473 and 7 <= q[0] < 633 and 7 <= q[1] < 473):
                continue
            patch = rng.integers(0, 256, (11, 11), dtype=np.uint8)
            first[p[1]-5:p[1]+6, p[0]-5:p[0]+6] = patch
            second[q[1]-5:q[1]+6, q[0]-5:q[0]+6] = patch
        first = cv2.GaussianBlur(first, (3, 3), 0.5)
        second = cv2.GaussianBlur(second, (3, 3), 0.5)
        result = reconstruct(first, second, camera)
        self.assertGreater(result.inliers, 20)
        self.assertLess(result.median_reprojection_px, 1.5)
        self.assertGreater(float(np.dot(result.translation, [-1, 0, 0])), 0.8)
        self.assertTrue((result.points[:, 2] > 0).all())
        replay = reconstruct(first, second, camera)
        np.testing.assert_allclose(result.points, replay.points, rtol=0, atol=1e-10)


if __name__ == "__main__":
    unittest.main()
