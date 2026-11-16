"""Create a separate model-only CRASLAB research project; no photos are implied."""
import argparse
import json
from pathlib import Path
import shutil

from products.worldstate_bim.room_ir import validate_room


def prepare(source: Path, output: Path, operator: str) -> None:
    source = source.resolve(strict=True)
    if output.exists():
        raise FileExistsError('choose a new workspace; existing projects are never overwritten')
    model = json.loads((source / 'model.json').read_text())
    validate_room(model)
    if model['revision'] != 1 or not (source / 'model.ifc').is_file():
        raise ValueError('expected a complete first revision')
    output.mkdir(mode=0o700, parents=True)
    revision = output / 'revision-001';revision.mkdir(mode=0o700)
    for name in ('model.json', 'model.ifc'):
        shutil.copyfile(source / name, revision / name)
    project = {'schema': 'worldstate-photo-project/0.1', 'id': model['project_id'],
               'name': 'CRASLAB scan-derived BIM · model-only research',
               'operator_kind': operator, 'current_revision': 1, 'events': [],
               'notes': 'No registered site photos. Cloud2BIM classifications and dimensions remain unverified.'}
    (output / 'photo-project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2) + '\n')
    (output / 'evidence-index.json').write_text(json.dumps({'schema': 'worldstate-studio-evidence/0.1',
                                                           'uploads': []}) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--operator', choices=('user', 'automation'), required=True)
    a = p.parse_args();prepare(a.source, a.output, a.operator)
    print(json.dumps({'workspace': str(a.output), 'source': str(a.source),
                      'photos': 0, 'status': 'UNVERIFIED_SCAN_DERIVED_MODEL'}))
