"""Scoped Studio integration for a single optional Codex modeling run."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import threading
import uuid
from datetime import datetime, timezone

from .agent_tools import AgentTools, read_json
from .general_modeler import camera_digest, digest, solve_modeler


def persist_job(server, job: dict) -> None:
    from .studio_server import _write_json
    value = {k: v for k, v in job.items() if k != 'output'}
    value['project_id'] = server.project['id']
    _write_json(job['output'] / 'job.json', value)


def recover_job(server) -> dict | None:
    """Recover the newest completed job; interrupted jobs are never retried."""
    if not server.agent_settings or not server.project:return None
    root = server.agent_settings['output_root'];jobs = []
    for directory in root.glob('agent-*'):
        if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(r'agent-[0-9a-f]{32}', directory.name):continue
        try:
            item = read_json(directory / 'job.json')
            if item.get('project_id') != server.project['id'] or item.get('id') != directory.name:continue
            if not isinstance(item.get('image_ids'), list) or not isinstance(item.get('started_at'), str):continue
            item.pop('project_id');item['output'] = directory
            jobs.append(item)
        except (ValueError, KeyError, OSError, TypeError):continue
    if not jobs:return None
    job = max(jobs, key=lambda item: item['started_at'])
    if job.get('status') == 'RUNNING':
        job.update(status='INTERRUPTED', error='服务重启中断了任务；未自动重试。')
        persist_job(server, job)
    return job


def status(server) -> dict:
    job = server.agent_job
    result = {'enabled': server.agent_settings is not None,
              'provider': server.agent_settings['model'] if server.agent_settings else None,
              'image_transfer_requires_confirmation': True, 'job': None}
    if not job:return result
    public = {k: job.get(k) for k in ('id', 'status', 'source_revision', 'image_ids', 'result', 'candidates', 'error')}
    trace = job['output'] / 'agent-tool-trace.jsonl';events = []
    if trace.is_file() and not trace.is_symlink():
        with trace.open() as stream:
            for line in stream:
                try:item = json.loads(line)
                except json.JSONDecodeError:continue
                events.append({k: item.get(k) for k in ('time', 'tool', 'status', 'error')})
        events = events[-30:]
    hypotheses = [];artifact_errors = []
    for path in sorted(job['output'].glob('hypothesis-*.json'))[:30]:
        if not re.fullmatch(r'hypothesis-[0-9a-f]{32}\.json', path.name):continue
        try:
            item = read_json(path)
            if item.get('status') != 'AI_SUGGESTED_UNVERIFIED':raise ValueError('invalid hypothesis status')
            if not {v['image_id'] for v in item['views']} <= set(job['image_ids']):raise ValueError('unauthorized photo')
            hypotheses.append(item)
        except (ValueError, KeyError, OSError, TypeError):artifact_errors.append(path.stem)
    revisions = []
    for path in sorted(job['output'].glob('revision-proposal-*.json'))[:20]:
        if not re.fullmatch(r'revision-proposal-[0-9a-f]{32}\.json', path.name):continue
        try:
            item = read_json(path)
            if item.get('status') != 'AI_PROPOSED_UNVERIFIED':raise ValueError('invalid revision proposal')
            revisions.append(item)
        except (ValueError, KeyError, OSError, TypeError):artifact_errors.append(path.stem)
    public.update(events=events, hypotheses=hypotheses, revision_proposals=revisions,
                  artifact_errors=artifact_errors);result['job'] = public
    return result


def start(handler, body: dict) -> None:
    server = handler.server;settings = server.agent_settings
    if settings is None:raise ValueError('未配置多模态建模 Agent；当前仍为本地规则模式')
    if body.get('allow_external_images') is not True:
        raise ValueError('请先明确同意将选定照片发送至已配置模型')
    goal, images, selected = body.get('goal'), body.get('image_ids'), body.get('selected_id')
    if (not isinstance(goal, str) or not goal.strip() or len(goal) > 1000 or
        not isinstance(images, list) or not 2 <= len(images) <= 8 or
        any(isinstance(i, bool) or not isinstance(i, int) for i in images) or len(set(images)) != len(images)):
        raise ValueError('请输入任务并选择 2–8 张不同的已注册照片')
    state = (server.project or {}).get('general_modeler')
    if not state or not set(images) <= {c['image_id'] for c in state['cameras']}:
        raise ValueError('所选照片未注册到当前项目')
    known = {o['id'] for o in state['objects']} | {e['id'] for e in (server.model or {}).get('elements', [])}
    if selected is not None and (not isinstance(selected, str) or selected not in known):
        raise ValueError('选中构件不属于当前项目')
    if server.agent_job and server.agent_job['status'] == 'RUNNING':
        raise ValueError('已有 Agent 任务正在运行')
    ident = 'agent-' + uuid.uuid4().hex
    output = settings['output_root'] / ident
    output.mkdir(mode=0o700)
    job = {'id': ident, 'status': 'RUNNING', 'source_revision': state['revision'],
           'image_ids': list(images), 'selected_id': selected, 'output': output, 'result': '', 'candidates': [], 'error': None,
           'started_at': datetime.now(timezone.utc).isoformat()}
    persist_job(server, job)
    server.agent_job = job

    def worker() -> None:
        try:
            from .agent_runner import run_codex_agent
            result = run_codex_agent(workspace=server.workspace, output=output, image_ids=images, goal=goal,
                codex=settings['codex'], node=settings['node'], model=settings['model'],
                timeout=settings['timeout'], selected_id=selected)
            with server.lock:
                job.update(status=result['status'], result=result['result'], candidates=result['candidates'],
                           error=result.get('error'))
                persist_job(server, job)
        except Exception as exc:
            with server.lock:
                job.update(status='FAILED', error=str(exc)[:500]);persist_job(server, job)

    threading.Thread(target=worker, name='worldstate-modeling-agent', daemon=True).start()
    handler.send_json(202, status(server))


def accept(handler, body: dict) -> None:
    """Import one solved candidate as explicitly unverified machine evidence."""
    server = handler.server;job = server.agent_job
    if not job or job['id'] != body.get('job_id') or job['status'] not in {'COMPLETED', 'COMPLETED_NO_SOLVED_CANDIDATE'}:
        raise ValueError('Agent 任务不可用或尚未完成')
    ident = body.get('candidate_id')
    if not isinstance(ident, str) or not re.fullmatch(r'candidate-[0-9a-f]{16}', ident) or ident not in job['candidates']:
        raise ValueError('请选择本次任务的已求解候选')
    state = (server.project or {}).get('general_modeler')
    if not state or body.get('state_revision') != state['revision'] or state['revision'] != job['source_revision']:
        raise ValueError('项目或相机观察已改变；请重新运行 Agent')
    tools = AgentTools(server.workspace, job['output'], 'studio-agent', allowed_images=set(job['image_ids']))
    candidate = tools.candidate(ident);data = candidate['data']
    if candidate['agent_hypothesis'].get('provider') != 'codex-cli:' + server.agent_settings['model']:
        raise ValueError('候选模型来源与本次任务不一致')
    if any(o.get('origin') not in {'deterministic', 'ai_suggested'} or
           o.get('confirmation') != 'automation_unverified' for o in data['observations']):
        raise ValueError('候选包含不受支持或冒充人工确认的观察')
    if any(c['image_id'] not in job['image_ids'] for c in data['cameras']):
        raise ValueError('候选使用了未授权照片')
    for camera in data['cameras']:
        current = tools.camera(camera['image_id']);tools.photo(current)
        if camera_digest(camera) != camera_digest(current):raise ValueError('候选相机版本已改变')
    tracks = {t['id']: t for t in tools.tracks()}
    for observation in data['observations']:
        if observation['origin'] == 'deterministic':
            track = tracks.get(observation.get('track_id'))
            match = next((o for o in (track or {}).get('observations', [])
                          if o['image_id'] == observation['image_id']), None)
            if not match or match['pixel_xy'] != observation.get('pixel_xy'):
                raise ValueError('候选特征点与已登记轨迹不一致')
        else:
            ref = observation.get('agent_observation_id')
            if not isinstance(ref, str) or not re.fullmatch(r'observation-[0-9a-f]{32}', ref):
                raise ValueError('候选缺少 AI 观察来源')
            source = read_json(job['output'] / (ref + '.json'))
            if (source.get('hypothesis_id') != candidate['agent_hypothesis']['id'] or
                source.get('image_id') != observation['image_id'] or
                source.get('photo_sha256') != observation['photo_sha256'] or
                source.get('camera_sha256') != observation['camera_sha256'] or
                source.get('kind') != observation['kind'] or source.get('sigma_px') != observation['sigma_px']):
                raise ValueError('候选 AI 观察与来源记录不一致')
            if observation['kind'] == 'point':
                same = (source['feature_ids'] == [observation['feature_id']] and
                        source['points_original_px'] == [observation['pixel_xy']])
            elif observation['kind'] == 'line':
                same = (source['feature_ids'] == observation['feature_ids'] and
                        source['points_original_px'] == observation['points_px'])
            else:
                same = source['points_original_px'] == observation.get('polygon_px')
            if not same:raise ValueError('候选 AI 像素或特征编号已改变')
    solve_modeler(data)  # Re-run the existing geometry gates before import.
    object_id = 'ai-' + job['id'].removeprefix('agent-')[:12]
    if any(o['id'] == object_id for o in state['objects']):raise ValueError('该候选已导入')
    obj = copy.deepcopy(data['objects'][0]);obj['id'] = object_id
    obj['agent_hypothesis'] = copy.deepcopy(candidate['agent_hypothesis'])
    obj['agent_source'] = {'job_id': job['id'], 'candidate_id': ident, 'status': 'UNVERIFIED'}
    observations = copy.deepcopy(data['observations'])
    for observation in observations:observation['object_id'] = object_id
    state['objects'].append(obj);state['observations'].extend(observations)
    state['solution'] = None;state['model_dirty'] = True;state['suggestions'] = [];state['revision'] += 1
    operator = 'automation_accepted_unverified' if server.project.get('operator_kind') == 'automation' else 'user_accepted_unverified'
    server.record('agent_candidate_imported', object_id=object_id, job_id=job['id'], candidate_id=ident,
                  operator=operator, warning='AI semantics and automatic observations require review')
    handler.send_json(201, {'state': state, 'object_id': object_id,
                            'warning': '候选尚未验证；请检查照片、尺度和模型。'})


def accept_revision(handler, body: dict) -> None:
    """Apply a user-accepted AI proposal only to the exact model it inspected."""
    server = handler.server;job = server.agent_job
    if not job or job['id'] != body.get('job_id') or job['status'] not in {'COMPLETED', 'COMPLETED_NO_SOLVED_CANDIDATE'}:
        raise ValueError('Agent 任务不可用或尚未完成')
    ident = body.get('proposal_id')
    if not isinstance(ident, str) or not re.fullmatch(r'revision-proposal-[0-9a-f]{32}', ident):
        raise ValueError('修改建议编号无效')
    proposal = read_json(job['output'] / (ident + '.json'))
    if (proposal.get('id') != ident or proposal.get('status') != 'AI_PROPOSED_UNVERIFIED' or
        proposal.get('provider') != 'codex-cli:' + server.agent_settings['model']):
        raise ValueError('修改建议来源与本次任务不一致')
    model = server.model;state = (server.project or {}).get('general_modeler')
    if (not model or proposal.get('project_id') != model['project_id'] or
        body.get('revision') != model['revision'] or proposal.get('source_model_revision') != model['revision'] or
        proposal.get('source_model_sha256') != digest(model) or (state and state.get('model_dirty'))):
        raise ValueError('模型或照片观察已改变；请重新生成修改建议')
    from .modeling_tools import compare_revisions, update_element
    from .room_cli import save_version
    revised, diff = update_element(model, proposal['element_id'], proposal['attribute'], proposal['value'],
                                   reason=proposal['reason'], operator='analyst')
    if diff != proposal['diff']:raise ValueError('修改影响范围已改变；请重新检查')
    evidence = revised['evidence'][-1]
    evidence.update(kind='agent_proposed_revision', provider=proposal['provider'], proposal_id=ident,
                    confirmation='accepted_unverified')
    target = server.workspace / f"revision-{revised['revision']:03}"
    save_version(revised, target, diff=diff)
    server.model, server.model_dir = revised, target
    server.project['current_revision'] = revised['revision']
    operator = 'automation_accepted_unverified' if server.project.get('operator_kind') == 'automation' else 'user_accepted_unverified'
    server.record('agent_revision_accepted', proposal_id=ident, job_id=job['id'], operator=operator,
                  warning='Agent proposal accepted; independent validation remains required')
    handler.send_json(200, {'model': revised, 'diff': diff, 'comparison': compare_revisions(model, revised)})
