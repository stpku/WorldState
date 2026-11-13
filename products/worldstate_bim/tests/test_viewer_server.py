"""Local browser API must edit a real IFC only with a same-origin session token."""
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


@unittest.skipUnless(all(importlib.util.find_spec(x) for x in ("numpy", "cv2", "ifcopenshell")),
                     "assisted BIM dependencies are optional")
class ViewerServerTests(unittest.TestCase):
    def test_local_revision_and_cross_origin_rejection(self):
        import cv2
        import numpy as np
        from products.worldstate_bim.assisted import create_candidate, write_model
        from products.worldstate_bim.viewer_server import ViewerServer

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            image, depth = root / "photo.png", root / "depth.png"
            cv2.imwrite(str(image), np.full((80, 100, 3), 127, dtype=np.uint8))
            cv2.imwrite(str(depth), np.full((80, 100), 10000, dtype=np.uint16))
            model, _ = create_candidate(image, depth, roi=(5, 5, 95, 75),
                anchor_pixels=(20, 40, 80, 40), anchor_m=0.5,
                anchor_description="synthetic test", anchor_independence="same_sensor",
                thickness_m=.12, project_id="server-test", operator="analyst",
                intrinsics=(525, 525, 319.5, 239.5))
            write_model(model, root, root / "v1")
            server = ViewerServer(0, root / "v1", root, root / "revisions")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                payload = json.dumps({"wall_id": "wall-patch-1", "length_m": 0.75, "reason": "test"}).encode()
                request = urllib.request.Request(base + "/api/revise", data=payload, method="POST")
                with self.assertRaises(urllib.error.HTTPError) as failed:
                    urllib.request.urlopen(request)
                self.assertEqual(failed.exception.code, 403)
                request = urllib.request.Request(base + "/api/revise", data=payload, method="POST", headers={
                    "Origin": base, "X-WorldState-Token": server.token, "Content-Type": "application/json"})
                with urllib.request.urlopen(request) as response:
                    result = json.load(response)
                self.assertEqual(result["model"]["revision"], 2)
                self.assertEqual(result["model"]["elements"][0]["parameters"]["length"]["value"], .75)
                self.assertTrue((root / "revisions" / "revision-002" / "model.ifc").is_file())
                with urllib.request.urlopen(base + "/api/model.ifc") as response:
                    self.assertIn(b"IFC4", response.read())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
