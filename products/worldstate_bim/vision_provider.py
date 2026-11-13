"""Optional local Depth Anything V2 ONNX provider for assisted selection."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from .parametric_ir import digest


def infer_relative_depth(image_path: Path, model_path: Path) -> tuple[np.ndarray, dict]:
    """Infer relative inverse depth locally; neither metres nor semantics are output."""
    import onnxruntime as ort
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("cannot read photo for local vision inference")
    h, w = image.shape[:2]
    factor = 518 / min(h, w)
    width = max(14, round(w*factor/14)*14)
    height = max(14, round(h*factor/14)*14)
    rgb = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), (width, height), interpolation=cv2.INTER_CUBIC).astype(np.float32)/255
    rgb = (rgb-np.array([0.485, 0.456, 0.406], np.float32))/np.array([0.229, 0.224, 0.225], np.float32)
    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(model_path), sess_options=session_options, providers=["CPUExecutionProvider"])
    start = time.perf_counter()
    prediction = session.run(None, {session.get_inputs()[0].name: np.transpose(rgb, (2, 0, 1))[None]})[0][0]
    elapsed = time.perf_counter()-start
    result = cv2.resize(prediction, (w, h), interpolation=cv2.INTER_CUBIC)
    if not np.isfinite(result).all():
        raise ValueError("local vision model returned non-finite depth")
    return result, {"id": "vision-1", "kind": "local_vision_model",
                    "model": "Depth Anything V2 Small ONNX", "sha256": digest(model_path),
                    "provider": "onnxruntime CPU", "runtime_version": ort.__version__,
                    "inference_seconds": elapsed, "output": "relative inverse depth; not metric or semantic"}
