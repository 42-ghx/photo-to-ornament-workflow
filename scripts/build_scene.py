"""Independent background Blender: create UV highpoly, render proof, export FBX."""
import argparse,json,sys,time
from pathlib import Path
import bpy,numpy as np
from mathutils import Vector,Euler

def material(name,color):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
    bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=.65
    return m

def mesh_from_arrays(v,q,name):
    m=bpy.data.meshes.new(name);m.vertices.add(len(v));m.vertices.foreach_set('co',v.ravel())
    m.loops.add(q.size);m.loops.foreach_set('vertex_index',q.ravel())
    m.polygons.add(len(q));m.polygons.foreach_set('loop_start',np.arange(len(q),dtype=np.int32)*4)
    m.polygons.foreach_set('loop_total',np.full(len(q),4,np.int32));m.polygons.foreach_set('use_smooth',np.ones(len(q),np.bool_));m.update()
    return m

def render(scene,path,target,delta,scale,res=(2100,1000),bounds=None):
    target=Vector(target);cam=scene.camera;cam.location=target+Vector(delta);cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
    if bounds is not None:
        # Full-object views must fit both projected axes, including tall motifs.
        local=(bounds-np.asarray(target))@np.asarray(cam.rotation_euler.to_matrix())
        extent=2*np.max(np.abs(local[:,:2]),axis=0);aspect=res[0]/res[1]
        scale=max(scale,1.08*extent[0],1.08*extent[1]*aspect)
    cam.data.sensor_fit='HORIZONTAL';cam.data.ortho_scale=scale
    scene.render.resolution_x,scene.render.resolution_y=res;scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)

def uv_outline_svg(data,out):
    scale=data['scale'];placements={int(k):v for k,v in data['placements'].items()};px=4096
    colors={'front':'#85b9fb','thickness':'#efb473','bottom':'#9cdbb3'}
    def xy(u,v):return f'{u*px:.3f},{(1-v)*px:.3f}'
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" viewBox="0 0 {px} {px}">',f'<rect width="{px}" height="{px}" fill="#14171b"/>']
    cap_paths={}
    for boundary in data['boundaries']:
        uv=boundary['uv'];path='M'+' L'.join(xy(*p) for p in uv)+' Z';cap_paths.setdefault((boundary['kind'],boundary['chart']),[]).append(path)
    for (kind,cid),paths in cap_paths.items():
        parts.append(f'<path d="{" ".join(paths)}" fill="{colors[kind]}" fill-opacity=".25" stroke="{colors[kind]}" stroke-width="2" fill-rule="evenodd"/>')
    for chart in data['charts']:
        if chart['kind']!='thickness':continue
        x,y=placements[chart['id']];w,h=chart['width']*scale,chart['height']*scale
        parts.append(f'<rect x="{x*px:.3f}" y="{(1-y-h)*px:.3f}" width="{w*px:.3f}" height="{h*px:.3f}" fill="{colors["thickness"]}" fill-opacity=".45" stroke="{colors["thickness"]}" stroke-width=".7"/>')
    parts.append('</svg>');(out/'UV_layout_4096.svg').write_text('\n'.join(parts),encoding='utf-8')

def main():
    if not bpy.app.background:raise RuntimeError('Run in separate BACKGROUND Blender only')
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    source=Path(a.source).resolve();out=Path(a.out).resolve()
    outputs=('01_form.png','02_thickness.png','03_bottom.png','04_side_loops.png','05_uv_checker.png','ornament_highpoly.fbx','fbx_uv_checks.json','ornament_highpoly.blend','UV_layout_4096.svg')
    if any((out/name).exists() or (out/name).is_symlink() for name in outputs):raise FileExistsError('Output artifacts already exist; choose a new version directory')
    out.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter();data=np.load(source/'ding_quad_uv.npz');v=data['vertices'];q=data['quads'];uv=data['uv'];kind=data['face_kind'];width=float(np.ptp(v[:,0]));support=float(v[np.unique(q[kind==1]),2].max());peak=float(v[:,2].max())
    lower,upper=v.min(axis=0),v.max(axis=0)
    bounds=np.array([(x,y,z) for x in (lower[0],upper[0]) for y in (lower[1],upper[1]) for z in (lower[2],upper[2])])
    bpy.ops.wm.read_factory_settings(use_empty=True);scene=bpy.context.scene;scene.name='Ornament_Highpoly_Review';scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
    mesh=mesh_from_arrays(v,q,'Ornament_Quad_HighPoly_UV');layer=mesh.uv_layers.new(name='UV_Main');layer.data.foreach_set('uv',uv.ravel())
    for key,values in [('surface_region',kind),('source_component',data['face_component']),('uv_island',data['face_chart'])]:
        attr=mesh.attributes.new(key,'INT','FACE');attr.data.foreach_set('value',values.astype(np.int32))
    mats=[material('01_FRONT',(.58,.61,.65)),material('02_THICKNESS',(.58,.61,.65)),material('03_BOTTOM',(.58,.61,.65))]
    for m in mats:mesh.materials.append(m)
    mesh.polygons.foreach_set('material_index',kind.astype(np.int32))
    edges=np.empty(len(mesh.edges)*2,np.int32);mesh.edges.foreach_get('vertices',edges);edges=edges.reshape(-1,2)
    def encode(e):
        e=np.sort(e,axis=1).astype(np.int64);return e[:,0]*len(v)+e[:,1]
    selected=np.isin(encode(edges),encode(data['seams']));mesh.edges.foreach_set('use_seam',selected);mesh.update()
    obj=bpy.data.objects.new('ORNAMENT_HIGH_UV',mesh);scene.collection.objects.link(obj);obj.color=(.58,.61,.65,1)
    for key,value in {'width_m':width,'maximum_thickness_m':peak,'base_thickness_m':support,'relief_amplitude_m':peak-support,'wall_layers':int(len(np.unique(v[np.unique(q[kind==1]),2]))-1),'horizontal_contour_levels':int(len(np.unique(v[np.unique(q[kind==1]),2]))),'uv_regions':'FRONT / THICKNESS / BOTTOM','uv_cut_rule':'Every horizontal thickness ring, plus vertical strip-opening cuts','source_material_components':int(data['face_component'].max())+1,'remesh':'Controlled contour constrained triangles converted to dense quads, explicit horizontal sidewall rings'}.items():obj[key]=value
    scene.world=bpy.data.worlds.new('Neutral Review');scene.world.color=(.04,.045,.055)
    scene.render.engine='BLENDER_WORKBENCH';scene.render.resolution_percentage=100;scene.render.image_settings.file_format='PNG'
    shade=scene.display.shading;shade.light='STUDIO';shade.color_type='OBJECT';shade.show_shadows=True;shade.show_cavity=True;shade.cavity_type='BOTH';shade.background_type='WORLD'
    cam=bpy.data.objects.new('Review Camera',bpy.data.cameras.new('Review Camera'));scene.collection.objects.link(cam);scene.camera=cam;cam.data.type='ORTHO';cam.data.clip_start=.001
    render(scene,out/'01_form.png',(0,0,peak*.4),(0,-.35*width,width),1.08*width,(2200,850),bounds=bounds)
    render(scene,out/'02_thickness.png',(0,0,peak*.4),(0,-.8*width,.30*width),1.08*width,(2200,1000),bounds=bounds)
    render(scene,out/'03_bottom.png',(0,0,0),(0,.1*width,-width),1.08*width,(2200,850),bounds=bounds)
    # A real wireframe geometry overlay on only the side faces makes the contour rings readable.
    side=q[kind==1];sv=v[side];inside=(sv[:,:,0].mean(axis=1)>-.36*width)&(sv[:,:,0].mean(axis=1)<-.12*width)&(sv[:,:,1].mean(axis=1)<-.065*width)
    sample=side[inside];used,inv=np.unique(sample,return_inverse=True)
    wm=mesh_from_arrays(v[used],inv.reshape(-1,4).astype(np.int32),'Local side-loop proof')
    wire=bpy.data.objects.new('Wall_Loop_Proof',wm);scene.collection.objects.link(wire);wire.color=(.03,.035,.04,1)
    modifier=wire.modifiers.new('Actual quad edge wire overlay','WIREFRAME');modifier.thickness=.000045*width;modifier.offset=1.;modifier.use_replace=True
    render(scene,out/'04_side_loops.png',(-.235*width,-.095*width,support*.55),(0,-.30*width,.13*width),.30*width,(1900,1100));wire.hide_render=True;wire.hide_viewport=True
    # Data-driven checker diagnostic, drawn on actual face corners through their UVs.
    checker=mesh.color_attributes.new(name='UV_Checker_32',type='BYTE_COLOR',domain='CORNER')
    check=(np.floor(uv[:,:,0]*32).astype(int)+np.floor(uv[:,:,1]*32).astype(int))%2
    rgba=np.ones((q.size,4),np.float32);colors=np.where(check.ravel()==0,.14,.72);rgba[:,:3]=colors[:,None];checker.data.foreach_set('color',rgba.ravel());mesh.color_attributes.active_color_index=0
    shade.color_type='VERTEX';shade.show_cavity=False
    render(scene,out/'05_uv_checker.png',(0,0,peak*.4),(0,-.6*width,.9*width),1.08*width,(2200,1000),bounds=bounds);shade.color_type='OBJECT';shade.show_cavity=True
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    path=out/'ornament_highpoly.fbx';bpy.ops.export_scene.fbx(filepath=str(path),use_selection=True,object_types={'MESH'},apply_unit_scale=True,bake_anim=False,use_mesh_modifiers=True)
    before=set(bpy.data.objects);bpy.ops.import_scene.fbx(filepath=str(path));bpy.context.view_layer.update();loaded=[o for o in set(bpy.data.objects)-before if o.type=='MESH']
    if len(loaded)!=1:raise RuntimeError('FBX must have one mesh object')
    rt=loaded[0];rmesh=rt.data;ruv=np.empty(len(rmesh.loops)*2,np.float32);rmesh.uv_layers.active.data.foreach_get('uv',ruv)
    positions=np.empty(len(mesh.vertices)*3,np.float32);mesh.vertices.foreach_get('co',positions)
    returned=np.empty(len(rmesh.vertices)*3,np.float32);rmesh.vertices.foreach_get('co',returned)
    co_error=float(np.max(np.abs(positions-returned))) if len(positions)==len(returned) else None
    counts_ok=len(rmesh.vertices)==len(mesh.vertices) and len(rmesh.polygons)==len(mesh.polygons) and len(rmesh.loops)==len(mesh.loops)
    uv_error=float(np.max(np.abs(ruv-uv.ravel()))) if len(ruv)==uv.size else None
    dim_error=float(np.max(np.abs(np.array(rt.dimensions)-np.array(obj.dimensions))))
    result={'status':'passed' if co_error is not None and co_error<1e-6 and counts_ok and uv_error is not None and uv_error<1e-6 and dim_error<1e-6 else 'failed','blender_version':bpy.app.version_string,'fbx':path.name,'vertices':len(mesh.vertices),'quads':len(mesh.polygons),'loop_uv_values':len(ruv)//2,'fbx_counts_match':counts_ok,'fbx_coordinate_max_error_m':co_error,'fbx_uv_max_error':uv_error,'fbx_dimension_max_error_m':dim_error,'seam_edges':int(selected.sum()),'uv_layers':[x.name for x in mesh.uv_layers],'seconds':round(time.perf_counter()-start,2)}
    (out/'fbx_uv_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if result['status']!='passed':raise RuntimeError(str(result))
    bpy.data.objects.remove(rt,do_unlink=True);bpy.data.meshes.remove(rmesh)
    bpy.context.view_layer.objects.active=obj;obj.select_set(True)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='VIEW_3D':
                sp=area.spaces.active;sp.shading.color_type='OBJECT';sp.shading.show_cavity=True;sp.shading.cavity_type='BOTH';sp.overlay.show_floor=False;sp.overlay.show_extras=False;sp.overlay.show_cursor=False
                sp.region_3d.view_rotation=Euler((.35,0,0)).to_quaternion();sp.region_3d.view_distance=1.2*width;sp.region_3d.view_location=(0,0,peak*.4);sp.region_3d.view_perspective='ORTHO'
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'ornament_highpoly.blend'))
    uv_outline_svg(json.loads((source/'uv_charts.json').read_text()),out)
    print(json.dumps(result),flush=True)

if __name__=='__main__':main()
