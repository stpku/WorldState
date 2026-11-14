"""Replaceable, offline semantic-image provider for assisted BIM.

The provider makes image-space proposals only. It does not estimate wall
instances, camera pose, physical dimensions or unobserved geometry.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Protocol


class VisionProvider(Protocol):
    """A provider returns inspectable image-coordinate proposals and an overlay."""

    def analyze(self, image: Path) -> tuple[dict, bytes]: ...


class UperNetOnnxProvider:
    """UperNet/ConvNeXt ADE20K semantic segmentation using CPU ONNX Runtime."""

    MODEL_SHA256 = "fea729ab6c5d338bc79ad3d986b073e6faa12c97255eafd78a1f7145326e534e"
    MODEL_REVISION = "a8e2807c3479bc617b37d8ed53e68660b3fa1ebb"
    CLASSES = {0: "wall", 3: "floor", 5: "ceiling", 8: "window", 14: "door"}
    COLORS = {0: (60, 185, 255), 3: (90, 210, 100), 5: (245, 155, 70),
              8: (225, 100, 205), 14: (70, 85, 240)}  # BGR

    def __init__(self, model_path: Path, threads: int = 4):
        import onnxruntime as ort

        self.model_path = Path(model_path).resolve(strict=True)
        h = hashlib.sha256()
        with self.model_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != self.MODEL_SHA256:
            raise ValueError("视觉模型 SHA-256 与受支持的 UperNet ONNX 权重不匹配")
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(int(threads), 16))
        self.session = ort.InferenceSession(str(self.model_path), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        if self.session.get_inputs()[0].name != "pixel_values":
            raise ValueError("视觉模型输入格式不受支持")

    def analyze(self, image: Path) -> tuple[dict, bytes]:
        """Segment one real image; coordinates refer to the original raster."""
        import cv2
        import numpy as np

        started = time.monotonic()
        data = Path(image).read_bytes()
        image_sha = hashlib.sha256(data).hexdigest()
        pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            raise ValueError("无法读取照片")
        height, width = pixels.shape[:2]
        if width < 32 or height < 32 or width * height > 40_000_000:
            raise ValueError("照片尺寸超出视觉模型支持范围")
        rgb = cv2.cvtColor(cv2.resize(pixels, (512, 512)), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        mean = np.array([.485, .456, .406], dtype=np.float32)
        std = np.array([.229, .224, .225], dtype=np.float32)
        input_tensor = ((rgb - mean) / std).transpose(2, 0, 1)[None]
        logits = self.session.run(None, {"pixel_values": input_tensor})[0][0]
        if logits.shape != (150, 128, 128) or not np.isfinite(logits).all():
            raise ValueError("视觉模型输出格式无效")
        classes = np.argmax(logits, axis=0).astype(np.uint8)
        # Model scores are not calibrated probabilities or verified accuracy.
        exps = np.exp(logits - np.max(logits, axis=0, keepdims=True))
        scores = np.max(exps, axis=0) / np.sum(exps, axis=0)
        labels = cv2.resize(classes, (width, height), interpolation=cv2.INTER_NEAREST)
        overlay = pixels.copy()
        candidates: list[dict] = []
        for class_id, name in self.CLASSES.items():
            mask = (labels == class_id).astype(np.uint8)
            if not mask.any():
                continue
            color = np.array(self.COLORS[class_id], dtype=np.float32)
            overlay[mask > 0] = (pixels[mask > 0].astype(np.float32) * .58 + color * .42).astype(np.uint8)
            count, components, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            for i in range(1, count):
                x, y, w, h, area = (int(v) for v in stats[i])
                if area < max(60, width * height * .002):
                    continue
                region = (components == i).astype(np.uint8)
                contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                contour = max(contours, key=cv2.contourArea)
                polygon = cv2.approxPolyDP(contour, .005 * cv2.arcLength(contour, True), True).reshape(-1, 2).tolist()
                small = cv2.resize(region, (128, 128), interpolation=cv2.INTER_NEAREST).astype(bool)
                confidence = float(np.mean(scores[small])) if small.any() else None
                candidates.append({"id": f"region-{name}-{i}", "kind": f"{name}_region",
                    "bbox_px": [x, y, x + w - 1, y + h - 1], "polygon_px": polygon,
                    "area_px": area, "model_score_mean_uncalibrated": confidence,
                    "status": "proposed", "geometry": "semantic_region_not_instance"})
                cv2.drawContours(overlay, [contour], -1, self.COLORS[class_id], max(1, width // 500))
        # A wall/floor semantic boundary may contain more than one physical wall.
        # Hough segments are geometric suggestions, not wall identities.
        wall = (labels == 0).astype(np.uint8)
        floor = (labels == 3).astype(np.uint8)
        kernel = np.ones((7, 7), np.uint8)
        floor_edge = cv2.Canny(floor * 255, 50, 150)
        boundary = cv2.bitwise_and(floor_edge, cv2.dilate(wall, kernel))
        min_length = max(35, width // 12)
        lines = cv2.HoughLinesP(boundary, 1, np.pi / 180, threshold=max(18, width // 45),
                                minLineLength=min_length, maxLineGap=max(8, width // 50))
        if lines is not None:
            ordered = sorted((line[0].tolist() for line in lines),
                             key=lambda a: -((a[2]-a[0])**2 + (a[3]-a[1])**2))
            for line in ordered[:20]:
                x1, y1, x2, y2 = (int(x) for x in line)
                candidates.append({"id": f"ground-line-{len(candidates)+1}", "kind": "wall_floor_line",
                    "points_px": [[x1, y1], [x2, y2]], "status": "proposed",
                    "method": "hough_on_semantic_boundary", "uncertainty": "heuristic_not_calibrated"})
                cv2.line(overlay, (x1,y1), (x2,y2), (20, 20, 255), max(2,width//300))
                if len(candidates) < 20:
                    for j, point in enumerate(([x1,y1],[x2,y2]), 1):
                        candidates.append({"id":f"line-endpoint-{len(candidates)+1}-{j}",
                            "kind":"line_endpoint", "points_px":[point], "status":"proposed",
                            "method":"hough_segment_endpoint", "uncertainty":"may_be_image_edge_or_occlusion_not_wall_corner"})
        ceiling = (labels == 5).astype(np.uint8)
        ceiling_edge = cv2.Canny(ceiling * 255, 50, 150)
        boundary = cv2.bitwise_and(ceiling_edge, cv2.dilate(wall, kernel))
        ceiling_lines = cv2.HoughLinesP(boundary, 1, np.pi / 180, threshold=max(18,width//45),
                                        minLineLength=min_length, maxLineGap=max(8,width//50))
        if ceiling_lines is not None:
            ordered = sorted((line[0].tolist() for line in ceiling_lines),
                             key=lambda a: -((a[2]-a[0])**2 + (a[3]-a[1])**2))
            for line in ordered[:8]:
                x1,y1,x2,y2=(int(x) for x in line)
                candidates.append({"id":f"ceiling-line-{len(candidates)+1}","kind":"wall_ceiling_line",
                    "points_px":[[x1,y1],[x2,y2]],"status":"proposed",
                    "method":"hough_on_semantic_boundary","uncertainty":"heuristic_not_calibrated"})
                cv2.line(overlay,(x1,y1),(x2,y2),(255,80,30),max(2,width//300))
        ok, encoded = cv2.imencode(".png", overlay)
        if not ok:
            raise ValueError("无法保存识别叠加图")
        return ({"schema": "worldstate-visual-candidates/0.1", "provider": "upernet-convnext-tiny-ade20k-onnx",
                 "model_sha256": self.MODEL_SHA256, "model_revision": self.MODEL_REVISION,
                 "image_sha256": image_sha, "width_px": width, "height_px": height,
                 "runtime_seconds": round(time.monotonic() - started, 3), "device": "CPU",
                 "candidates": candidates, "cross_photo_association": "NOT_IMPLEMENTED",
                 "occlusion_and_unobserved": "UNKNOWN",
                 "limitations": ["semantic regions do not identify individual walls",
                    "door/window not detected does not establish absence", "scores are uncalibrated",
                    "no camera pose, physical dimensions, or geometry inferred by this provider"]}, encoded.tobytes())


def suggest_disconnected_segments(result: dict, *, limit: int = 3) -> list[dict]:
    """Suggest nonduplicate visible floor lines, without asserting wall identity.

    Each segment references the provider's actual proposed line and endpoints.
    Pixel-space suppression is a heuristic; occlusions and separate wall
    instances cannot be verified from it.
    """
    import math

    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=10:
        raise ValueError('invalid proposal limit')
    candidates=result.get('candidates',[]);width=result.get('width_px',0)
    if not isinstance(candidates,list) or not isinstance(width,int) or width<1:
        raise ValueError('invalid visual candidate set')
    lines=[c for c in candidates if c.get('kind')=='wall_floor_line' and c.get('status')=='proposed']
    endpoints=[c for c in candidates if c.get('kind')=='line_endpoint' and c.get('status')=='proposed']
    def length(line):
        a,b=line['points_px'];return math.dist(a,b)
    def duplicate(a,b):
        p,q=a['points_px'];r,s=b['points_px'];ux,uy=q[0]-p[0],q[1]-p[1];vx,vy=s[0]-r[0],s[1]-r[1]
        ul,vl=math.hypot(ux,uy),math.hypot(vx,vy)
        if not ul or not vl or abs(ux*vy-uy*vx)/(ul*vl)>.15:return False
        tolerance=max(4.,width*.022)
        separation=abs((r[0]-p[0])*uy-(r[1]-p[1])*ux)/ul
        t1=((r[0]-p[0])*ux+(r[1]-p[1])*uy)/ul;t2=((s[0]-p[0])*ux+(s[1]-p[1])*uy)/ul
        return separation<tolerance and max(min(t1,t2),0)<=min(max(t1,t2),ul)+tolerance
    selected=[];used=set()
    for line in sorted(lines,key=length,reverse=True):
        if any(duplicate(line,x['line']) for x in selected):continue
        matches=[]
        for point in line['points_px']:
            match=next((x for x in endpoints if x.get('points_px')==[point] and x['id'] not in used and x not in matches),None)
            if match is None:break
            matches.append(match)
        if len(matches)!=2:continue
        used.update(x['id'] for x in matches)
        selected.append({'line':line,'endpoints':matches})
        if len(selected)>=limit:break
    return selected
