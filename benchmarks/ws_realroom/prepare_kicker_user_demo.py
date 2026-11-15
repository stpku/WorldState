"""Create a new local-only ETH3D kicker trial workspace from existing caches.

The input data and trained model are not downloaded or redistributed. ETH3D is
CC BY-NC-SA 4.0; this demo is for non-commercial research. A pre-existing
partial IFC uses unverified automated observations and assumed dimensions.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from products.worldstate_bim.general_modeler import _point, build_room_ir, camera_digest, solve_modeler
from products.worldstate_bim.room_cli import save_version
from products.worldstate_bim.studio_modeler import _data


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def prepare(template: Path, manifest_path: Path, photos: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError('Output exists; use a new workspace and preserve the prior trial')
    template = template.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 'worldstate-modeler-cameras/0.1' or manifest.get('camera_mode') != 'known-pose':
        raise ValueError('Expected known-pose camera manifest')
    cameras = manifest['cameras']
    if len(cameras) < 2 or len({c['image_id'] for c in cameras}) != len(cameras):
        raise ValueError('Expected distinct registered cameras')
    project = json.loads((template / 'photo-project.json').read_text())
    old = project['general_modeler']
    if old['source_reconstruction'] != manifest['source_reconstruction']:
        raise ValueError('Camera reconstruction changed; do not rebind old observations')
    indexed = {c['image_id']: c for c in cameras}
    for observation in old['observations']:
        camera = indexed.get(observation['image_id'])
        if not camera or camera_digest(camera) != observation['camera_sha256'] or camera['sha256'] != observation['photo_sha256']:
            raise ValueError('Old observations do not bind to these camera and image versions')
    # Validate every source before creating/copying the new workspace.
    for camera in cameras:
        source = photos / camera['photo']
        if Path(camera['photo']).name != camera['photo'] or source.is_symlink() or sha(source) != camera['sha256']:
            raise ValueError(f"Image missing or hash mismatch: {camera['photo']}")
    shutil.copytree(template, output, symlinks=False)
    evidence = json.loads((output / 'evidence-index.json').read_text())
    existing = {item['sha256'] for item in evidence['uploads']}
    now = datetime.now(timezone.utc).isoformat()
    for camera in cameras:
        digest = camera['sha256']
        destination = output / 'evidence' / (digest + '.jpg')
        if digest in existing:
            if sha(destination) != digest:
                raise ValueError('Existing evidence hash mismatch')
            continue
        shutil.copyfile(photos / camera['photo'], destination)
        if sha(destination) != digest:
            raise ValueError('Copied evidence hash mismatch')
        evidence['uploads'].append({'id': 'upload-' + digest[:16], 'sha256': digest,
            'extension': '.jpg', 'mime': 'image/jpeg', 'width': camera['width_px'],
            'height': camera['height_px'], 'captured_at': 'UNKNOWN', 'added_at': now,
            'status': 'unassociated', 'original_filename': camera['photo'],
            'quality': {'warnings': [], 'note': 'quality not assessed on preload; registration unverified'}})
    tracks, duplicates = [], 0
    for track in manifest['tracks']:
        seen, points = set(), []
        for obs in track['observations']:
            cam = indexed.get(obs['image_id'])
            if cam is None:
                continue
            if cam['image_id'] in seen:
                duplicates += 1
                break
            seen.add(cam['image_id'])
            points.append({'image_id': cam['image_id'], 'pixel_xy': _point(obs, cam).tolist()})
        else:
            if len(points) >= 2:
                tracks.append({'id': track['id'], 'observations': points})
    track_path = output / 'modeler-tracks.json'
    write(track_path, {'tracks': tracks})
    old.update(cameras=copy.deepcopy(cameras), track_sha256=sha(track_path), track_count=len(tracks),
               duplicate_view_tracks_excluded=duplicates, suggestions=[])
    data = _data(old)
    solution = solve_modeler(data)
    previous = json.loads((output / f"revision-{project['current_revision']:03}" / 'model.json').read_text())
    model = build_room_ir(data, solution, project_id=project['id'],
        scale={'basis': 'assumed', 'metres_per_source_unit': 1.0}, thickness_m=0.1,
        up_source=[0, 0, 1], allow_rectangular_approximation=True)
    model['revision'] = previous['revision'] + 1
    event = {'revision': model['revision'], 'action': 'demo_camera_preload_resolve',
        'operator': 'automation', 'input_sha256': solution['input_sha256'],
        'warning': 'Existing automated observations and assumed scale remain unverified.'}
    model['history'] = copy.deepcopy(previous.get('history', [])) + [event]
    save_version(model, output / f"revision-{model['revision']:03}", diff=event)
    old.update(solution=solution, model_dirty=False, revision=old['revision'] + 1)
    project.update(name='ETH3D kicker · 非商业研究演示', current_revision=model['revision'], operator_kind='user')
    project['events'].append({'action': 'demo_preloaded', 'at': now, 'operator': 'automation',
        'registered': len(cameras), 'tracks': len(tracks), 'prior_observations': 'automation_unverified',
        'warning': 'No real person confirmed previous observations. Scale, up and wall thickness are assumed.'})
    write(output / 'evidence-index.json', evidence)
    write(output / 'photo-project.json', project)
    return {'workspace': str(output), 'photos': len(cameras), 'registered': len(cameras),
        'tracks': len(tracks), 'duplicate_view_tracks_excluded': duplicates, 'revision': model['revision'],
        'existing_objects': len(model['elements']), 'status': 'PARTIAL_UNVERIFIED_NONCOMMERCIAL_DEMO'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--photos', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.template, args.manifest, args.photos, args.output), indent=2))
