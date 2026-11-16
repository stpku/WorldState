"""Blender 5.2: render IFC-derived geometry and exact camera/visibility truth."""
from __future__ import annotations
import json
import math
import random
import sys
from pathlib import Path
import bpy
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view


def main():
    spec_path,input_dir,reference_dir=map(Path,sys.argv[sys.argv.index('--')+1:]);spec=json.loads(spec_path.read_text())
    rng=random.Random(spec['seed']);scene=bpy.context.scene
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene.render.engine='CYCLES';scene.cycles.samples=spec['samples'];scene.cycles.seed=spec['seed']%65536
    scene.render.resolution_x=spec['width'];scene.render.resolution_y=spec['height_px'];scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB'
    scene.view_layers[0].use_pass_z=True;scene.view_layers[0].use_pass_object_index=True
    scene.world.color=(.15,.15,.15)
    world=bpy.data.worlds.new('synthetic-world');scene.world=world;world.use_nodes=True
    world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.25*spec['illumination']
    palette={'IfcWall':(.72,.71,.68,1),'IfcSlab':(.43,.40,.36,1),'IfcDoor':(.43,.28,.17,1),'IfcWindow':(.21,.40,.48,1)}
    materials={}
    for kind,color in palette.items():
        material=bpy.data.materials.new(kind);material.diffuse_color=color;material.use_nodes=True
        shader=material.node_tree.nodes.get('Principled BSDF');shader.inputs['Base Color'].default_value=color
        if kind=='IfcWall' and not spec['low_texture']:
            noise=material.node_tree.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=55.
            mix=material.node_tree.nodes.new('ShaderNodeMixRGB');mix.inputs[1].default_value=(.50,.49,.46,1)
            mix.inputs[2].default_value=(.78,.77,.73,1)
            material.node_tree.links.new(noise.outputs['Fac'],mix.inputs[0]);material.node_tree.links.new(mix.outputs[0],shader.inputs['Base Color'])
        shader.inputs['Roughness'].default_value=.85;materials[kind]=material
    for item in spec['mesh']:
        mesh=bpy.data.meshes.new('synthetic-mesh');mesh.from_pydata(item['vertices'],[],item['faces']);mesh.update()
        obj=bpy.data.objects.new('synthetic-object-'+str(item['id']),mesh);scene.collection.objects.link(obj)
        obj.data.materials.append(materials[item['ifc_type']]);obj.pass_index=item['id']
    xs=[n[0] for n in spec['nodes']];ys=[n[1] for n in spec['nodes']];width=max(xs)-min(xs);depth=max(ys)-min(ys)
    # Furniture is deliberately not a BIM wall and occludes parts of some views.
    bpy.ops.mesh.primitive_cube_add(size=1,location=(width*.36,depth*.25,.46));furniture=bpy.context.object
    furniture.dimensions=(.65,.85,.92);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);furniture.pass_index=900
    mat=bpy.data.materials.new('synthetic-furniture');mat.diffuse_color=(.28,.22,.14,1);mat.use_nodes=True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=mat.diffuse_color;furniture.data.materials.append(mat)
    # Ceiling and furniture are synthetic scene geometry; neither is claimed as a predicted IFC element.
    mesh=bpy.data.meshes.new('synthetic-ceiling');mesh.from_pydata([(x,y,spec['height']) for x,y in spec['nodes']],[],[list(range(len(spec['nodes'])))])
    ceiling=bpy.data.objects.new('synthetic-ceiling',mesh);scene.collection.objects.link(ceiling);ceiling.pass_index=901;ceiling.data.materials.append(materials['IfcWall'])
    light=bpy.data.lights.new('synthetic-light','AREA');light.energy=100*spec['illumination'];light.shape='DISK';light.size=2.
    lo=bpy.data.objects.new('synthetic-light',light);scene.collection.objects.link(lo);lo.location=(width*.26,depth*.26,spec['height']-.15)
    camera_data=bpy.data.cameras.new('synthetic-camera');cam=bpy.data.objects.new('synthetic-camera',camera_data);scene.collection.objects.link(cam);scene.camera=cam
    camera_data.type='PERSP';camera_data.lens=20.;camera_data.sensor_width=36.;camera_data.sensor_fit='HORIZONTAL';camera_data.clip_end=100
    scene.compositing_node_group=bpy.data.node_groups.new('WS-ground-truth','CompositorNodeTree')
    tree=scene.compositing_node_group;render=tree.nodes.new('CompositorNodeRLayers');outputs={}
    for name,source in [('depth','Depth'),('instance','Object Index')]:
        node=tree.nodes.new('CompositorNodeOutputFile');node.directory=str(reference_dir);node.format.file_format='OPEN_EXR_MULTILAYER';node.format.color_depth='32'
        node.file_output_items.new('FLOAT','value');tree.links.new(render.outputs[source],node.inputs['value']);outputs[name]=node
    cameras=[];features=[];view_count=6  # Equal count does not expose room shape in input filenames.
    # IFC mesh vertices are exact; projected corner visibility is determined by scene ray casting.
    candidates=[]
    for item in spec['mesh']:
        if item['ifc_type']!='IfcWall':continue
        seen=set()
        for v in item['vertices']:
            key=tuple(round(x,7) for x in v)
            if key in seen or min(abs(v[2]),abs(v[2]-spec['height']))>1e-5:continue
            seen.add(key);candidates.append({'feature_id':f"v{item['id']}-{len(seen)}",'kind':'mesh_corner',
                                             'instance_id':item['id'],'world_xyz':list(key)})
        # Interior face samples remain useful even when exact mesh vertices are
        # hidden by touching solids or lie on a rasterization boundary.
        for face_index,face in enumerate(item['faces']):
            p=[Vector(item['vertices'][i]) for i in face]
            if (p[1]-p[0]).cross(p[2]-p[0]).length<.02:continue
            center=(p[0]+p[1]+p[2])/3
            candidates.append({'feature_id':f"s{item['id']}-{face_index}",'kind':'surface_sample',
                               'instance_id':item['id'],'world_xyz':[float(x) for x in center]})
    for index in range(view_count):
        a=spec['nodes'][index%len(spec['nodes'])];b=spec['nodes'][(index+1)%len(spec['nodes'])]
        cam.location=(width*(.20+rng.random()*.25),depth*(.16+rng.random()*.20),1.30+rng.random()*.18)
        target=Vector(((a[0]+b[0])/2,(a[1]+b[1])/2,spec['height']*.48));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
        bpy.context.view_layer.update();world_to_blender=cam.matrix_world.inverted();cv=Matrix.Diagonal((1.,-1.,-1.,1.))@world_to_blender
        focal=spec['width']*camera_data.lens/camera_data.sensor_width
        cameras.append({'image_id':index+1,'photo':f'view-{index+1:03}.png','width_px':spec['width'],'height_px':spec['height_px'],
          'camera_model':'SIMPLE_PINHOLE','intrinsics':[focal,spec['width']/2,spec['height_px']/2],
          'rotation_camera_from_world':[[float(cv[i][j]) for j in range(3)] for i in range(3)],
          'translation_camera_from_world':[float(cv[i][3]) for i in range(3)]})
        for candidate in candidates:
            point=Vector(candidate['world_xyz']);uv=world_to_camera_view(scene,cam,point)
            px=[float(uv.x*spec['width']),float((1.-uv.y)*spec['height_px'])]
            visible='outside_frame'
            if uv.z>0 and 0<=px[0]<spec['width'] and 0<=px[1]<spec['height_px']:
                ray=point-cam.location;distance=ray.length
                hit,position,_,_,obj,_=scene.ray_cast(bpy.context.evaluated_depsgraph_get(),cam.location,ray.normalized(),distance=distance+1e-4)
                visible='visible' if hit and abs((position-cam.location).length-distance)<1e-3 and obj.pass_index==candidate['instance_id'] else 'occluded_or_edge_ambiguous'
            features.append({**candidate,'image_id':index+1,'pixel_xy':px,'visibility':visible})
        for name,node in outputs.items():node.file_name=f'{name}-{index+1:03}'
        scene.render.filepath=str(input_dir/'images'/f'view-{index+1:03}.png');bpy.ops.render.render(write_still=True)
    (reference_dir/'cameras-exact.json').write_text(json.dumps({'cameras':cameras},indent=2)+'\n')
    (reference_dir/'feature-visibility.json').write_text(json.dumps({'features':features,'visibility_tolerance_m':.001},indent=2)+'\n')


if __name__=='__main__':main()
