"""Synthetic safety and provenance tests; not a real room or human acceptance."""
import copy
import hashlib
import io
import json

from PIL import Image
import pytest

from products.worldstate_bim.agent_tools import AgentTools
from products.worldstate_bim.tests.test_general_modeler import fixture


def make_workspace(tmp_path):
    workspace = tmp_path / 'source';evidence = workspace / 'evidence';evidence.mkdir(parents=True)
    output = tmp_path / 'output';output.mkdir()
    data = fixture();cameras = copy.deepcopy(data['cameras']);uploads = []
    for camera, color in zip(cameras, ('red', 'green', 'blue')):
        image = Image.new('RGB', (640, 480), color);buffer = io.BytesIO();image.save(buffer, format='JPEG')
        raw = buffer.getvalue();sha = hashlib.sha256(raw).hexdigest();camera['sha256'] = sha
        (evidence / (sha + '.jpg')).write_bytes(raw)
        uploads.append({'id': 'upload-' + sha[:16], 'sha256': sha, 'extension': '.jpg',
                        'mime': 'image/jpeg', 'width': 640, 'height': 480})
    tracks = []
    for index, feature in enumerate(('a', 'b', 'c', 'd'), 1):
        tracks.append({'id': index, 'observations': [
            {'image_id': o['image_id'], 'pixel_xy': o['pixel_xy']}
            for o in data['observations'] if o['object_id'] == 'west' and o['feature_id'] == feature]})
    track_path = workspace / 'modeler-tracks.json';track_path.write_text(json.dumps({'tracks': tracks}))
    state = {'revision': 4, 'camera_mode': 'SYNTHETIC', 'cameras': cameras, 'objects': [],
             'observations': [], 'object_constraints': [], 'suggestions': [], 'model_dirty': False, 'solution': None,
             'source_reconstruction': [{'kind': 'synthetic'}],
             'track_sha256': hashlib.sha256(track_path.read_bytes()).hexdigest()}
    project = {'schema': 'worldstate-photo-project/0.1', 'id': 'synthetic-project', 'name': 'synthetic',
               'operator_kind': 'automation', 'current_revision': None, 'events': [], 'general_modeler': state}
    (workspace / 'photo-project.json').write_text(json.dumps(project))
    (workspace / 'evidence-index.json').write_text(json.dumps({'schema': 'worldstate-studio-evidence/0.1', 'uploads': uploads}))
    return workspace, output


def hypothesis(tools):
    return tools.record_hypothesis({'label': 'wall', 'description': 'synthetic wall candidate',
        'uncertainty': 'synthetic, not human-confirmed',
        'views': [{'image_id': i, 'bbox_normalized': [0, 0, 1, 1]} for i in (1, 2, 3)]})


def test_agent_evidence_and_deterministic_solve_do_not_mutate_source(tmp_path):
    workspace, output = make_workspace(tmp_path)
    before = (workspace / 'photo-project.json').read_bytes()
    tools = AgentTools(workspace, output, 'synthetic-test-model')
    proposal = hypothesis(tools)
    assert proposal['status'] == 'AI_SUGGESTED_UNVERIFIED'
    assert proposal['views'][0]['photo_sha256'] == tools.cameras[1]['sha256']
    observation = tools.record_image_observation({'hypothesis_id': proposal['id'], 'image_id': 1,
        'kind': 'line', 'points_normalized': [[.1, .2], [.8, .2]],
        'feature_ids': ['p1', 'p2'], 'sigma_px': 5.,
        'description': 'unconfirmed edge', 'uncertainty': 'several pixels'})
    assert observation['origin'] == 'ai_suggested' and observation['confirmation'] == 'proposed'
    assert len(tools.find_tracks({'image_a': 1, 'image_b': 2})['tracks']) == 4
    result = tools.solve_surface({'hypothesis_id': proposal['id'], 'track_ids': [1, 2, 3, 4],
        'image_ids': [1, 2, 3], 'reason': 'synthetic tracks', 'uncertainty': 'not a real scene'})
    assert result['scale_status'] == 'UNKNOWN' and result['solution']['optimization']['point_max_px'] < 1e-5
    saved = tools.candidate(result['candidate_id'])
    assert all(o['origin'] == 'deterministic' and o['confirmation'] == 'automation_unverified'
               for o in saved['data']['observations'])
    assert saved['agent_hypothesis']['provider'] == 'synthetic-test-model'
    assert (workspace / 'photo-project.json').read_bytes() == before
    with pytest.raises(ValueError, match='operator-provided scale'):
        tools.compile_ifc({'candidate_id': result['candidate_id']})


def test_agent_compile_requires_operator_assumptions_and_preserves_provenance(tmp_path):
    import ifcopenshell
    workspace, output = make_workspace(tmp_path);tools = AgentTools(workspace, output, 'synthetic-test-model')
    proposal = hypothesis(tools)
    result = tools.solve_surface({'hypothesis_id': proposal['id'], 'track_ids': [1, 2, 3, 4],
        'image_ids': [1, 2, 3], 'reason': 'synthetic tracks', 'uncertainty': 'synthetic'})
    config = tmp_path / 'assumptions.json';config.write_text(json.dumps({'operator_confirmed': True,
        'scale': {'basis': 'assumed', 'metres_per_source_unit': 1.}, 'thickness_m': .1,
        'up_source': [0, -1, 0], 'allow_rectangular_approximation': True}))
    tools = AgentTools(workspace, output, 'synthetic-test-model', config)
    draft = tools.compile_ifc({'candidate_id': result['candidate_id']})
    assert draft['status'] == 'UNVERIFIED_IFC_DRAFT' and draft['scale']['independent_measurement'] is False
    assert len(ifcopenshell.open(str(output / draft['ifc_file'])).by_type('IfcWall')) == 1
    model = json.loads((output / draft['ir_file']).read_text())
    assert any(e['kind'] == 'ai_semantic_hypothesis' for e in model['evidence'])


def test_agent_rejects_tampered_source_and_stale_hypothesis(tmp_path):
    workspace, output = make_workspace(tmp_path);tools = AgentTools(workspace, output, 'synthetic-test-model')
    proposal = hypothesis(tools)
    project_path = workspace / 'photo-project.json';project = json.loads(project_path.read_text())
    project['general_modeler']['revision'] += 1;project_path.write_text(json.dumps(project))
    with pytest.raises(ValueError, match='different modeler revision'):
        AgentTools(workspace, output).hypothesis(proposal['id'])
    camera = tools.cameras[1];(workspace / 'evidence' / (camera['sha256'] + '.jpg')).write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash mismatch'):
        tools.view_photo({'image_id': 1})


def test_agent_photo_scope_and_ai_observations_keep_machine_origin(tmp_path):
    workspace, output = make_workspace(tmp_path)
    tools = AgentTools(workspace, output, 'synthetic-test-model', allowed_images={1, 2})
    with pytest.raises(ValueError, match='not authorized'):
        tools.view_photo({'image_id': 3})
    proposal = tools.record_hypothesis({'label': 'wall', 'description': 'synthetic wall',
        'uncertainty': 'synthetic', 'views': [{'image_id': i, 'bbox_normalized': [0, 0, 1, 1]} for i in (1, 2)]})
    tracks = tools.tracks();ids = []
    for track in tracks:
        for item in track['observations']:
            if item['image_id'] not in (1, 2):continue
            x, y = item['pixel_xy']
            result = tools.record_image_observation({'hypothesis_id': proposal['id'], 'image_id': item['image_id'],
                'kind': 'point', 'points_normalized': [[x/640, y/480]], 'feature_ids': [f"p{track['id']}"],
                'sigma_px': 1., 'description': 'synthetic pixel', 'uncertainty': 'synthetic only'})
            ids.append(result['id'])
    solved = tools.solve_observations({'hypothesis_id': proposal['id'], 'observation_ids': ids,
                                       'reason': 'synthetic correspondence', 'uncertainty': 'not human confirmed'})
    candidate = tools.candidate(solved['candidate_id'])
    assert all(o['origin'] == 'ai_suggested' and o['confirmation'] == 'automation_unverified'
               for o in candidate['data']['observations'])


def test_studio_agent_requires_consent_and_imports_only_verified_machine_evidence(tmp_path):
    import threading
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    workspace, output = make_workspace(tmp_path);tools = AgentTools(workspace, output, 'codex-cli:synthetic')
    proposal = hypothesis(tools)
    result = tools.solve_surface({'hypothesis_id': proposal['id'], 'track_ids': [1, 2, 3, 4],
        'image_ids': [1, 2, 3], 'reason': 'synthetic tracks', 'uncertainty': 'synthetic only'})
    settings = {'model': 'synthetic', 'output_root': tmp_path, 'codex': 'unused', 'node': 'unused', 'timeout': 1}
    server = StudioServer(0, None, workspace, agent_settings=settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    try:
        assert api(server, '/api/agent/status')[1]['enabled'] is True
        assert api(server, '/api/agent/start', {'goal': 'test', 'image_ids': [1, 2]})[0] == 400
        server.agent_job = {'id': 'agent-' + 'a'*32, 'status': 'COMPLETED', 'source_revision': 4,
                            'image_ids': [1, 2, 3], 'output': output, 'candidates': [result['candidate_id']]}
        request = {'job_id': server.agent_job['id'], 'candidate_id': result['candidate_id'], 'state_revision': 3}
        assert api(server, '/api/agent/accept', request)[0] == 400
        request['state_revision'] = 4
        status, response = api(server, '/api/agent/accept', request);assert status == 201
        state = response['state'];assert state['revision'] == 5 and state['model_dirty'] is True
        assert state['objects'][0]['agent_hypothesis']['status'] == 'AI_SUGGESTED_UNVERIFIED'
        assert server.project['events'][-1]['operator'] == 'automation_accepted_unverified'
        assert all(o['origin'] == 'deterministic' and o['confirmation'] == 'automation_unverified'
                   for o in state['observations'])
        assert api(server, '/api/agent/accept', request)[0] == 400
    finally:
        server.shutdown();server.server_close();thread.join()


def test_studio_agent_revision_requires_matching_model_and_keeps_ifc_identity(tmp_path):
    import shutil
    import threading
    import ifcopenshell
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    workspace, output = make_workspace(tmp_path);tools = AgentTools(workspace, output, 'codex-cli:synthetic')
    proposal = hypothesis(tools)
    solved = tools.solve_surface({'hypothesis_id': proposal['id'], 'track_ids': [1, 2, 3, 4],
        'image_ids': [1, 2, 3], 'reason': 'synthetic tracks', 'uncertainty': 'synthetic'})
    config = tmp_path / 'assumptions.json';config.write_text(json.dumps({'operator_confirmed': True,
        'scale': {'basis': 'assumed', 'metres_per_source_unit': 1.}, 'thickness_m': .1,
        'up_source': [0, -1, 0], 'allow_rectangular_approximation': True}))
    draft = AgentTools(workspace, output, 'codex-cli:synthetic', config).compile_ifc({'candidate_id': solved['candidate_id']})
    directory = workspace / 'revision-001';directory.mkdir()
    shutil.copyfile(output / draft['ir_file'], directory / 'model.json');shutil.copyfile(output / draft['ifc_file'], directory / 'model.ifc')
    project_path = workspace / 'photo-project.json';project = json.loads(project_path.read_text())
    project['current_revision'] = 1;project_path.write_text(json.dumps(project))
    tools = AgentTools(workspace, output, 'codex-cli:synthetic')
    revision = tools.preview_revision({'element_id': 'agent-candidate', 'attribute': 'height',
                                       'value': 1.2, 'reason': 'synthetic agent suggestion'})
    settings = {'model': 'synthetic', 'output_root': tmp_path, 'codex': 'unused', 'node': 'unused', 'timeout': 1}
    server = StudioServer(0, None, workspace, agent_settings=settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    try:
        server.agent_job = {'id': 'agent-' + 'b'*32, 'status': 'COMPLETED', 'source_revision': 4,
                            'image_ids': [1, 2, 3], 'output': output, 'candidates': []}
        request = {'job_id': server.agent_job['id'], 'proposal_id': revision['id'], 'revision': 99}
        assert api(server, '/api/agent/accept-revision', request)[0] == 400
        request['revision'] = 1;status, response = api(server, '/api/agent/accept-revision', request)
        assert status == 200 and response['model']['revision'] == 2
        assert response['model']['evidence'][-1]['kind'] == 'agent_proposed_revision'
        assert response['model']['evidence'][-1]['confirmation'] == 'accepted_unverified'
        assert server.project['events'][-1]['operator'] == 'automation_accepted_unverified'
        before = ifcopenshell.open(str(directory / 'model.ifc')).by_type('IfcWall')[0].GlobalId
        after = ifcopenshell.open(str(workspace / 'revision-002' / 'model.ifc')).by_type('IfcWall')[0].GlobalId
        assert before == after
        assert api(server, '/api/agent/accept-revision', request)[0] == 400
    finally:
        server.shutdown();server.server_close();thread.join()


def test_agent_job_recovery_marks_interruption_without_retry(tmp_path):
    from products.worldstate_bim.studio_agent import persist_job
    from products.worldstate_bim.studio_server import StudioServer
    workspace, _ = make_workspace(tmp_path);root = tmp_path / 'jobs';root.mkdir()
    settings = {'model': 'synthetic', 'output_root': root, 'codex': 'unused', 'node': 'unused', 'timeout': 1}
    ident = 'agent-' + 'c'*32;directory = root / ident;directory.mkdir()
    first = StudioServer(0, None, workspace, agent_settings=settings)
    try:
        persist_job(first, {'id': ident, 'status': 'RUNNING', 'source_revision': 4, 'image_ids': [1, 2],
            'output': directory, 'result': '', 'candidates': [], 'error': None, 'started_at': '2026-11-16T00:00:00+00:00'})
    finally:first.server_close()
    second = StudioServer(0, None, workspace, agent_settings=settings)
    try:
        assert second.agent_job['status'] == 'INTERRUPTED'
        assert '未自动重试' in second.agent_job['error']
        assert json.loads((directory / 'job.json').read_text())['status'] == 'INTERRUPTED'
    finally:second.server_close()


def test_studio_agent_job_is_scoped_nonblocking_and_recoverable(tmp_path, monkeypatch):
    import threading
    import time
    import products.worldstate_bim.agent_runner as runner
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    workspace, _ = make_workspace(tmp_path);root = tmp_path / 'jobs';root.mkdir()
    settings = {'model': 'synthetic', 'output_root': root, 'codex': 'unused', 'node': 'unused', 'timeout': 1}
    entered, release = threading.Event(), threading.Event()
    def fake_run(**kwargs):
        assert kwargs['image_ids'] == [1, 2] and kwargs['workspace'] == workspace
        entered.set();assert release.wait(5)
        return {'status': 'COMPLETED_NO_SOLVED_CANDIDATE', 'result': 'synthetic only', 'candidates': []}
    monkeypatch.setattr(runner, 'run_codex_agent', fake_run)
    server = StudioServer(0, None, workspace, agent_settings=settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
    try:
        body = {'goal': 'synthetic task', 'image_ids': [1, 2], 'allow_external_images': True}
        code, response = api(server, '/api/agent/start', body);assert code == 202
        assert entered.wait(3) and response['job']['status'] == 'RUNNING'
        assert api(server, '/api/agent/start', body)[0] == 400
        assert api(server, '/api/modeler/state')[1]['state']['revision'] == 4
        release.set();deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = api(server, '/api/agent/status')[1]['job']
            if job['status'] != 'RUNNING':break
            time.sleep(.05)
        assert job['status'] == 'COMPLETED_NO_SOLVED_CANDIDATE'
        assert server.project['general_modeler']['revision'] == 4
    finally:
        release.set();server.shutdown();server.server_close();thread.join()
    recovered = StudioServer(0, None, workspace, agent_settings=settings)
    try:assert recovered.agent_job['status'] == 'COMPLETED_NO_SOLVED_CANDIDATE'
    finally:recovered.server_close()
