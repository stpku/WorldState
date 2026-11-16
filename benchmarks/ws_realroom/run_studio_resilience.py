"""Repeat browser marking on disposable copies and retain failures, never human data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def isolated_copy(source: Path, destination: Path) -> None:
    subprocess.run(['cp', '-a', '--reflink=auto', str(source), str(destination)], check=True)
    project_path = destination / 'photo-project.json'
    project = json.loads(project_path.read_text())
    project['operator_kind'] = 'automation'
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + '\n')


def run_one(args: argparse.Namespace, number: str, script: str) -> dict:
    root = args.output / number
    root.mkdir()
    workspace = root / 'workspace'
    isolated_copy(args.source, workspace)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}/'
    with (root / 'server.log').open('w') as server_log:
        server = subprocess.Popen([args.python, '-m', 'products.worldstate_bim.studio_server',
                                   '--workspace', str(workspace), '--port', str(port)],
                                  cwd=ROOT, stdout=server_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError(f'server exited {server.returncode}')
                try:
                    with urllib.request.urlopen(url + 'api/project', timeout=2) as response:
                        if json.load(response)['project']['operator_kind'] != 'automation':
                            raise RuntimeError('project is not an isolated automation copy')
                        break
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    time.sleep(.25)
            else:
                raise TimeoutError('server did not start')
            command = [args.node, str(ROOT / 'benchmarks/ws_realroom' / script), url]
            if script == 'studio_ux_reset_browser.cjs':
                command.append(str(args.input))
            command.append(str(root / 'browser'))
            started = time.monotonic()
            with (root / 'browser.log').open('w') as browser_log:
                result = subprocess.run(command, cwd=ROOT, env=os.environ.copy(),
                                        stdout=browser_log, stderr=subprocess.STDOUT, timeout=240)
            return {'run': number, 'returncode': result.returncode,
                    'elapsed_seconds': round(time.monotonic() - started, 2)}
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', default='python')
    parser.add_argument('--node', default='node')
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10:
        parser.error('--runs must be between 1 and 10')
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    try:
        for index in range(args.runs):
            result = run_one(args, f'continuous-{index+1}', 'studio_ux_reset_browser.cjs')
            results.append(result)
            print(json.dumps(result), flush=True)
        result = run_one(args, 'fault-injection', 'studio_ux_retry_check.cjs')
        results.append(result)
        print(json.dumps(result), flush=True)
    finally:
        (args.output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    return int(any(row['returncode'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
