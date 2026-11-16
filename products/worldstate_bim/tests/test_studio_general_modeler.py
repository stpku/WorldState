"""Synthetic API coverage for the local general Modeler."""

from products.worldstate_bim.tests.test_general_modeler import fixture


def test_studio_creates_new_surface_from_uploaded_photos_and_versioned_points(tmp_path):
    """Synthetic local API integration; none of these clicks are human evidence."""
    import base64
    import hashlib
    import io
    import threading
    from PIL import Image
    from products.worldstate_bim.studio_server import StudioServer
    from products.worldstate_bim.tests.test_studio_server import api
    data=fixture();data['objects']=data['objects'][:1];data['observations']=[o for o in data['observations'] if o['object_id']=='west']
    server=StudioServer(0,None,tmp_path/'studio');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        assert api(server,'/api/project',{'name':'Synthetic modeler','operator_kind':'automation'})[0]==201
        uploads={}
        for cam in data['cameras']:
            buf=io.BytesIO();Image.new('RGB',(640,480),(cam['image_id']*30,0,0)).save(buf,format='PNG')
            status,upload=api(server,'/api/upload',{'data_base64':base64.b64encode(buf.getvalue()).decode()});assert status==201
            cam['sha256']=upload['sha256'];uploads[cam['image_id']]=upload
        manifest={'schema':'worldstate-modeler-cameras/0.1','camera_mode':'known-pose','cameras':data['cameras'],
                  'source_reconstruction':[{'file':'synthetic','sha256':'f'*64}]}
        manifest['tracks']=[{'id':7,'observations':[{'image_id':o['image_id'],'pixel_xy':o['pixel_xy']}
                             for o in data['observations'] if o['feature_id']=='a']}]
        status,state=api(server,'/api/modeler/cameras',{'manifest':manifest});assert status==201
        status,response=api(server,'/api/modeler/object',{'state_revision':state['revision'],'id':'west','vertices':4})
        assert status==201;state=response['state']
        class FakeVision:
            def analyze(self,path):
                return ({'image_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'model_sha256':'f'*64,
                    'runtime_seconds':0,'candidates':[{'id':'fake-point','kind':'line_endpoint',
                    'points_px':[[350.,290.]],'uncertainty':'synthetic'}]},b'fake-overlay')
        server.vision_model=tmp_path/'fake-weights';server.vision_provider=FakeVision()
        status,run=api(server,'/api/vision/analyze',{'photo_id':uploads[1]['id']});assert status==201
        status,response=api(server,'/api/modeler/vision-decision',{'state_revision':state['revision'],
            'run_id':run['id'],'candidate_id':'fake-point','object_id':'west','decision':'accept','feature_id':'p1','sigma_px':2.})
        assert status==200;state=response['state']
        assert state['observations'][0]['origin']=='ai_suggested' and state['observations'][0]['accepted_by']=='automation'
        for observation in data['observations']:
            status,response=api(server,'/api/modeler/point',{'state_revision':state['revision'],'object_id':'west',
                'image_id':observation['image_id'],'feature_id':{'a':'p1','b':'p2','c':'p3','d':'p4'}[observation['feature_id']],
                'pixel_xy':observation['pixel_xy'],'sigma_px':.1})
            assert status==201, response
            state=response['state']
        assert all(o['origin']=='automation' and o['confirmation']=='automation_unverified' for o in state['observations'])
        server.project['general_modeler']['track_source']='synthetic line-intersection candidates'
        status,response=api(server,'/api/modeler/suggest',{'state_revision':state['revision'],'object_id':'west','feature_id':'p1','image_id':1})
        assert status==200 and response['state']['suggestions'];state=response['state']
        assert state['suggestions'][0]['origin']=='deterministic_feature_track'
        track_file=server.workspace/'modeler-tracks.json';original=track_file.read_bytes();track_file.write_bytes(b'tampered')
        status,error=api(server,'/api/modeler/decision',{'state_revision':state['revision'],
            'suggestion_id':state['suggestions'][0]['id'],'decision':'accept'})
        assert status==400 and '轨迹文件已改变' in error['error']
        assert server.project['general_modeler']['suggestions'][0]['status']=='proposed'
        track_file.write_bytes(original)
        status,response=api(server,'/api/modeler/decision',{'state_revision':state['revision'],
            'suggestion_id':state['suggestions'][0]['id'],'decision':'accept'})
        assert status==200;state=response['state']
        accepted=[o for o in state['observations'] if o.get('track_id')==7]
        assert len(accepted)==2 and all(o['origin']=='deterministic' and o['accepted_by']=='automation' and
                                      o['track_source']=='synthetic line-intersection candidates' for o in accepted)
        before_events=len(server.project['events'])
        status,preview=api(server,'/api/modeler/preview-solve',{'state_revision':state['revision']})
        assert status==200 and preview['persisted'] is False and preview['state_revision']==state['revision']
        assert preview['solution']['optimization']['point_max_px']<1e-5
        assert server.project['general_modeler']['revision']==state['revision'] and len(server.project['events'])==before_events
        status,response=api(server,'/api/modeler/solve',{'state_revision':state['revision'],
            'sensitivity':{'samples':4,'camera_position_sigma_source':.001,'camera_rotation_sigma_deg':.01,'focal_sigma_fraction':.0001}})
        assert status==200 and response['solution']['optimization']['point_max_px']<1e-5;state=response['state']
        body={'state_revision':state['revision'],'scale':{'basis':'assumed','metres_per_source_unit':1.},
              'thickness_m':.1,'up_source':[0,-1,0],'confirm_up_assumed':True,'allow_rectangular_approximation':True}
        status,response=api(server,'/api/modeler/commit',body);assert status==201
        assert response['model']['elements'][0]['id']=='west' and api(server,'/api/export/model.ifc')[1].startswith(b'ISO-10303-21')
        assert api(server,'/api/modeler/commit',body)[0]==409
        state=response['state'];old=next(o for o in state['observations'] if o['feature_id']=='p1' and o['image_id']==1)
        def anchor_endpoints(value):
            return [{'id':feature,'observations':[{'image_id':o['image_id'],'photo_sha256':o['photo_sha256'],'pixel_xy':o['pixel_xy']}
                for o in value['observations'] if o['kind']=='point' and o['feature_id']==feature]} for feature in ('p1','p2')]
        anchor={'schema':'worldstate-multiview-scale-anchor/0.1','object_id':'west','confirmed':True,
                'basis':'independent_user_declared','distance_m':1.,'measurement_uncertainty_m':.01,
                'description':'synthetic test reference','endpoints':anchor_endpoints(state)}
        status,response=api(server,'/api/modeler/point',{'state_revision':state['revision'],'object_id':'west','image_id':1,
            'feature_id':'p1','pixel_xy':[old['pixel_xy'][0]+.01,old['pixel_xy'][1]],'sigma_px':.1})
        assert status==201 and api(server,'/api/export/model.ifc')[0]==409
        assert (server.workspace/'revision-001'/'model.ifc').is_file()
        state=response['state'];status,response=api(server,'/api/modeler/solve',{'state_revision':state['revision']});assert status==200
        state=response['state'];body['state_revision']=state['revision'];body['scale']=anchor
        status,error=api(server,'/api/modeler/commit',body);assert status==400 and '重新绑定' in error['error']
        anchor['endpoints']=anchor_endpoints(state);status,response=api(server,'/api/modeler/commit',body);assert status==201
        assert response['model']['revision']==2 and api(server,'/api/export/model.ifc')[0]==200
        state=response['state']
        status,response=api(server,'/api/modeler/discard-unsaved-object',{'state_revision':state['revision'],'object_id':'west'})
        assert status==400 and '已保存' in response['error']
        status,response=api(server,'/api/modeler/object',{'state_revision':state['revision'],'id':'abandoned','vertices':4})
        assert status==201;state=response['state']
        status,response=api(server,'/api/modeler/point',{'state_revision':state['revision'],'object_id':'abandoned',
            'image_id':1,'feature_id':'p1','pixel_xy':[12.,34.],'sigma_px':2.})
        assert status==201;state=response['state']
        status,response=api(server,'/api/modeler/discard-unsaved-object',{'state_revision':state['revision'],'object_id':'abandoned'})
        assert status==200 and [o['id'] for o in response['state']['objects']]==['west']
        event=server.project['events'][-1]
        assert event['action']=='modeler_unsaved_candidate_discarded' and event['observations'][0]['pixel_xy']==[12.,34.]
        assert api(server,'/api/export/model.ifc')[0]==409
    finally:
        server.shutdown();server.server_close();thread.join()
