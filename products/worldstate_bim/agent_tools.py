"""Read-only, evidence-bound tools for a single modeling-agent workspace.

AI classifications remain hypotheses. Geometry is solved from registered
COLMAP observations by the existing Modeler; the tools do not establish that a
feature hull is an architectural wall or that source units are metric.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import uuid
from datetime import datetime, timezone

from PIL import Image, ImageDraw

from .general_modeler import SCHEMA_INPUT, build_room_ir, camera_digest, digest, solve_modeler


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError('workspace file unavailable or symlinked')
    return json.loads(path.read_text())


class AgentTools:
    """Restrict operations to an explicitly selected workspace and output directory."""

    def __init__(self, workspace: Path, output: Path, provider: str = 'unspecified',
                 approved_constraints: Path | None = None, allowed_images: set[int] | None = None):
        self.workspace = workspace.resolve(strict=True)
        self.output = output.resolve(strict=True)
        if (self.workspace == self.output or self.workspace in self.output.parents or
            self.output.is_relative_to(Path(__file__).resolve().parents[2])):
            raise ValueError('agent output must be outside the source workspace and repository')
        self.project = read_json(self.workspace / 'photo-project.json')
        self.provider = provider
        self.approved_constraints = read_json(approved_constraints) if approved_constraints else None
        self.state = self.project.get('general_modeler')
        if not isinstance(self.state, dict):
            if not self.project.get('current_revision'):
                raise ValueError('project has neither registered cameras nor a saved model')
            self.state = {'revision': 0, 'camera_mode': None, 'cameras': [], 'objects': []}
        self.cameras = {c['image_id']: c for c in self.state['cameras']}
        self.allowed_images = allowed_images
        if allowed_images is not None and not allowed_images <= self.cameras.keys():
            raise ValueError('allowed photos must belong to the registered project')
        index = read_json(self.workspace / 'evidence-index.json')
        self.uploads = {x['sha256']: x for x in index['uploads']}

    def camera(self, image_id: int) -> dict:
        if (isinstance(image_id, bool) or image_id not in self.cameras or
            (self.allowed_images is not None and image_id not in self.allowed_images)):
            raise ValueError('image is not registered or not authorized for this agent run')
        return self.cameras[image_id]

    def photo(self, camera: dict) -> Path:
        sha = camera['sha256']
        photo = self.uploads.get(sha)
        if not photo or not re.fullmatch(r'[0-9a-f]{64}', sha) or photo.get('extension') not in {'.jpg', '.png'}:
            raise ValueError('registered original photo is unavailable')
        evidence_dir = self.workspace / 'evidence'
        if evidence_dir.is_symlink():raise ValueError('evidence directory is symlinked')
        path = evidence_dir / (sha + photo['extension'])
        if path.is_symlink() or not path.is_file():
            raise ValueError('photo unavailable or symlinked')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != sha:
                raise ValueError('photo hash mismatch')
        return path

    def tracks(self) -> list[dict]:
        path = self.workspace / 'modeler-tracks.json'
        if path.is_symlink() or not path.is_file():
            raise ValueError('registered feature tracks unavailable')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != self.state.get('track_sha256'):
                raise ValueError('feature track hash mismatch')
        return read_json(path)['tracks']

    def inspect_scene(self, _: dict) -> dict:
        model_summary = []
        if self.project.get('current_revision'):
            from .modeling_tools import list_elements
            model_summary = list_elements(self.model())
        return {'project': self.project['name'], 'state_revision': self.state['revision'],
                'model_revision': self.project.get('current_revision'), 'model_elements': model_summary,
                'camera_mode': self.state['camera_mode'],
                'scale_status': 'MODEL_DECLARED_METRIC_NOT_INDEPENDENTLY_VERIFIED' if model_summary else 'UNKNOWN',
                'registration_status': self.state.get('registration_status'),
                'cameras': [{k: c[k] for k in ('image_id', 'photo', 'sha256', 'width_px', 'height_px')}
                            for c in self.cameras.values() if self.allowed_images is None or c['image_id'] in self.allowed_images],
                'existing_objects': [{k:o.get(k) for k in ('id','ifc_type','surface_kind')}
                                     for o in self.state['objects']],
                'warning': 'Camera and object semantics are not independently verified.'}

    def model(self) -> dict:
        revision = self.project.get('current_revision')
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError('no saved IR model')
        model = read_json(self.workspace / f'revision-{revision:03}' / 'model.json')
        if model.get('project_id') != self.project.get('id') or model.get('revision') != revision:
            raise ValueError('saved model identity or revision mismatch')
        return model

    def view_photo(self, args: dict) -> dict:
        camera = self.camera(args.get('image_id'))
        selected = args.get('track_ids', [])
        if not isinstance(selected, list) or len(selected) > 30 or any(isinstance(x, bool) or not isinstance(x, int) for x in selected):
            raise ValueError('track_ids must be at most 30 integer identifiers')
        tracks = {t['id']: t for t in self.tracks()} if selected else {}
        with Image.open(self.photo(camera)) as original:
            if original.size != (camera['width_px'], camera['height_px']):
                raise ValueError('photo dimensions differ from registered camera')
            original.draft('RGB', (1600, 1600))
            original.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            image = original.convert('RGB')
        draw = ImageDraw.Draw(image)
        visible = []
        candidate_id = args.get('candidate_id')
        if candidate_id:
            candidate = self.candidate(candidate_id)
            projections = candidate['solution']['objects'][0]['projections']
            projection = next((p for p in projections if p['image_id'] == camera['image_id'] and
                               p['photo_sha256'] == camera['sha256']), None)
            if projection:
                polygon = [(x*image.width/camera['width_px'], y*image.height/camera['height_px'])
                           for x, y in projection['polygon_px']]
                draw.line(polygon + [polygon[0]], fill='#29ead0', width=3)
        model_projection = None
        if args.get('model_projection') is True:
            projected = self.inspect_model_projection({})
            model_projection = next((v for v in projected['views'] if v['image_id'] == camera['image_id']), None)
            if model_projection:
                polygon = [(x*image.width/camera['width_px'], y*image.height/camera['height_px'])
                           for x,y in model_projection['polygon_px']]
                draw.line(polygon+[polygon[0]],fill='#29ead0',width=3)
                for line in model_projection['ceiling_lines']:
                    points=[(x*image.width/camera['width_px'],y*image.height/camera['height_px']) for x,y in line['points_px']]
                    draw.line(points,fill='#ffdd33',width=3)
        for ident in selected:
            track = tracks.get(ident)
            observation = next((o for o in (track or {}).get('observations', []) if o['image_id'] == camera['image_id']), None)
            if observation is None:
                continue
            x, y = observation['pixel_xy']
            px, py = x * image.width / camera['width_px'], y * image.height / camera['height_px']
            draw.ellipse((px-5, py-5, px+5, py+5), fill='#ffdd33', outline='#1d1d1d', width=2)
            draw.text((px+7, py-5), str(ident), fill='#ffdd33', stroke_width=2, stroke_fill='#111111')
            visible.append({'track_id': ident, 'pixel_xy': [x, y]})
        buffer = io.BytesIO();image.save(buffer, format='JPEG', quality=85)
        return {'image_base64': base64.b64encode(buffer.getvalue()).decode(), 'mime_type': 'image/jpeg',
                'image_id': camera['image_id'], 'photo': camera['photo'], 'photo_sha256': camera['sha256'],
                'camera_sha256': camera_digest(camera), 'original_size': [camera['width_px'], camera['height_px']],
                'preview_size': list(image.size), 'marked_tracks': visible,
                'candidate_id': candidate_id, 'model_projection': model_projection,
                'status': 'UNVERIFIED_IMAGE_EVIDENCE'}

    def inspect_model_projection(self, _: dict) -> dict:
        """Compare a supported IR patch with its own registered image observations."""
        from .model_first import project_local_wall_ir
        model = self.model();projection = project_local_wall_ir(model)
        if not projection:raise ValueError('model has no supported registered photo projection')
        evidence = next((e for e in model['evidence'] if e.get('id') == 'camera'), {})
        source = {c['image_id']:c for c in evidence.get('cameras', [])}
        views=[]
        for v in projection['views']:
            if self.allowed_images is not None and v['image_id'] not in self.allowed_images:continue
            camera = self.camera(v['image_id']);self.photo(camera)
            if v['image_id'] not in source or camera_digest(source[v['image_id']]) != camera_digest(camera):
                raise ValueError('model and authorized photo camera versions differ')
            views.append({**v, 'camera_sha256':camera_digest(camera)})
        if not views:raise ValueError('no registered model photos were authorized')
        return {**projection, 'views':views,
                'warning':'Original model observations are not independent ground truth; occlusion and scale remain unverified.'}

    def preview_projection_repair(self, args: dict) -> dict:
        """Fit a single existing patch height to two authorized observed ceiling lines."""
        import copy
        import numpy as np
        from scipy.optimize import minimize_scalar
        from .model_first import project_local_wall_ir
        if args.get('element_id') != 'wall-above-opening':
            raise ValueError('only the existing supported local patch can be optimized')
        reason=args.get('reason')
        if not isinstance(reason,str) or not reason.strip():raise ValueError('repair reason is required')
        model=self.model();before=self.inspect_model_projection({})
        selected=[v for v in before['views'] if v['ceiling_lines']]
        if len(selected)<2:raise ValueError('at least two authorized observed ceiling lines are required')
        image_ids={v['image_id'] for v in selected};wall=next(e for e in model['elements'] if e['id']=='wall-above-opening')
        height=wall['parameters']['height']['value']
        if not isinstance(height,(int,float)) or not math.isfinite(height) or height<=0:raise ValueError('wall height is unknown')
        def errors(value):
            candidate=copy.deepcopy(model)
            next(e for e in candidate['elements'] if e['id']=='wall-above-opening')['parameters']['height']['value']=float(value)
            views=project_local_wall_ir(candidate)['views']
            return [err for v in views if v['image_id'] in image_ids for line in v['ceiling_lines'] for err in line['endpoint_error_px']]
        initial=errors(height)
        result=minimize_scalar(lambda h:float(np.sum(np.square(errors(h)))),
                               bounds=(max(height*.25,1e-6),height*2.),method='bounded',options={'xatol':1e-10})
        final=errors(result.x) if result.success else []
        if (len(final)!=len(initial) or not final or max(final)>3. or
            np.linalg.norm(final)>=np.linalg.norm(initial)-1e-6):
            raise ValueError('authorized observations do not support a better height within the 3 px gate')
        summary=self.preview_revision({'element_id':args['element_id'],'attribute':'height',
                                       'value':float(result.x),'reason':reason})
        proposal=read_json(self.output/(summary['id']+'.json'))
        proposal['projection_evidence']={'method':'bounded scalar height fit to original ceiling lines',
            'views':[{'image_id':v['image_id'],'photo_sha256':v['photo_sha256'],'camera_sha256':v['camera_sha256']} for v in selected],
            'before_line_rms_px':float(np.sqrt(np.mean(np.square(initial)))),
            'after_line_rms_px':float(np.sqrt(np.mean(np.square(final)))), 'after_max_line_px':float(max(final)),
            'status':'SOURCE_OBSERVATIONS_NOT_INDEPENDENTLY_VERIFIED'}
        (self.output/(proposal['id']+'.json')).write_text(json.dumps(proposal,ensure_ascii=False,indent=2,allow_nan=False))
        return {**summary,'projection_evidence':proposal['projection_evidence']}

    def find_tracks(self, args: dict) -> dict:
        first, second = self.camera(args.get('image_a')), self.camera(args.get('image_b'))
        if first['image_id'] == second['image_id']:
            raise ValueError('two different photos are required')
        region = args.get('region_a', [0, 0, 1, 1])
        if (not isinstance(region, list) or len(region) != 4 or
            any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or x > 1 for x in region) or
            region[0] >= region[2] or region[1] >= region[3]):
            raise ValueError('region_a must be a normalized [left, top, right, bottom] box')
        limit = args.get('limit', 20)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
            raise ValueError('limit must be an integer from 1 to 30')
        matches = []
        for track in self.tracks():
            a = next((o for o in track['observations'] if o['image_id'] == first['image_id']), None)
            b = next((o for o in track['observations'] if o['image_id'] == second['image_id']), None)
            if not a or not b:
                continue
            x, y = a['pixel_xy'];nx, ny = x/first['width_px'], y/first['height_px']
            if region[0] <= nx <= region[2] and region[1] <= ny <= region[3]:
                matches.append({'track_id': track['id'], 'a_pixel_xy': a['pixel_xy'],
                                'b_pixel_xy': b['pixel_xy'], 'total_views': len(track['observations']),
                                'source_line_ids':track.get('source_line_ids')})
        matches.sort(key=lambda x: (-x['total_views'], x['track_id']))
        return {'image_a': first['image_id'], 'image_b': second['image_id'], 'region_a': region,
                'count': len(matches), 'tracks': matches[:limit],
                'track_source':self.state.get('track_source','COLMAP registered feature tracks'),
                'warning': 'Feature correspondences are not verified wall corners or wall instances.'}

    def record_hypothesis(self, args: dict) -> dict:
        label, description, uncertainty = args.get('label'), args.get('description'), args.get('uncertainty')
        views = args.get('views')
        if label not in {'wall', 'floor', 'ceiling', 'door', 'window', 'furniture', 'unknown'}:
            raise ValueError('unsupported semantic label')
        if not all(isinstance(x, str) and 0 < len(x.strip()) <= 1000 for x in (description, uncertainty)):
            raise ValueError('description and uncertainty are required')
        if not isinstance(views, list) or not 1 <= len(views) <= 8:
            raise ValueError('supply 1–8 photo regions')
        if len({v.get('image_id') for v in views if isinstance(v, dict)}) != len(views):
            raise ValueError('each hypothesis view must reference a different photo')
        evidence = []
        for view in views:
            if not isinstance(view, dict):raise ValueError('invalid view')
            camera = self.camera(view.get('image_id'));self.photo(camera)
            box = view.get('bbox_normalized')
            if (not isinstance(box, list) or len(box) != 4 or
                any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or x > 1 for x in box) or
                box[0] >= box[2] or box[1] >= box[3]):
                raise ValueError('each view needs a normalized visible bounding box')
            evidence.append({'image_id': camera['image_id'], 'photo': camera['photo'],
                'photo_sha256': camera['sha256'], 'camera_sha256': camera_digest(camera),
                'bbox_normalized': box, 'bbox_original_px': [box[0]*camera['width_px'], box[1]*camera['height_px'],
                                                             box[2]*camera['width_px'], box[3]*camera['height_px']]})
        ident = 'hypothesis-' + uuid.uuid4().hex
        hypothesis = {'id': ident, 'status': 'AI_SUGGESTED_UNVERIFIED', 'provider': self.provider,
                      'created_at': datetime.now(timezone.utc).isoformat(), 'state_revision': self.state['revision'],
                      'label': label, 'description': description, 'uncertainty': uncertainty, 'views': evidence}
        with (self.output / (ident + '.json')).open('x') as stream:
            json.dump(hypothesis, stream, ensure_ascii=False, indent=2, allow_nan=False)
        return hypothesis

    def hypothesis(self, ident: str) -> dict:
        if not isinstance(ident, str) or not re.fullmatch(r'hypothesis-[0-9a-f]{32}', ident):
            raise ValueError('invalid hypothesis ID')
        result = read_json(self.output / (ident + '.json'))
        if result.get('state_revision') != self.state['revision']:
            raise ValueError('hypothesis belongs to a different modeler revision')
        return result

    def record_image_observation(self, args: dict) -> dict:
        camera = self.camera(args.get('image_id'));self.photo(camera)
        kind, points = args.get('kind'), args.get('points_normalized')
        minimum, maximum = {'point': (1, 1), 'line': (2, 2), 'plane': (3, 128)}.get(kind, (0, 0))
        if (not isinstance(points, list) or not minimum <= len(points) <= maximum or not minimum or
            any(not isinstance(p, list) or len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) or v < 0 or v > 1 for v in p) for p in points)):
            raise ValueError('point, line or plane needs valid normalized image coordinates')
        uncertainty, description = args.get('uncertainty'), args.get('description')
        if not all(isinstance(v, str) and 0 < len(v.strip()) <= 1000 for v in (uncertainty, description)):
            raise ValueError('description and uncertainty are required')
        hypothesis = self.hypothesis(args.get('hypothesis_id'))
        if camera['image_id'] not in {v['image_id'] for v in hypothesis['views']}:
            raise ValueError('observation photo is not in the hypothesis')
        ident = 'observation-' + uuid.uuid4().hex
        features = args.get('feature_ids', [])
        if (not isinstance(features, list) or len(features) != (1 if kind == 'point' else 2 if kind == 'line' else 0) or
            any(not isinstance(x, str) or not re.fullmatch(r'p[1-9][0-9]?', x) for x in features) or
            len(set(features)) != len(features)):
            raise ValueError('point needs one feature ID, line needs two, plane needs none')
        sigma = args.get('sigma_px')
        if isinstance(sigma, bool) or not isinstance(sigma, (int, float)) or not math.isfinite(sigma) or not 0 < sigma <= 100:
            raise ValueError('positive pixel uncertainty up to 100 is required')
        observation = {'id': ident, 'origin': 'ai_suggested', 'confirmation': 'proposed',
            'provider': self.provider, 'hypothesis_id': hypothesis['id'], 'image_id': camera['image_id'],
            'photo_sha256': camera['sha256'], 'camera_sha256': camera_digest(camera), 'kind': kind,
            'points_original_px': [[p[0]*camera['width_px'], p[1]*camera['height_px']] for p in points],
            'feature_ids': features, 'sigma_px': sigma, 'uncertainty': uncertainty,
            'description': description, 'visibility': 'visible_unverified',
            'created_at': datetime.now(timezone.utc).isoformat()}
        with (self.output / (ident + '.json')).open('x') as stream:
            json.dump(observation, stream, ensure_ascii=False, indent=2, allow_nan=False)
        return observation

    def candidate(self, ident: str) -> dict:
        if not isinstance(ident, str) or not re.fullmatch(r'candidate-[0-9a-f]{16}', ident):
            raise ValueError('invalid candidate ID')
        result = read_json(self.output / (ident + '.json'))
        if result.get('project_id') != self.project['id'] or result.get('state_revision') != self.state['revision']:
            raise ValueError('candidate belongs to a different project or modeler revision')
        if result['solution'].get('input_sha256') != digest(result['data']):
            raise ValueError('candidate observations changed after solving')
        return result

    def inspect_element(self, args: dict) -> dict:
        from .modeling_tools import inspect_element
        return inspect_element(self.model(), args.get('element_id'))

    def preview_revision(self, args: dict) -> dict:
        revision = self.project.get('current_revision')
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError('no saved IR model')
        from .modeling_tools import inspect_element, update_element, validate_geometry
        model = self.model()
        revised, diff = update_element(model, args.get('element_id'), args.get('attribute'), args.get('value'),
                                       reason=args.get('reason'), operator='analyst')
        ident = 'revision-proposal-' + uuid.uuid4().hex
        proposal = {'id': ident, 'status': 'AI_PROPOSED_UNVERIFIED', 'provider': self.provider,
                    'project_id': self.project['id'], 'source_model_revision': revision,
                    'source_model_sha256': digest(model), 'element_id': args.get('element_id'),
                    'attribute': args.get('attribute'), 'value': args.get('value'), 'reason': args.get('reason'),
                    'diff': diff, 'validation_before': validate_geometry(model), 'validation': validate_geometry(revised),
                    'affected_geometry': [{'id': ident,
                        'before': inspect_element(model, ident), 'after': inspect_element(revised, ident)}
                        for ident in diff['affected_elements']]}
        with (self.output / (ident + '.json')).open('x') as stream:
            json.dump(proposal, stream, ensure_ascii=False, indent=2, allow_nan=False)
        # Full geometry remains available for explicit review in Studio. Sending
        # duplicated element/geometry blobs back into the model on every tool
        # call inflates context without improving the deterministic check.
        return {k:proposal[k] for k in ('id','status','element_id','attribute','value','diff','validation')}

    def solve_surface(self, args: dict) -> dict:
        ids, views = args.get('track_ids'), args.get('image_ids')
        if (not isinstance(ids, list) or not 3 <= len(ids) <= 12 or len(set(ids)) != len(ids) or
            any(isinstance(i, bool) or not isinstance(i, int) for i in ids)):
            raise ValueError('supply 3–12 distinct ordered track IDs')
        if (not isinstance(views, list) or len(set(views)) != len(views) or not 2 <= len(views) <= 8 or
            any(isinstance(i, bool) or not isinstance(i, int) for i in views)):
            raise ValueError('supply 2–8 distinct registered image IDs')
        hypothesis = self.hypothesis(args.get('hypothesis_id'))
        if hypothesis['label'] != 'wall' or not set(views) <= {v['image_id'] for v in hypothesis['views']}:
            raise ValueError('candidate needs an unverified wall hypothesis for every selected photo')
        if not all(isinstance(args.get(k), str) and args[k].strip() and len(args[k]) <= 1000 for k in ('reason', 'uncertainty')):
            raise ValueError('track selection reason and uncertainty are required')
        cameras = [self.camera(v) for v in views]
        for camera in cameras:self.photo(camera)
        tracks = {t['id']: t for t in self.tracks()};now = datetime.now(timezone.utc).isoformat()
        observations = []
        for index, ident in enumerate(ids):
            track = tracks.get(ident)
            if track is None:raise ValueError('unknown track')
            matched = [o for o in track['observations'] if o['image_id'] in views]
            if len({o['image_id'] for o in matched}) < 2:raise ValueError('each track needs at least two selected views')
            for item in matched:
                camera = self.camera(item['image_id'])
                region = next(v['bbox_normalized'] for v in hypothesis['views'] if v['image_id'] == camera['image_id'])
                x, y = item['pixel_xy'];nx, ny = x/camera['width_px'], y/camera['height_px']
                if not (region[0] <= nx <= region[2] and region[1] <= ny <= region[3]):
                    raise ValueError('track lies outside the declared wall region')
                observations.append({'kind': 'point', 'object_id': 'agent-candidate', 'feature_id': f'p{index+1}',
                    'image_id': camera['image_id'], 'pixel_xy': item['pixel_xy'], 'photo_sha256': camera['sha256'],
                    'camera_sha256': camera_digest(camera), 'origin': 'deterministic',
                    'confirmation': 'automation_unverified', 'visibility': 'visible', 'sigma_px': 2.0,
                    'track_id': ident, 'track_source': self.state.get('track_source','COLMAP registered feature tracks'),
                    'created_at': now})
        data = {'schema': SCHEMA_INPUT, 'camera_mode': self.state['camera_mode'],
                'coordinate_system': {'name': 'registered reconstruction', 'scale_status': 'UNKNOWN'},
                'source_reconstruction': self.state['source_reconstruction'], 'cameras': cameras,
                'objects': [{'id': 'agent-candidate', 'ifc_type': 'IfcWall',
                             'vertices': [f'p{i+1}' for i in range(len(ids))], 'surface_kind': 'visible_surface_patch'}],
                'observations': observations, 'object_constraints': []}
        return self.save_solved(data, hypothesis, {'track_ids': ids, 'image_ids': views,
            'reason': args['reason'], 'uncertainty': args['uncertainty']})

    def save_solved(self, data: dict, hypothesis: dict, selection: dict) -> dict:
        solution = solve_modeler(data)
        candidate = {'schema': 'worldstate-agent-surface-candidate/0.1', 'status': 'UNVERIFIED',
                     'project_id': self.project['id'], 'state_revision': self.state['revision'],
                     'provider': self.provider + ' + WorldState deterministic Modeler',
                     'agent_hypothesis': hypothesis,
                     'agent_selection': selection,
                     'data': data, 'solution': solution,
                     'limitations': ['Selected image features can lie on furniture or occlusion boundaries.',
                                     'Hull is not an observed complete wall boundary.',
                                     'Scale and physical dimensions are unknown.']}
        name = 'candidate-' + digest({'selection': selection, 'hypothesis': hypothesis['id'],
                                      'project': self.project['id']})[:16] + '.json'
        destination = self.output / name
        if destination.exists() or destination.is_symlink():raise ValueError('candidate output already exists')
        with destination.open('x') as stream:
            json.dump(candidate, stream, ensure_ascii=False, indent=2, allow_nan=False)
        return {'candidate_id': name.removesuffix('.json'), 'solution': solution,
                'status': 'UNVERIFIED_FEATURE_HULL', 'scale_status': 'UNKNOWN',
                'limitations': candidate['limitations']}

    def solve_observations(self, args: dict) -> dict:
        ids, hypothesis = args.get('observation_ids'), self.hypothesis(args.get('hypothesis_id'))
        if hypothesis['label'] != 'wall':raise ValueError('an unverified wall hypothesis is required')
        if (not isinstance(ids, list) or not 6 <= len(ids) <= 48 or len(set(ids)) != len(ids) or
            any(not isinstance(i, str) or not re.fullmatch(r'observation-[0-9a-f]{32}', i) for i in ids)):
            raise ValueError('supply 6–48 distinct proposed observation IDs')
        if not all(isinstance(args.get(k), str) and args[k].strip() and len(args[k]) <= 1000 for k in ('reason', 'uncertainty')):
            raise ValueError('observation selection reason and uncertainty are required')
        records = [read_json(self.output / (ident + '.json')) for ident in ids]
        if any(r.get('hypothesis_id') != hypothesis['id'] or r.get('confirmation') != 'proposed' for r in records):
            raise ValueError('all observations must be proposed by the same hypothesis')
        features = sorted({r['feature_ids'][0] for r in records if r['kind'] == 'point'},
                          key=lambda x: int(x[1:]))
        if not 3 <= len(features) <= 12:raise ValueError('at least three distinct point features are required')
        views = sorted({r['image_id'] for r in records});cameras = [self.camera(v) for v in views]
        if len(cameras) < 2:raise ValueError('at least two authorized views are required')
        observations = []
        for record in records:
            camera = self.camera(record['image_id']);self.photo(camera)
            if record['photo_sha256'] != camera['sha256'] or record['camera_sha256'] != camera_digest(camera):
                raise ValueError('observation photo or camera has changed')
            region = next(v['bbox_normalized'] for v in hypothesis['views'] if v['image_id'] == camera['image_id'])
            if any(not (region[0] <= p[0]/camera['width_px'] <= region[2] and
                       region[1] <= p[1]/camera['height_px'] <= region[3]) for p in record['points_original_px']):
                raise ValueError('observation lies outside the declared wall region')
            common = {'kind': record['kind'], 'object_id': 'agent-candidate', 'image_id': camera['image_id'],
                'photo_sha256': camera['sha256'], 'camera_sha256': camera_digest(camera), 'origin': 'ai_suggested',
                'confirmation': 'automation_unverified', 'visibility': 'visible', 'sigma_px': record['sigma_px'],
                'created_at': record['created_at'], 'agent_observation_id': record['id'],
                'provider': record['provider'], 'uncertainty_note': record['uncertainty']}
            if record['kind'] == 'point':common.update(feature_id=record['feature_ids'][0], pixel_xy=record['points_original_px'][0])
            elif record['kind'] == 'line':common.update(feature_ids=record['feature_ids'], points_px=record['points_original_px'])
            else:common.update(semantic_label=hypothesis['label'], polygon_px=record['points_original_px'])
            observations.append(common)
        data = {'schema': SCHEMA_INPUT, 'camera_mode': self.state['camera_mode'],
                'coordinate_system': {'name': 'registered reconstruction', 'scale_status': 'UNKNOWN'},
                'source_reconstruction': self.state['source_reconstruction'], 'cameras': cameras,
                'objects': [{'id': 'agent-candidate', 'ifc_type': 'IfcWall', 'vertices': features,
                             'surface_kind': 'visible_surface_patch'}],
                'observations': observations, 'object_constraints': []}
        return self.save_solved(data, hypothesis, {'observation_ids': ids, 'image_ids': views,
                                'reason': args['reason'], 'uncertainty': args['uncertainty']})

    def compile_ifc(self, args: dict) -> dict:
        ident = args.get('candidate_id')
        if not self.approved_constraints:
            raise ValueError('IFC requires operator-provided scale, up, thickness and rectangular-approximation approval')
        config = self.approved_constraints
        if config.get('operator_confirmed') is not True:
            raise ValueError('IFC assumptions require explicit operator confirmation')
        candidate = self.candidate(ident)
        model = build_room_ir(candidate['data'], candidate['solution'], project_id=self.project['id'],
                              scale=config.get('scale'), thickness_m=config.get('thickness_m'),
                              up_source=config.get('up_source'),
                              allow_rectangular_approximation=config.get('allow_rectangular_approximation'))
        hypothesis = candidate['agent_hypothesis']
        model['evidence'].append({'id': 'agent-hypothesis', 'kind': 'ai_semantic_hypothesis',
                                  'status': 'inferred', 'data': hypothesis})
        model['elements'][0]['classification']['evidence_refs'].append('agent-hypothesis')
        from .room_ifc import export_room
        ifc_path = self.output / (ident + '.ifc')
        model_path = self.output / (ident + '-ir.json')
        if model_path.exists() or model_path.is_symlink():raise ValueError('IR output already exists')
        export_room(model, ifc_path)
        with model_path.open('x') as stream:json.dump(model, stream, ensure_ascii=False, indent=2, allow_nan=False)
        return {'status': 'UNVERIFIED_IFC_DRAFT', 'ifc_file': ifc_path.name, 'ir_file': model_path.name,
                'scale': model['scale'], 'validation': model['validation']}

    def execute(self, action: str, args: dict) -> dict:
        operations = {'inspect_scene': self.inspect_scene, 'view_photo': self.view_photo,
                      'inspect_model_projection': self.inspect_model_projection,
                      'preview_projection_repair': self.preview_projection_repair,
                      'find_tracks': self.find_tracks, 'record_hypothesis': self.record_hypothesis,
                      'record_image_observation': self.record_image_observation,
                      'inspect_element': self.inspect_element, 'preview_revision': self.preview_revision,
                      'solve_surface': self.solve_surface, 'solve_observations': self.solve_observations,
                      'compile_ifc': self.compile_ifc}
        if action not in operations or not isinstance(args, dict):raise ValueError('unsupported agent tool')
        return operations[action](args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provider', default='unspecified')
    parser.add_argument('--approved-constraints', type=Path)
    parser.add_argument('--allowed-images', help='Comma-separated operator-authorized registered image IDs')
    parser.add_argument('--deny-images', action='store_true', help='Restrict model-only tasks from all photo observations')
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        if args.deny_images and args.allowed_images:raise ValueError('photo scope conflicts with model-only mode')
        allowed = set() if args.deny_images else {int(x) for x in args.allowed_images.split(',')} if args.allowed_images else None
        result = AgentTools(args.workspace, args.output, args.provider, args.approved_constraints, allowed).execute(request['action'], request.get('arguments', {}))
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)[:1000]}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
