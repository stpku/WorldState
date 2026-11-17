"""Safety and provenance checks on synthetic fixtures, not user acceptance."""
import copy
import json

import pytest

from products.worldstate_bim.agent_tools import AgentTools
from products.worldstate_bim.room_ir import revise_element
from products.worldstate_bim.tests.test_agent_tools import make_workspace, hypothesis
from products.worldstate_bim.tests.test_room_ir import fixture as room_fixture
from products.worldstate_bim.view_recommendation import recommend_views


def test_wall_translation_propagates_shared_corners_and_refuses_constraint_conflicts():
    model=room_fixture();original=copy.deepcopy(model)
    with pytest.raises(ValueError,match='ANGULAR_CONSTRAINT_CONFLICT'):
        revise_element(model,'wall-1','position_x',.2,reason='synthetic translation',operator='analyst')
    assert model==original
    model['constraints']=[]
    revised,diff=revise_element(model,'wall-1','position_x',.2,reason='synthetic translation',operator='analyst')
    assert diff['before']==0 and diff['after']==pytest.approx(.2)
    assert {'wall-1','wall-2','wall-4','opening-1','door-1'} <= set(diff['affected_elements'])
    assert revised['nodes'][0]['x']==pytest.approx(.2) and revised['nodes'][1]['x']==pytest.approx(4.2)


def test_recommendation_is_object_based_and_does_not_claim_visibility(tmp_path):
    workspace,output=make_workspace(tmp_path);tools=AgentTools(workspace,output,'synthetic')
    h=hypothesis(tools);result=tools.solve_surface({'hypothesis_id':h['id'],'track_ids':[1,2,3,4],
        'image_ids':[1,2,3],'reason':'synthetic feature tracks','uncertainty':'synthetic'})
    candidate=tools.candidate(result['candidate_id']);state=tools.state
    state.update(objects=candidate['data']['objects'],observations=candidate['data']['observations'],
                 object_constraints=candidate['data']['object_constraints'],solution=candidate['solution'])
    ranked=recommend_views(workspace,state,list(tools.uploads.values()),'agent-candidate')
    assert ranked['status']=='UNVERIFIED_LOCAL_RECOMMENDATION' and ranked['pairs']
    assert all(x['occlusion']=='UNKNOWN' for x in ranked['views'])
    assert all(x['photo_sha256'] and x['camera_sha256'] for x in ranked['views'])
    assert recommend_views(workspace,state,list(tools.uploads.values()),'missing')['status']=='INSUFFICIENT_OBJECT_GEOMETRY'
    partial=copy.deepcopy(state);partial['solution']=None;partial['model_dirty']=True
    point_ranked=recommend_views(workspace,partial,list(tools.uploads.values()),'agent-candidate')
    assert point_ranked['status']=='UNVERIFIED_POINT_RECOMMENDATION'
    assert point_ranked['point_support']['status']=='MULTIVIEW_TRIANGULATED_CORRESPONDENCE_UNVERIFIED'
    assert all(v['projection_fraction'] is None and v['occlusion']=='UNKNOWN' for v in point_ranked['views'])
    state['model_dirty']=True
    assert recommend_views(workspace,state,list(tools.uploads.values()),'agent-candidate')['status']=='STALE_OBJECT_GEOMETRY'
    state['model_dirty']=False
    camera=tools.cameras[1];(workspace/'evidence'/(camera['sha256']+'.jpg')).write_bytes(b'tampered')
    ranked=recommend_views(workspace,state,list(tools.uploads.values()),'agent-candidate')
    assert ranked['status']=='SOURCE_EVIDENCE_UNAVAILABLE' and not ranked['views']
    assert '哈希不符' in ranked['warning']


def test_model_only_agent_cannot_access_unapproved_photo_and_requires_model_consent(tmp_path):
    import threading
    from products.worldstate_bim.room_ifc import export_room
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    workspace,output=make_workspace(tmp_path);project_path=workspace/'photo-project.json'
    project=json.loads(project_path.read_text());model=room_fixture();model['project_id']=project['id']
    project['current_revision']=1;project_path.write_text(json.dumps(project));directory=workspace/'revision-001';directory.mkdir()
    (directory/'model.json').write_text(json.dumps(model));export_room(model,directory/'model.ifc')
    tools=AgentTools(workspace,output,'synthetic',allowed_images=set())
    assert tools.inspect_scene({})['cameras']==[] and len(tools.inspect_scene({})['model_elements'])==8
    with pytest.raises(ValueError,match='not authorized'):
        tools.view_photo({'image_id':1})
    server=StudioServer(0,None,workspace,agent_settings={'model':'synthetic','output_root':tmp_path,'codex':'unused','node':'unused','timeout':1})
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        code,reply=api(server,'/api/agent/start',{'goal':'test','image_ids':[],'model_only':True})
        assert code==400 and '模型构件信息' in reply['error']
        code,reply=api(server,'/api/agent/start',{'goal':'test','image_ids':[1,2],'model_only':True,'allow_external_model':True})
        assert code==400
    finally:server.shutdown();server.server_close();thread.join()


def test_ai_point_suggestions_remain_unconfirmed_and_become_stale(tmp_path):
    import threading
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    workspace,output=make_workspace(tmp_path);tools=AgentTools(workspace,output,'codex-cli:synthetic',allowed_images={1,2})
    h=tools.record_hypothesis({'label':'wall','description':'synthetic','uncertainty':'unreviewed',
        'views':[{'image_id':i,'bbox_normalized':[0,0,1,1]} for i in (1,2)]})
    observation=tools.record_image_observation({'hypothesis_id':h['id'],'image_id':1,'kind':'point',
        'points_normalized':[[.25,.25]],'feature_ids':['p1'],'sigma_px':3.,'description':'synthetic','uncertainty':'unreviewed'})
    settings={'model':'synthetic','output_root':tmp_path,'codex':'unused','node':'unused','timeout':1}
    server=StudioServer(0,None,workspace,agent_settings=settings)
    server.agent_job={'id':'agent-'+'e'*32,'status':'COMPLETED','source_revision':4,'image_ids':[1,2],'output':output,'candidates':[]}
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        suggestion=api(server,'/api/agent/status')[1]['job']['observations'][0]
        assert suggestion['id']==observation['id'] and suggestion['confirmation']=='proposed' and not suggestion['stale']
        assert not server.project['general_modeler']['observations']
        server.project['general_modeler']['revision']+=1
        assert api(server,'/api/agent/status')[1]['job']['observations'][0]['stale']
    finally:server.shutdown();server.server_close();thread.join()


def test_projection_repair_binds_photos_and_persists_fit_provenance(tmp_path):
    import hashlib
    import io
    import threading
    from PIL import Image
    from products.worldstate_bim.model_first import build_local_wall_ir, solve_local_wall
    from products.worldstate_bim.room_ifc import export_room
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_model_first import scene
    from products.worldstate_bim.tests.test_studio_server import api
    data,_=scene();workspace=tmp_path/'source';(workspace/'evidence').mkdir(parents=True);output=tmp_path/'out';output.mkdir()
    uploads=[]
    for c,color in zip(data['cameras'],('red','green','blue')):
        buf=io.BytesIO();Image.new('RGB',(640,480),color).save(buf,format='JPEG');raw=buf.getvalue()
        digest=hashlib.sha256(raw).hexdigest();c['sha256']=digest;(workspace/'evidence'/(digest+'.jpg')).write_bytes(raw)
        uploads.append({'id':'upload-'+digest[:16],'sha256':digest,'extension':'.jpg','mime':'image/jpeg','width':640,'height':480})
    lookup={c['image_id']:c['sha256'] for c in data['cameras']}
    for group in data['corners'].values():
        for o in group:o['photo_sha256']=lookup[o['image_id']]
    for o in data['ceiling_lines']:o['photo_sha256']=lookup[o['image_id']]
    solution=solve_local_wall(data);model=build_local_wall_ir(data,solution,project_id='synthetic-photo-patch',
        assumed_scale=1.,assumed_thickness_m=.1,allow_assumed=True)
    original_height=model['elements'][0]['parameters']['height']['value']
    model,_=revise_element(model,'wall-above-opening','height',original_height+.1,reason='controlled synthetic perturbation',operator='automation')
    rev=workspace/'revision-002';rev.mkdir();(rev/'model.json').write_text(json.dumps(model));export_room(model,rev/'model.ifc')
    state={'revision':1,'camera_mode':'known-pose','cameras':data['cameras'],'objects':[],'model_dirty':False}
    project={'schema':'worldstate-photo-project/0.1','id':model['project_id'],'name':'synthetic',
             'operator_kind':'automation','current_revision':2,'general_modeler':state,'events':[]}
    (workspace/'photo-project.json').write_text(json.dumps(project));(workspace/'evidence-index.json').write_text(json.dumps({'schema':'worldstate-studio-evidence/0.1','uploads':uploads}))
    tools=AgentTools(workspace,output,'codex-cli:synthetic',allowed_images={1,2})
    proposal=tools.preview_projection_repair({'element_id':'wall-above-opening','reason':'synthetic observation fit'})
    assert proposal['projection_evidence']['after_line_rms_px']<1e-4
    server=StudioServer(0,None,workspace,agent_settings={'model':'synthetic','output_root':tmp_path,'codex':'unused','node':'unused','timeout':1})
    server.agent_job={'id':'agent-'+'c'*32,'status':'COMPLETED','source_revision':1,'image_ids':[1,2],'output':output,'candidates':[]}
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        request={'job_id':server.agent_job['id'],'proposal_id':proposal['id'],'revision':2}
        photo=workspace/'evidence'/(lookup[1]+'.jpg');raw=photo.read_bytes();photo.write_bytes(b'tampered')
        assert api(server,'/api/agent/accept-revision',request)[0]==400
        assert server.model['revision']==2;photo.write_bytes(raw)
        code,reply=api(server,'/api/agent/accept-revision',request)
        assert code==200 and reply['model']['revision']==3
        assert reply['model']['evidence'][-1]['projection_evidence']['views']==proposal['projection_evidence']['views']
    finally:server.shutdown();server.server_close();thread.join()


def test_batch_proposals_recompute_atomically_and_reject_stale_or_invalid(tmp_path):
    import threading
    import ifcopenshell
    from benchmarks.ws_agent.run import setup
    from examples.bim_synthetic_room_round3.generate import synthetic_room
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    workspace,model=setup(tmp_path/'task',synthetic_room(),{})
    output=tmp_path/'agent';output.mkdir()
    tools=AgentTools(workspace,output,'codex-cli:synthetic',allowed_images=set())
    first=tools.preview_revision({'element_id':'wall-2','attribute':'height','value':2.9,'reason':'synthetic batch'})
    second=tools.preview_revision({'element_id':'opening-door','attribute':'offset','value':1.2,'reason':'synthetic batch'})
    settings={'model':'synthetic','output_root':tmp_path,'codex':'unused','node':'unused','timeout':1}
    server=StudioServer(0,None,workspace,agent_settings=settings)
    server.agent_job={'id':'agent-'+'d'*32,'status':'COMPLETED','source_revision':0,'image_ids':[],'output':output,'candidates':[]}
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        request={'job_id':server.agent_job['id'],'proposal_ids':[first['id'],second['id']],'revision':1}
        code,preview=api(server,'/api/agent/preview-batch',request)
        assert code==200 and [x['after'] for x in preview['steps']]==[2.9,1.2]
        assert server.model['revision']==1 and not (workspace/'revision-002').exists()
        assert api(server,'/api/agent/accept-batch',{**request,'batch_sha256':preview['batch_sha256']})[0]==400
        assert api(server,'/api/agent/accept-batch',{**request,'batch_sha256':'invalid','confirmed':True})[0]==400
        # A proposal changed after preview must invalidate the approval digest.
        path=output/(second['id']+'.json');saved=path.read_text();modified=json.loads(saved);modified['value']=1.25;path.write_text(json.dumps(modified))
        assert api(server,'/api/agent/accept-batch',{**request,'batch_sha256':preview['batch_sha256'],'confirmed':True})[0]==400
        modified=json.loads(saved);modified['reason']='changed after preview';path.write_text(json.dumps(modified))
        assert api(server,'/api/agent/accept-batch',{**request,'batch_sha256':preview['batch_sha256'],'confirmed':True})[0]==400
        path.write_text(saved)
        assert api(server,'/api/agent/accept-batch',{**request,'batch_sha256':preview['batch_sha256'],'confirmed':True},authorized=False)[0]==403
        code,result=api(server,'/api/agent/accept-batch',{**request,'batch_sha256':preview['batch_sha256'],'confirmed':True})
        assert code==200 and result['model']['revision']==3
        assert (workspace/'revision-002'/'model.ifc').is_file() and (workspace/'revision-003'/'model.ifc').is_file()
        revised=result['model'];assert next(e for e in revised['elements'] if e['id']=='wall-2')['parameters']['height']['value']==2.9
        assert next(e for e in revised['elements'] if e['id']=='opening-door')['parameters']['offset']['value']==1.2
        assert api(server,'/api/agent/accept-batch',{**request,'batch_sha256':preview['batch_sha256'],'confirmed':True})[0]==400
        before=ifcopenshell.open(str(workspace/'revision-001'/'model.ifc'));after=ifcopenshell.open(str(workspace/'revision-003'/'model.ifc'))
        assert {e.GlobalId for e in before.by_type('IfcProduct')}=={e.GlobalId for e in after.by_type('IfcProduct')}
        assert len(after.by_type('IfcDoor'))==1 and len(after.by_type('IfcRelVoidsElement'))==2
    finally:server.shutdown();server.server_close();thread.join()


def test_batch_io_failure_does_not_advance_current_model(tmp_path,monkeypatch):
    import threading
    from benchmarks.ws_agent.run import setup
    from examples.bim_synthetic_room_round3.generate import synthetic_room
    from products.worldstate_bim import studio_agent
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    workspace,_=setup(tmp_path/'task',synthetic_room(),{});output=tmp_path/'agent';output.mkdir()
    tools=AgentTools(workspace,output,'codex-cli:synthetic',allowed_images=set())
    first=tools.preview_revision({'element_id':'wall-2','attribute':'height','value':2.9,'reason':'synthetic batch'})
    second=tools.preview_revision({'element_id':'opening-door','attribute':'offset','value':1.2,'reason':'synthetic batch'})
    server=StudioServer(0,None,workspace,agent_settings={'model':'synthetic','output_root':tmp_path,'codex':'unused','node':'unused','timeout':1})
    server.agent_job={'id':'agent-'+'e'*32,'status':'COMPLETED','source_revision':0,'image_ids':[],'output':output,'candidates':[]}
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        request={'job_id':server.agent_job['id'],'proposal_ids':[first['id'],second['id']],'revision':1}
        preview=api(server,'/api/agent/preview-batch',request)[1]
        def failed_link(*args,**kwargs):raise OSError('injected failure')
        monkeypatch.setattr(studio_agent.os,'link',failed_link)
        code,response=api(server,'/api/agent/accept-batch',{**request,'batch_sha256':preview['batch_sha256'],'confirmed':True})
        assert code==400 and '当前模型未更新' in response['error']
        assert server.model['revision']==1 and json.loads((workspace/'photo-project.json').read_text())['current_revision']==1
    finally:server.shutdown();server.server_close();thread.join()
