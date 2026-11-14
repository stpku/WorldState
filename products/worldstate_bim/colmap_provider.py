"""CPU COLMAP reconstruction adapter for the BIM product, not Core."""
from __future__ import annotations

import hashlib
import math
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


def reconstruct_uncalibrated_images(image_dir: Path, names: list[str], output_dir: Path, *, threads: int = 4, calibration: dict | None = None, max_image_size: int = 1200) -> dict[str, Any]:
    """Run CPU SfM on 4–32 images declared to share one undistorted camera.

    Focal length and poses are estimates unless an explicitly sourced, fixed
    camera calibration is supplied; the output coordinate frame has no physical scale. The caller must verify that the images are from the same
    camera and raster dimensions, and must not treat reprojection error as
    reconstruction accuracy. The optional SIFT maximum image dimension is a
    resource/quality tradeoff; higher resolutions do not guarantee registration.
    """
    if not 4 <= len(names) <= 32 or len(set(names)) != len(names):
        raise ValueError("多视图求解需要 4 至 32 张不同照片")
    if any(Path(name).name != name or not (image_dir / name).is_file() or (image_dir / name).is_symlink() for name in names):
        raise ValueError("照片必须是证据目录中的普通文件")
    if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 16:
        raise ValueError("线程数无效")
    if isinstance(max_image_size, bool) or not isinstance(max_image_size, int) or not 640 <= max_image_size <= 4096:
        raise ValueError("特征提取图像尺寸须为 640 至 4096 像素")
    from PIL import Image
    dimensions=set()
    for name in names:
        with Image.open(image_dir/name) as image:
            if image.format not in {"JPEG","PNG"} or image.width*image.height>30_000_000 or image.getexif().get(274,1)!=1:
                raise ValueError("照片格式、尺寸或旋转方向不受支持")
            dimensions.add(image.size)
    if len(dimensions)!=1:raise ValueError("同一相机的照片需要相同像素尺寸")
    output_dir.mkdir(parents=True,exist_ok=True)
    database=output_dir/'database.db';sparse=output_dir/'sparse'
    if database.exists() or sparse.exists():raise FileExistsError('COLMAP 输出目录必须为空')
    sparse.mkdir()
    if calibration is None:
        reader=pycolmap.ImageReaderOptions(camera_model='SIMPLE_PINHOLE')
    else:
        if calibration.get('confirmed') is not True or not isinstance(calibration.get('source'),str) or not calibration['source'].strip():
            raise ValueError('请确认相机标定对应当前照片并记录来源')
        values=[calibration.get(k) for k in ('fx','fy','cx','cy')]
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):raise ValueError('相机标定参数无效')
        fx,fy,cx,cy=values;width,height=next(iter(dimensions))
        if not (.05*max(width,height)<=fx<=10*max(width,height) and .05*max(width,height)<=fy<=10*max(width,height) and 0<=cx<width and 0<=cy<height):
            raise ValueError('相机标定参数超出图像有效范围')
        sha=calibration.get('source_sha256')
        if sha is not None and (not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha)):
            raise ValueError('相机标定来源哈希无效')
        reader=pycolmap.ImageReaderOptions(camera_model='PINHOLE',camera_params=','.join(str(v) for v in values))
    extraction=pycolmap.FeatureExtractionOptions(num_threads=threads,use_gpu=False,max_image_size=max_image_size)
    extraction.sift.first_octave=0
    matching=pycolmap.FeatureMatchingOptions(num_threads=threads,use_gpu=False)
    mapper=pycolmap.IncrementalPipelineOptions(num_threads=threads,random_seed=0,multiple_models=False,min_model_size=3)
    mapper.mapper.init_min_tri_angle=3.0;mapper.mapper.init_min_num_inliers=50
    if calibration is not None:
        mapper.ba_refine_focal_length=False;mapper.ba_refine_principal_point=False;mapper.ba_refine_extra_params=False
        mapper.mapper.abs_pose_refine_focal_length=False;mapper.mapper.abs_pose_refine_extra_params=False
    started=time.perf_counter()
    pycolmap.extract_features(database,image_dir,image_names=names,camera_mode=pycolmap.CameraMode.SINGLE,
                              reader_options=reader,extraction_options=extraction,device=pycolmap.Device.cpu)
    after_features=time.perf_counter()
    pycolmap.match_exhaustive(database,matching_options=matching,device=pycolmap.Device.cpu)
    after_matching=time.perf_counter()
    models=pycolmap.incremental_mapping(database,image_dir,sparse,options=mapper)
    finished=time.perf_counter()
    hashes=[]
    for name in names:
        with (image_dir/name).open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        hashes.append({'file':name,'sha256':sha})
    result={'schema':'worldstate-bim-geometry-candidate/0.1','provider':'COLMAP/pycolmap',
        'provider_version':pycolmap.__version__,'status':'RECONSTRUCTION_FAILED','inputs':hashes,
        'input_camera_assumption':'all images from one camera; '+('focal length self-calibrated' if calibration is None else 'user-declared fixed calibration'),
        'feature_extraction_max_image_size_px':max_image_size,
        'supplied_calibration':calibration,
        'coordinate_frame':'COLMAP arbitrary reconstruction frame','scale':{'status':'unknown','unit':'arbitrary'},
        'timing_seconds':{'feature_extraction':after_features-started,'matching':after_matching-after_features,
                          'mapping':finished-after_matching,'total':finished-started},
        'registered_cameras':[],'sparse_points':0,
        'limitations':['no independent metric scale or ground truth','self-calibration and sparse geometry unverified',
                       'not a BIM or wall-instance reconstruction',
                       'registration below 3 images or 50% is marked insufficient; this is not a release criterion']}
    if models:
        model=max(models.values(),key=lambda m:m.num_reg_images())
        model.export_PLY(output_dir/'points.ply')
        error=model.compute_mean_reprojection_error() if model.num_points3D() else None
        if error is not None and not math.isfinite(error):error=None
        result.update(status='UNVERIFIED_RESEARCH_CANDIDATE' if model.num_reg_images()>=3 and model.num_reg_images()/len(names)>=.5 else 'INSUFFICIENT_REGISTRATION',
                      sparse_points=model.num_points3D(),mean_reprojection_error_px=error,
                      point_cloud_file='points.ply')
        for image_id in model.reg_image_ids():
            image=model.image(image_id)
            result['registered_cameras'].append({'name':image.name,'center':image.projection_center().tolist(),
                'rotation_camera_from_world':image.cam_from_world().rotation.matrix().tolist()})
        result['registered_cameras'].sort(key=lambda x:x['name'])
        result['camera_parameters']=[{'model':str(cam.model),'width':cam.width,'height':cam.height,'params':cam.params.tolist()}
                                     for cam in model.cameras.values()]
        for cam in model.cameras.values():
            focal=float(cam.params[0]);extent=max(cam.width,cam.height)
            if not math.isfinite(focal) or not .05*extent<=focal<=10*extent:
                result['status']='DEGENERATE_CALIBRATION'
                result['limitations'].append('estimated focal length is implausible for the image dimensions')
    return result
