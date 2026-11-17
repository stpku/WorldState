"""Scoped Studio integration for a single optional Codex modeling run."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import tempfile
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
    observations=[]
    state=(server.project or {}).get('general_modeler') or {}
    cameras={c['image_id']:c for c in state.get('cameras',[])}
    for path in sorted(job['output'].glob('observation-*.json'))[:200]:
        if not re.fullmatch(r'observation-[0-9a-f]{32}\.json',path.name):continue
        try:
            item=read_json(path);camera=cameras.get(item.get('image_id'))
            if (item.get('origin')!='ai_suggested' or item.get('confirmation')!='proposed' or
                item.get('image_id') not in job['image_ids'] or not camera or
                item.get('photo_sha256')!=camera['sha256'] or item.get('camera_sha256')!=camera_digest(camera)):
                raise ValueError('unauthorized or stale AI observation')
            item['stale']=state.get('revision')!=job.get('source_revision')
            observations.append(item)
        except (ValueError, KeyError, OSError, TypeError):artifact_errors.append(path.stem)
    revisions = []
    for path in sorted(job['output'].glob('revision-proposal-*.json'))[:20]:
        if not re.fullmatch(r'revision-proposal-[0-9a-f]{32}\.json', path.name):continue
        try:
            item = read_json(path)
            if item.get('status') != 'AI_PROPOSED_UNVERIFIED':raise ValueError('invalid revision proposal')
            revisions.append(item)
        except (ValueError, KeyError, OSError, TypeError):artifact_errors.append(path.stem)
    restores=[];designs=[]
    for prefix,expected,destination in (('restore-proposal-','AI_RESTORE_PROPOSED_UNVERIFIED',restores),
                                        ('design-proposal-','AI_SIMULATED_DESIGN_PROPOSED',designs)):
        for path in sorted(job['output'].glob(prefix+'*.json'))[:20]:
            if not re.fullmatch(prefix+r'[0-9a-f]{32}\.json',path.name):continue
            try:
                item=read_json(path)
                if item.get('id')!=path.stem or item.get('status')!=expected:raise ValueError('invalid proposal')
                destination.append(item)
            except (ValueError,KeyError,OSError,TypeError):artifact_errors.append(path.stem)
    public.update(events=events, hypotheses=hypotheses, observations=observations, revision_proposals=revisions,
                  restore_proposals=restores,design_proposals=designs,
                  artifact_errors=artifact_errors);result['job'] = public
    return result


def start(handler, body: dict) -> None:
    server = handler.server;settings = server.agent_settings
    if settings is None:raise ValueError('未配置多模态建模 Agent；当前仍为本地规则模式')
    if server.project is None:raise ValueError('请先在隔离工作区打开或创建项目')
    model_only = body.get('model_only') is True;author_only=body.get('author_only') is True
    if model_only and author_only:raise ValueError('请选择一种 Agent 工作模式')
    if author_only and body.get('allow_external_text') is not True:
        raise ValueError('请先明确同意将建模文字发送至已配置模型')
    if model_only and body.get('allow_external_model') is not True:
        raise ValueError('请先明确同意将模型构件信息发送至已配置模型')
    if not model_only and not author_only and body.get('allow_external_images') is not True:
        raise ValueError('请先明确同意将选定照片发送至已配置模型')
    goal, images, selected = body.get('goal'), body.get('image_ids'), body.get('selected_id')
    if (not isinstance(goal, str) or not goal.strip() or len(goal) > 1000 or
        not isinstance(images, list) or not ((model_only or author_only) and not images or 2 <= len(images) <= 8) or
        any(isinstance(i, bool) or not isinstance(i, int) for i in images) or len(set(images)) != len(images)):
        raise ValueError('请输入任务并选择 2–8 张不同的已注册照片')
    state = (server.project or {}).get('general_modeler')
    if model_only and (images or not server.model):
        raise ValueError('仅模型模式需要已保存模型，且不能发送照片')
    if author_only and (images or server.model or server.project.get('current_revision')):
        raise ValueError('文字新建需要没有模型的项目，且不能发送照片')
    if not model_only and not author_only and (not state or not set(images) <= {c['image_id'] for c in state['cameras']}):
        raise ValueError('所选照片未注册到当前项目')
    known = {o['id'] for o in (state or {}).get('objects', [])} | {e['id'] for e in (server.model or {}).get('elements', [])}
    if selected is not None and (not isinstance(selected, str) or selected not in known):
        raise ValueError('选中构件不属于当前项目')
    if server.agent_job and server.agent_job['status'] == 'RUNNING':
        raise ValueError('已有 Agent 任务正在运行')
    ident = 'agent-' + uuid.uuid4().hex
    output = settings['output_root'] / ident
    output.mkdir(mode=0o700)
    job = {'id': ident, 'status': 'RUNNING', 'source_revision': state['revision'] if state else 0,
           'image_ids': list(images), 'selected_id': selected, 'output': output, 'result': '', 'candidates': [], 'error': None,
           'started_at': datetime.now(timezone.utc).isoformat()}
    persist_job(server, job)
    server.agent_job = job

    def worker() -> None:
        try:
            from .agent_runner import run_codex_agent
            result = run_codex_agent(workspace=server.workspace, output=output, image_ids=images, goal=goal,
                codex=settings['codex'], node=settings['node'], model=settings['model'],
                timeout=settings['timeout'], selected_id=selected, model_only=model_only,author_only=author_only)
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
            if (not match or match['pixel_xy'] != observation.get('pixel_xy') or
                (state.get('track_source') and observation.get('track_source') != state['track_source'])):
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
    if proposal.get('projection_evidence'):
        tools=AgentTools(server.workspace,job['output'],'studio-agent',allowed_images=set(job['image_ids']))
        views=proposal['projection_evidence'].get('views', [])
        if (not isinstance(views,list) or len(views)<2 or any(not isinstance(v,dict) for v in views) or
            len({v.get('image_id') for v in views})!=len(views)):
            raise ValueError('修订缺少独立视角的原始证据')
        for view in views:
            camera=tools.camera(view['image_id']);tools.photo(camera)
            if camera['sha256']!=view['photo_sha256'] or camera_digest(camera)!=view['camera_sha256']:
                raise ValueError('修订所用照片或相机版本已改变')
    from .modeling_tools import compare_revisions, update_element
    from .room_cli import save_version
    revised, diff = update_element(model, proposal['element_id'], proposal['attribute'], proposal['value'],
                                   reason=proposal['reason'], operator='analyst')
    if diff != proposal['diff']:raise ValueError('修改影响范围已改变；请重新检查')
    evidence = revised['evidence'][-1]
    evidence.update(kind='agent_proposed_revision', provider=proposal['provider'], proposal_id=ident,
                    confirmation='accepted_unverified')
    if proposal.get('projection_evidence'):
        evidence['projection_evidence']=copy.deepcopy(proposal['projection_evidence'])
    target = server.workspace / f"revision-{revised['revision']:03}"
    save_version(revised, target, diff=diff)
    server.model, server.model_dir = revised, target
    server.project['current_revision'] = revised['revision']
    operator = 'automation_accepted_unverified' if server.project.get('operator_kind') == 'automation' else 'user_accepted_unverified'
    server.record('agent_revision_accepted', proposal_id=ident, job_id=job['id'], operator=operator,
                  warning='Agent proposal accepted; independent validation remains required')
    handler.send_json(200, {'model': revised, 'diff': diff, 'comparison': compare_revisions(model, revised)})


def _checked_batch(server, body: dict) -> tuple[dict, list[tuple[dict, dict, dict]]]:
    """Recompute an ordered set of proposals without modifying the workspace."""
    from .modeling_tools import compare_revisions, update_element, validate_geometry
    job=server.agent_job;model=server.model;state=(server.project or {}).get('general_modeler')
    if not job or job['id']!=body.get('job_id') or job['status'] not in {'COMPLETED','COMPLETED_NO_SOLVED_CANDIDATE'}:
        raise ValueError('Agent 任务不可用或尚未完成')
    ids=body.get('proposal_ids')
    if (not isinstance(ids,list) or not 2<=len(ids)<=8 or
        any(not isinstance(x,str) or not re.fullmatch(r'revision-proposal-[0-9a-f]{32}',x) for x in ids) or
        len(set(ids))!=len(ids)):
        raise ValueError('请选择 2–8 项不同的修改建议')
    if not model or body.get('revision')!=model['revision'] or (state and state.get('model_dirty')):
        raise ValueError('模型或照片观察已改变；请重新生成修改建议')
    source_hash=digest(model);current=copy.deepcopy(model);steps=[];preview=[]
    for ident in ids:
        proposal=read_json(job['output']/(ident+'.json'))
        if (proposal.get('id')!=ident or proposal.get('status')!='AI_PROPOSED_UNVERIFIED' or
            proposal.get('provider')!='codex-cli:'+server.agent_settings['model'] or
            proposal.get('project_id')!=model['project_id'] or proposal.get('source_model_revision')!=model['revision'] or
            proposal.get('source_model_sha256')!=source_hash or proposal.get('projection_evidence')):
            raise ValueError('建议来源不符、已过期或需要单独核验照片证据')
        current,diff=update_element(current,proposal['element_id'],proposal['attribute'],proposal['value'],
                                    reason=proposal['reason'],operator='analyst')
        current['evidence'][-1].update(kind='agent_proposed_revision',provider=proposal['provider'],proposal_id=ident,
                                       confirmation='accepted_unverified')
        steps.append((copy.deepcopy(current),diff,proposal))
        preview.append({'proposal_id':ident,'element_id':proposal['element_id'],'attribute':proposal['attribute'],
                        'before':diff['before'],'after':diff['after'],'affected_elements':diff['affected_elements'],
                        'reason':proposal['reason'],'validation':validate_geometry(current)})
    signature=digest({'source_model_sha256':source_hash,'steps':preview})
    return {'revision':model['revision'],'batch_sha256':signature,'steps':preview,
            'comparison':compare_revisions(model,current),
            'warning':'顺序重新计算；墙轴提示不是完整三维实体碰撞检查。'},steps


def preview_batch(handler, body: dict) -> None:
    preview,_=_checked_batch(handler.server,body)
    handler.send_json(200,preview)


def accept_batch(handler, body: dict) -> None:
    """Save all validated steps before advancing the current project version."""
    if body.get('confirmed') is not True:raise ValueError('请先明确确认批量修改预览')
    server=handler.server;preview,steps=_checked_batch(server,body)
    if body.get('batch_sha256')!=preview['batch_sha256']:
        raise ValueError('批量预览已失效；请重新检查并确认')
    from .room_cli import save_version
    targets=[server.workspace/f"revision-{model['revision']:03}" for model,_,_ in steps]
    if any(path.exists() or path.is_symlink() for path in targets):
        raise ValueError('目标版本目录已存在；未应用任何修改')
    # Stage first. Final directories are created exclusively, and each file is
    # linked without overwriting existing paths. An interrupted save can leave
    # an orphan directory, but never advances the project to a partial batch.
    with tempfile.TemporaryDirectory(prefix='.ws-batch-',dir=server.workspace) as temp:
        staged=[]
        for model,diff,_ in steps:
            path=Path(temp)/f"revision-{model['revision']:03}";save_version(model,path,diff=diff);staged.append(path)
        try:
            for source,target in zip(staged,targets):
                target.mkdir(mode=0o700)
                for item in source.iterdir():os.link(item,target/item.name)
        except OSError as exc:
            raise ValueError('批量保存中断，当前模型未更新；请检查新建的版本目录') from exc
    server.model,server.model_dir=steps[-1][0],targets[-1]
    server.project['current_revision']=server.model['revision']
    operator='automation_accepted_unverified' if server.project.get('operator_kind')=='automation' else 'user_accepted_unverified'
    server.record('agent_batch_revision_accepted',proposal_ids=body['proposal_ids'],job_id=server.agent_job['id'],
                  operator=operator,warning='Ordered batch accepted; independent validation remains required')
    handler.send_json(200,{'model':server.model,'steps':preview['steps'],'comparison':preview['comparison']})


def _ready_job(server,body:dict) -> dict:
    job=server.agent_job
    if not job or job['id']!=body.get('job_id') or job['status'] not in {'COMPLETED','COMPLETED_NO_SOLVED_CANDIDATE'}:
        raise ValueError('Agent 任务不可用或尚未完成')
    if body.get('confirmed') is not True:raise ValueError('请先明确确认预览内容')
    return job


def accept_restore(handler,body:dict) -> None:
    """Restore a verified proposal as a new immutable version after confirmation."""
    from .history_tools import restore_preview,restored_model
    from .room_cli import save_version
    server=handler.server;job=_ready_job(server,body);ident=body.get('proposal_id')
    if not isinstance(ident,str) or not re.fullmatch(r'restore-proposal-[0-9a-f]{32}',ident):raise ValueError('恢复建议编号无效')
    proposal=read_json(job['output']/(ident+'.json'));model=server.model;state=(server.project or {}).get('general_modeler')
    if (not model or proposal.get('id')!=ident or proposal.get('status')!='AI_RESTORE_PROPOSED_UNVERIFIED' or
        proposal.get('provider')!='codex-cli:'+server.agent_settings['model'] or proposal.get('project_id')!=model['project_id'] or
        proposal.get('source_model_revision')!=model['revision'] or body.get('revision')!=model['revision'] or
        proposal.get('source_model_sha256')!=digest(model) or (state and state.get('model_dirty'))):
        raise ValueError('模型或恢复建议已改变；请重新预览')
    previous,preview=restore_preview(server.workspace,model,proposal['target_revision'])
    if proposal.get('target_model_sha256')!=digest(previous) or proposal.get('preview')!=preview:
        raise ValueError('历史版本已改变；请重新预览')
    if preview['geometry_issues']:raise ValueError('历史版本存在几何冲突')
    restored=restored_model(model,previous);target=server.workspace/f"revision-{restored['revision']:03}"
    save_version(restored,target);server.model,server.model_dir=restored,target;server.project['current_revision']=restored['revision']
    operator='automation_accepted_unverified' if server.project.get('operator_kind')=='automation' else 'user_accepted_unverified'
    server.record('agent_restore_accepted',proposal_id=ident,job_id=job['id'],source_revision=previous['revision'],operator=operator)
    handler.send_json(200,{'model':restored,'preview':preview})


def accept_design(handler,body:dict) -> None:
    """Rebuild an explicitly confirmed simulated design without trusting IFC text."""
    from .room_cli import save_version
    from .text_author import build_design
    server=handler.server;job=_ready_job(server,body);ident=body.get('proposal_id')
    if not isinstance(ident,str) or not re.fullmatch(r'design-proposal-[0-9a-f]{32}',ident):raise ValueError('设计建议编号无效')
    proposal=read_json(job['output']/(ident+'.json'));project=server.project
    context={'project_id':project['id'],'current_revision':project.get('current_revision'),
             'general_modeler':project.get('general_modeler'),'uploads':sorted(x['sha256'] for x in server.uploaded)}
    if (server.model is not None or project.get('current_revision') or proposal.get('id')!=ident or
        proposal.get('status')!='AI_SIMULATED_DESIGN_PROPOSED' or proposal.get('project_id')!=project['id'] or
        proposal.get('provider')!='codex-cli:'+server.agent_settings['model'] or proposal.get('context_sha256')!=digest(context)):
        raise ValueError('项目或设计建议已改变，请重新生成')
    request=read_json(job['output']/'authorized-request.json')
    if request.get('project_id')!=project['id'] or proposal.get('request_sha256')!=digest(request):raise ValueError('建模文字已改变')
    model=build_design(proposal['spec'],project_id=project['id'],user_request=request['goal'])
    if proposal.get('model_sha256')!=digest(model):raise ValueError('设计候选与确定性模型不一致')
    target=server.workspace/'revision-001';save_version(model,target)
    server.model,server.model_dir=model,target;project['current_revision']=1
    operator='automation_accepted_unverified' if project.get('operator_kind')=='automation' else 'user_accepted_unverified'
    server.record('agent_design_accepted',proposal_id=ident,job_id=job['id'],operator=operator,
                  warning='Simulated design; not a real-world observation')
    handler.send_json(201,{'model':model,'warning':'设计/模拟模型，不代表现场观测。'})
