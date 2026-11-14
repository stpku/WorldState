"""Compare sparse surfaces and multiview lines even when either route fails.

Inputs are a single reconstruction, registered image set and semantic masks.
This is a development diagnostic, not independent ground truth or acceptance.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from benchmarks.ws_geometry.run_structure_comparison import draw_overlays
from products.worldstate_bim.multiview_fusion import fuse_multiview
from products.worldstate_bim.structure_from_lines import extract_lines, solve_lines


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sparse', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--masks', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('choose a new output directory')
    started = time.monotonic()
    fusion = fuse_multiview(a.sparse, a.images, a.masks)
    route_a_s = time.monotonic()-started
    started = time.monotonic()
    lines = extract_lines(fusion, a.sparse, a.images, a.masks)
    structure = solve_lines(fusion, lines)
    route_b_s = time.monotonic()-started
    a.output.mkdir(parents=True)
    save(a.output/'fusion.json', fusion)
    save(a.output/'detected-lines.json', lines)
    save(a.output/'structure.json', structure)
    overlays = draw_overlays(structure, fusion, a.images, a.output/'overlays')
    def eligible(g: dict) -> bool:
        return (g['floor_consistency'] == 'CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY'
                and g['floor_joint_holdout_status'] == 'CONSISTENT_UNVERIFIED'
                and bool(g['visible_support_intervals']))
    summary = {'schema': 'worldstate-structure-diagnostics/0.1',
        'input': {'registered_or_supplied_cameras': len(fusion['cameras']), 'tracks': len(fusion['tracks']),
                  'source_reconstruction': fusion['source_reconstruction'],
                  'semantic_manifest_sha256': fusion['semantic_manifest_sha256']},
        'route_a': {'method': 'semantic sparse tracks and plane fitting', 'runtime_seconds': route_a_s,
            'floor_planes': [{'id': x['id'], 'support_points': x['support_count'],
                              'support_views': len(x['support_views']), 'fit_rms_source_units': x['fit_rms_arbitrary']}
                             for x in fusion['floor_planes']],
            'wall_surface_hypotheses': [{'id': x['id'], 'support_points': x['support_count'],
                'support_views': x['support_view_count'], 'fit_rms_source_units': x['fit_rms_arbitrary'],
                'visible_candidate': bool(x.get('visible_candidate'))} for x in fusion['wall_surfaces']]},
        'route_b': {'method': 'multiview image boundary lines with shared route-A sparse-floor prior',
            'runtime_seconds': route_b_s, 'image_line_proposals': len(lines['lines']),
            'line_hypotheses': [{'id': x['id'], 'support_views': x['support_view_count'],
                'floor_consistency': x['floor_consistency'],
                'floor_signed_distances_at_support_ends_source_units': x['floor_signed_distances_at_support_ends_relative'],
                'floor_consistency_threshold_source_units': x['floor_consistency_threshold_relative'],
                'floor_joint_holdout_status': x['floor_joint_holdout_status'],
                'floor_joint_holdout_max_px': max((v['error_px'] for v in x['floor_joint_leave_one_view_out_px']), default=None),
                'free_line_holdout_max_px': max((v['error_px'] for v in x['free_line_leave_one_view_out_px']), default=None),
                'eligible_for_draft': eligible(x)} for x in structure['groups']],
            'eligible_count': sum(eligible(x) for x in structure['groups']),
            'corner_candidates': len(structure['corner_candidates'])},
        'overlays': overlays, 'independent_dimensions': 'NOT_MEASURED',
        'independent_wall_instances': 'NOT_MEASURED', 'human_time': 'NOT_MEASURED',
        'caveats': ['Both routes use identical inputs and route B shares route A floor prior.',
            'Source pose inputs and physical scale must be evaluated separately; this tool does not establish them.',
            'Candidate count, fit residual and leave-one-view-out reprojection are not independent accuracy.',
            'Leave-one-view-out excludes a view during line fitting only; associations, cameras and floor use all views.']}
    save(a.output/'diagnostics.json', summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
