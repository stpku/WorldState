"""Run a real Codex modeling experiment on explicitly authorized photos."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from products.worldstate_bim.agent_runner import run_codex_agent


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--images', type=int, nargs='+', required=True)
    parser.add_argument('--goal', required=True)
    parser.add_argument('--codex', default='codex');parser.add_argument('--node', default='node')
    parser.add_argument('--model', default='gpt-6.1-terra');parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--allow-external-images', action='store_true',
                        help='Confirm permission to send only the selected photos to the model provider')
    args = parser.parse_args()
    if not args.allow_external_images:parser.error('explicit photo-transfer authorization is required')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = run_codex_agent(workspace=args.workspace, output=args.output, image_ids=args.images,
                             goal=args.goal, codex=args.codex, node=args.node, model=args.model,
                             timeout=args.timeout)
    print(json.dumps({k: result.get(k) for k in ('status', 'elapsed_seconds', 'usage',
          'successful_tools', 'tool_failures', 'candidates', 'hypotheses', 'revision_proposals')}, ensure_ascii=False))
