"""Compare same-photo semantic track support with a real agent run; no truth claims."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from products.worldstate_bim.agent_tools import AgentTools


def compare(workspace: Path, masks: Path, run: Path, images: list[int], output: Path) -> dict:
    if output.exists():raise FileExistsError('use a new output file')
    tools = AgentTools(workspace, run, 'comparison', allowed_images=set(images))
    manifest = json.loads((masks / 'manifest.json').read_text());records = {r['name']: r for r in manifest['images']}
    cameras = {i: tools.camera(i) for i in images};labels = {}
    for ident, camera in cameras.items():
        tools.photo(camera);record = records[camera['photo']]
        if record['sha256'] != camera['sha256'] or (record['width_px'], record['height_px']) != (camera['width_px'], camera['height_px']):
            raise ValueError('semantic mask does not bind to the same source image')
        mask = masks / record['mask_file']
        if mask.is_symlink() or hashlib.sha256(mask.read_bytes()).hexdigest() != record['mask_sha256']:
            raise ValueError('semantic mask hash mismatch')
        with np.load(mask, allow_pickle=False) as item:labels[ident] = item['labels'].copy()
    started = time.monotonic();shared = both_wall = disagreement = 0
    for track in tools.tracks():
        observations = {o['image_id']: o for o in track['observations'] if o['image_id'] in cameras}
        if len(observations) != len(cameras):continue
        shared += 1;classes = []
        for ident, observation in observations.items():
            camera = cameras[ident];x, y = observation['pixel_xy'];mask = labels[ident]
            ix = min(mask.shape[1]-1, int(x*mask.shape[1]/camera['width_px']))
            iy = min(mask.shape[0]-1, int(y*mask.shape[0]/camera['height_px']))
            classes.append(int(mask[iy, ix]))
        both_wall += int(all(c == 0 for c in classes))
        disagreement += int(any(c == 0 for c in classes) and not all(c == 0 for c in classes))
    metadata = json.loads((run / 'run.json').read_text()) if (run / 'run.json').is_file() else {}
    viewed = set()
    trace = run / 'agent-tool-trace.jsonl'
    if trace.is_file():
        for line in trace.read_text().splitlines():
            event = json.loads(line)
            if event.get('tool') == 'view_photo' and event.get('status') == 'ok':viewed.add(event['arguments']['image_id'])
    usage = metadata.get('usage');model_turn_completed = False
    events = run / 'events.jsonl'
    if not metadata and events.is_file():
        for line in events.read_text().splitlines():
            event = json.loads(line)
            if event.get('type') == 'turn.completed':usage = event.get('usage');model_turn_completed = True
    scope = ('SAME_SELECTED_IMAGES' if metadata.get('image_ids') and set(metadata['image_ids']) == set(images)
             else 'NOT_INDEPENDENTLY_CONFIRMED' if not metadata else 'DIFFERENT_INPUTS')
    result = {'image_ids': images, 'input_scope': scope,
        'rule_route': {'shared_tracks': shared, 'all_views_labeled_wall': both_wall,
                       'wall_nonwall_disagreement': disagreement, 'valid_wall_instances': 'NOT_MEASURED',
                       'new_ifc': 0, 'comparison_seconds_using_cached_masks': round(time.monotonic()-started, 3)},
        'agent_route': {'status': metadata.get('status', 'MODEL_TURN_COMPLETED_SUPERVISOR_INTERRUPTED' if model_turn_completed else 'SUPERVISOR_INTERRUPTED'),
                        'selected_image_ids': metadata.get('image_ids', []), 'viewed_image_ids': sorted(viewed),
                        'hypotheses': len(list(run.glob('hypothesis-*.json'))),
                        'solved_candidates': len(list(run.glob('candidate-*.json'))),
                        'new_ifc': len(list(run.glob('candidate-*.ifc'))),
                        'elapsed_seconds': metadata.get('elapsed_seconds'), 'usage': usage,
                        'model_cost': 'NOT_MEASURED'},
        'manual_route': {'status': 'NOT_MEASURED_NO_HUMAN_OPERATOR'},
        'limitations': ['Cached segmentation scores are not ground truth or wall-instance recognition.',
                        'A wall/nonwall disagreement is not a verified correspondence error.',
                        'No independent human review, accepted-model count or labor cost is available.',
                        'Different agent input images cannot be directly ranked against this photo pair.']}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True);parser.add_argument('--masks', type=Path, required=True)
    parser.add_argument('--agent-run', type=Path, required=True);parser.add_argument('--images', type=int, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.workspace, args.masks, args.agent_run, args.images, args.output), indent=2))
