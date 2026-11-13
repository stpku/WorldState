"""CPU COLMAP reconstruction adapter for the BIM product, not Core."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import pycolmap


def reconstruct_images(image_dir: Path, names: list[str], output_dir: Path) -> dict[str, Any]:
    """Run calibrated COLMAP SfM and return an arbitrary-scale geometry candidate.

    This benchmark adapter uses the TUM/ROS default pinhole intrinsics. It does
    not apply ground-truth scale or claim that sparse points are BIM objects.
    Output directory must not contain an existing database or sparse model.
    """
    if len(names) < 4 or len(set(names)) != len(names):
        raise ValueError("at least four distinct photos are required")
    if any(Path(name).name != name or not (image_dir / name).is_file() for name in names):
        raise ValueError("all images must be direct files in the evidence directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    database = output_dir / "database.db"
    sparse = output_dir / "sparse"
    if database.exists() or sparse.exists():
        raise FileExistsError("COLMAP output already exists; choose a new directory")
    sparse.mkdir()
    reader = pycolmap.ImageReaderOptions(camera_model="PINHOLE", camera_params="525,525,319.5,239.5")
    extract = pycolmap.FeatureExtractionOptions(num_threads=4, use_gpu=False, max_image_size=640)
    extract.sift.max_num_features = 4096
    extract.sift.first_octave = 0
    matching = pycolmap.FeatureMatchingOptions(num_threads=4, use_gpu=False)
    mapper = pycolmap.IncrementalPipelineOptions(num_threads=4, random_seed=0, multiple_models=False,
                                                 min_model_size=3, ba_refine_focal_length=False,
                                                 ba_refine_principal_point=False, ba_refine_extra_params=False)
    mapper.mapper.init_min_tri_angle = 3.0
    mapper.mapper.init_min_num_inliers = 50
    started = time.perf_counter()
    pycolmap.extract_features(database, image_dir, image_names=names, camera_mode=pycolmap.CameraMode.SINGLE,
                              reader_options=reader, extraction_options=extract, device=pycolmap.Device.cpu)
    after_features = time.perf_counter()
    pycolmap.match_exhaustive(database, matching_options=matching, device=pycolmap.Device.cpu)
    after_matching = time.perf_counter()
    models = pycolmap.incremental_mapping(database, image_dir, sparse, options=mapper)
    finished = time.perf_counter()
    image_hashes = []
    for name in names:
        with (image_dir / name).open("rb") as stream:
            image_hashes.append({"file": name, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()})
    result: dict[str, Any] = {
        "schema": "worldstate-bim-geometry-candidate/0.1", "provider": "COLMAP/pycolmap",
        "provider_version": pycolmap.__version__, "status": "UNVERIFIED_RESEARCH_CANDIDATE",
        "input_images": image_hashes, "coordinate_frame": "COLMAP reconstruction frame",
        "scale": {"status": "unknown", "unit": "arbitrary"},
        "uncertainty": {"status": "not_quantified", "reason": "no per-point covariance estimated"},
        "camera_calibration": {"model": "PINHOLE", "parameters": [525, 525, 319.5, 239.5],
                               "provenance": "TUM recommended ROS default, not per-frame calibration"},
        "timing_seconds": {"feature_extraction": after_features-started,
                           "matching": after_matching-after_features, "mapping": finished-after_matching,
                           "total": finished-started},
        "registered_cameras": [], "sparse_points": 0,
        "limitations": ["CPU sparse SfM only", "scale unknown without independent anchor", "not a building model"],
    }
    if not models:
        result["status"] = "RECONSTRUCTION_FAILED"
        return result
    model = max(models.values(), key=lambda m: m.num_reg_images())
    cloud = output_dir / "points.ply"
    model.export_PLY(cloud)
    result["point_cloud_file"] = cloud.name
    result["sparse_points"] = model.num_points3D()
    result["mean_reprojection_error_px"] = model.compute_mean_reprojection_error()
    for image_id in model.reg_image_ids():
        image = model.image(image_id)
        transform = image.cam_from_world()
        result["registered_cameras"].append({"name": image.name, "center": image.projection_center().tolist(),
                                              "rotation_camera_from_world": transform.rotation.matrix().tolist()})
    result["registered_cameras"].sort(key=lambda x: x["name"])
    return result
