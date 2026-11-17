"""Synthetic authoring and restoration safety; no real-world accuracy claims."""
import copy
import json
import threading
import ifcopenshell
import pytest

from products.worldstate_bim.agent_tools import AgentTools
from products.worldstate_bim.room_ifc import export_room
from products.worldstate_bim.room_ir import revise_element
from products.worldstate_bim.text_author import SCHEMA_AUTHOR,build_design
from products.worldstate_bim.studio_server import StudioServer
from products.worldstate_bim.tests.test_studio_server import api
from benchmarks.ws_agent.run import setup
from examples.bim_synthetic_room_round3.generate import synthetic_room

TEXT='矩形房间长4米、宽3米、高2.8米、墙厚12厘米、楼板厚15厘米；wall-1门偏移1米、宽90厘米、高2.1米、底0米、板厚4厘米。'
SPEC={'schema':SCHEMA_AUTHOR,'shape':'rectangle','length_m':4.,'width_m':3.,'height_m':2.8,'wall_thickness_m':.12,'slab_thickness_m':.15,
      'openings':[{'kind':'door','wall':'wall-1','offset_m':1.,'width_m':.9,'height_m':2.1,'sill_m':0.,'panel_thickness_m':.04}], 'assumptions':{}}


def test_wall_endpoint_is_distinct_from_translation_and_checks_real_angles():
    original=synthetic_room()
    with pytest.raises(ValueError,match='ANGULAR_CONSTRAINT_CONFLICT'):
        revise_element(original,'wall-2','start_x',4.1,reason='test endpoint',operator='automation')
    assert next(n for n in original['nodes'] if n['id']=='n2')['x']==4.0
    translated,_=revise_element(original,'wall-2','position_x',4.1,reason='test translation',operator='automation')
    assert next(n for n in translated['nodes'] if n['id']=='n2')['x']==pytest.approx(4.1)
    assert next(n for n in translated['nodes'] if n['id']=='n3')['x']==pytest.approx(4.1)
    unconstrained=copy.deepcopy(original);unconstrained['constraints']=[]
    partial,_=revise_element(unconstrained,'wall-2','start_x',4.1,reason='test endpoint',operator='automation')
    assert next(n for n in partial['nodes'] if n['id']=='n2')['x']==pytest.approx(4.1)
    assert next(n for n in partial['nodes'] if n['id']=='n3')['x']==pytest.approx(4.0)


def test_text_design_compiles_real_semantic_ifc_and_keeps_simulated_provenance(tmp_path):
    model=build_design(SPEC,project_id='simulated-author',user_request=TEXT)
    assert all(e['classification']['status']=='simulated' for e in model['elements'])
    assert model['evidence'][0]['kind']=='text_design' and model['validation']['scope']=='SIMULATED_TEXT_TO_BIM'
    f=ifcopenshell.open(str(export_room(model,tmp_path/'design.ifc')))
    assert f.schema=='IFC4' and len(f.by_type('IfcWall'))==4 and len(f.by_type('IfcDoor'))==1
    assert len(f.by_type('IfcRelVoidsElement'))==len(f.by_type('IfcRelFillsElement'))==1


def test_missing_dimensions_invalid_openings_and_assumptions_are_not_silent():
    missing=copy.deepcopy(SPEC);missing['height_m']=3.4
    with pytest.raises(ValueError,match='not supported'):build_design(missing,project_id='simulated',user_request=TEXT)
    missing['assumptions']={'height_m':'height explicitly assumed for draft'}
    model=build_design(missing,project_id='simulated',user_request=TEXT)
    assert next(e for e in model['elements'] if e['id']=='wall-1')['parameters']['height']['status']=='assumed'
    bad=copy.deepcopy(SPEC);bad['openings'][0]['offset_m']=4.
    with pytest.raises(ValueError,match='OPENING_OUTSIDE_WALL'):build_design(bad,project_id='simulated',user_request=TEXT)
    l=copy.deepcopy(SPEC);l.update(shape='l_shape',notch_length_m=1.,notch_width_m=.9)
    with pytest.raises(ValueError,match='shape was not specified'):
        build_design(l,project_id='simulated',user_request=TEXT)
    lmodel=build_design(l,project_id='simulated',user_request='L形'+TEXT)
    assert len([e for e in lmodel['elements'] if e['ifc_type']=='IfcWall'])==6


def test_design_acceptance_requires_confirmation_and_unchanged_project(tmp_path):
    workspace=tmp_path/'source';output=tmp_path/'out';output.mkdir();server=StudioServer(0,None,workspace,
       agent_settings={'model':'synthetic','output_root':tmp_path,'codex':'unused','node':'unused','timeout':1})
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        code,project=api(server,'/api/project',{'name':'test design','operator_kind':'automation'});assert code==201
        request=output/'authorized-request.json';request.write_text(json.dumps({'project_id':project['id'],'goal':TEXT}))
        tools=AgentTools(workspace,output,'codex-cli:synthetic',allowed_images=set(),allow_empty=True,request_file=request)
        proposal=tools.preview_design({'spec':SPEC})
        server.agent_job={'id':'agent-'+'a'*32,'status':'COMPLETED','source_revision':0,'image_ids':[],'output':output,'candidates':[]}
        body={'job_id':server.agent_job['id'],'proposal_id':proposal['id']}
        assert api(server,'/api/agent/accept-design',body)[0]==400 and server.model is None
        assert api(server,'/api/agent/accept-design',{**body,'confirmed':True},authorized=False)[0]==403
        original=request.read_text();request.write_text(json.dumps({'project_id':project['id'],'goal':TEXT+' 5米'}))
        assert api(server,'/api/agent/accept-design',{**body,'confirmed':True})[0]==400
        request.write_text(original)
        code,reply=api(server,'/api/agent/accept-design',{**body,'confirmed':True});assert code==201
        assert reply['model']['revision']==1 and reply['model']['evidence'][0]['status']=='simulated'
        assert api(server,'/api/agent/accept-design',{**body,'confirmed':True})[0]==400
    finally:server.shutdown();server.server_close();thread.join()


def test_restore_preview_rejects_stale_or_changed_history_and_creates_new_version(tmp_path):
    workspace,model=setup(tmp_path/'case',synthetic_room(),{'variant':'history'});output=tmp_path/'agent';output.mkdir()
    tools=AgentTools(workspace,output,'codex-cli:synthetic',allowed_images=set());p=tools.preview_restore({'source_revision':1})
    server=StudioServer(0,None,workspace,agent_settings={'model':'synthetic','output_root':tmp_path,'codex':'unused','node':'unused','timeout':1})
    server.agent_job={'id':'agent-'+'b'*32,'status':'COMPLETED','source_revision':0,'image_ids':[],'output':output,'candidates':[]}
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        body={'job_id':server.agent_job['id'],'proposal_id':p['id'],'revision':2,'confirmed':True}
        assert api(server,'/api/agent/accept-restore',{**body,'revision':1})[0]==400
        old=workspace/'revision-001'/'model.json';saved=old.read_text();obj=json.loads(saved);obj['elements'][0]['parameters']['height']['value']=2.7;old.write_text(json.dumps(obj))
        assert api(server,'/api/agent/accept-restore',body)[0]==400;old.write_text(saved)
        code,result=api(server,'/api/agent/accept-restore',body);assert code==200 and result['model']['revision']==3
        assert result['model']['history'][-1]['source_revision']==1
        assert (workspace/'revision-001'/'model.ifc').exists() and (workspace/'revision-002'/'model.ifc').exists()
        assert api(server,'/api/agent/accept-restore',body)[0]==400
    finally:server.shutdown();server.server_close();thread.join()
