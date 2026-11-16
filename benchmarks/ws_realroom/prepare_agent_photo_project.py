"""Import authorized real photos and registered cameras into a fresh research workspace."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import threading
import urllib.request

from products.worldstate_bim.studio_server import StudioServer


def prepare(images: Path, manifest_path: Path, output: Path, name: str) -> dict:
    if output.exists():raise FileExistsError('use a new workspace; existing projects are never overwritten')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 'worldstate-modeler-cameras/0.1':raise ValueError('invalid camera manifest')
    cameras = manifest.get('cameras', [])
    for camera in cameras:
        filename = camera['photo'];source = images / filename
        if Path(filename).name != filename or source.is_symlink() or not source.is_file():raise ValueError('invalid photo path')
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != camera['sha256']:raise ValueError('photo hash mismatch')
    server = StudioServer(0, None, output);thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    def post(path: str, value: dict) -> dict:
        request = urllib.request.Request(origin + path, data=json.dumps(value).encode(), headers={
            'Content-Type': 'application/json', 'Origin': origin, 'X-WorldState-Token': server.token})
        with urllib.request.urlopen(request, timeout=60) as response:return json.load(response)
    try:
        post('/api/project', {'name': name, 'operator_kind': 'automation'})
        for camera in cameras:
            raw = (images / camera['photo']).read_bytes()
            item = post('/api/upload', {'data_base64': base64.b64encode(raw).decode()})
            if item['sha256'] != camera['sha256']:raise ValueError('uploaded photo hash mismatch')
        state = post('/api/modeler/cameras', {'manifest': manifest})
        return {'workspace': str(output), 'registered': len(state['cameras']),
                'tracks': state['track_count'], 'camera_mode': state['camera_mode'],
                'operator': 'automation', 'status': 'UNVERIFIED_DEVELOPMENT_PROJECT'}
    finally:
        server.shutdown();server.server_close();thread.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.images, args.manifest, args.output, args.name), indent=2))
