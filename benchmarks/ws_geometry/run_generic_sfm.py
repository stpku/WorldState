"""CPU COLMAP experiment for a set of photos from a single camera.

No ground-truth poses or evaluation dimensions are read. Results have unknown
scale; this is not a room model. Run in a new empty output directory.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path
import pycolmap


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--images',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--threads',type=int,default=4)
    args=p.parse_args()
    names=sorted(x.name for x in args.images.iterdir() if x.suffix.lower() in {'.jpg','.jpeg','.png'})
    if len(names)<4: raise ValueError('at least four images required')
    args.output.mkdir(parents=True,exist_ok=True)
    database=args.output/'database.db'; sparse=args.output/'sparse'
    if database.exists() or sparse.exists(): raise FileExistsError('output already exists')
    sparse.mkdir()
    reader=pycolmap.ImageReaderOptions(camera_model='SIMPLE_PINHOLE')
    extract=pycolmap.FeatureExtractionOptions(num_threads=args.threads,use_gpu=False,max_image_size=1200)
    extract.sift.first_octave=0
    match=pycolmap.FeatureMatchingOptions(num_threads=args.threads,use_gpu=False)
    mapper=pycolmap.IncrementalPipelineOptions(num_threads=args.threads,random_seed=0,multiple_models=False,min_model_size=3)
    mapper.mapper.init_min_tri_angle=3.0
    mapper.mapper.init_min_num_inliers=50
    start=time.perf_counter()
    pycolmap.extract_features(database,args.images,image_names=names,camera_mode=pycolmap.CameraMode.SINGLE,
                              reader_options=reader,extraction_options=extract,device=pycolmap.Device.cpu)
    features=time.perf_counter()
    pycolmap.match_exhaustive(database,matching_options=match,device=pycolmap.Device.cpu)
    matching=time.perf_counter()
    models=pycolmap.incremental_mapping(database,args.images,sparse,options=mapper)
    end=time.perf_counter()
    hashes=[]
    for name in names:
        with (args.images/name).open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
        hashes.append({'file':name,'sha256':digest})
    result={'schema':'worldstate-bim-geometry-candidate/0.1','provider':'COLMAP/pycolmap',
      'provider_version':pycolmap.__version__,'status':'RECONSTRUCTION_FAILED','inputs':hashes,
      'input_camera_assumption':'all images from one camera; focal length self-calibrated',
      'coordinate_frame':'COLMAP arbitrary reconstruction frame', 'scale':{'status':'unknown','unit':'arbitrary'},
      'timing_seconds':{'feature_extraction':features-start,'matching':matching-features,'mapping':end-matching,'total':end-start},
      'registered_cameras':[],'sparse_points':0,'limitations':['no independent metric scale or ground truth',
      'self-calibration and sparse geometry unverified','not a BIM or wall-instance reconstruction']}
    if models:
        m=max(models.values(),key=lambda x:x.num_reg_images())
        m.export_PLY(args.output/'points.ply')
        result.update(status='UNVERIFIED_RESEARCH_CANDIDATE',sparse_points=m.num_points3D(),
                      mean_reprojection_error_px=m.compute_mean_reprojection_error(),point_cloud_file='points.ply')
        for i in m.reg_image_ids():
            image=m.image(i)
            result['registered_cameras'].append({'name':image.name,'center':image.projection_center().tolist(),
                'rotation_camera_from_world':image.cam_from_world().rotation.matrix().tolist()})
        result['registered_cameras'].sort(key=lambda x:x['name'])
        result['camera_parameters']=[{'model':str(cam.model),'width':cam.width,'height':cam.height,'params':cam.params.tolist()}
                                     for cam in m.cameras.values()]
    (args.output/'geometry-candidate.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':result['status'],'registered':len(result['registered_cameras']),
                      'points':result['sparse_points'],'reprojection_px':result.get('mean_reprojection_error_px'),
                      'timing':result['timing_seconds']}),flush=True)

if __name__=='__main__':main()
