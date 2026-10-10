"""Controlled all-quad highpoly remesh with horizontal contour rings and UVs.
PNG inputs are read-only mesh sampling sources. No bitmap assets are rewritten.
"""
import argparse, importlib.util, json, time
from pathlib import Path
import numpy as np
from scipy import ndimage as ndi
import trimesh

helper_path=Path(__file__).resolve().parent/'contour_base.py'
spec=importlib.util.spec_from_file_location('contour',helper_path)
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

def cross2d(a,b):
    return a[...,0]*b[...,1]-a[...,1]*b[...,0]

def planar_quad_mesh(poly,area):
    xy,t=helper.triangulate_polygon(poly,area)
    cross=cross2d(xy[t[:,1]]-xy[t[:,0]],xy[t[:,2]]-xy[t[:,0]])
    t[cross<0]=t[cross<0,::-1]
    directed=np.vstack([t[:,[0,1]],t[:,[1,2]],t[:,[2,0]]])
    edges,first,inv,counts=np.unique(np.sort(directed,axis=1),axis=0,return_index=True,return_inverse=True,return_counts=True)
    n=len(xy); mids=n+inv.reshape(3,-1).T
    centers=n+len(edges)+np.arange(len(t))
    quads=np.empty((len(t)*3,4),np.int32)
    quads[0::3]=np.column_stack([t[:,0],mids[:,0],centers,mids[:,2]])
    quads[1::3]=np.column_stack([t[:,1],mids[:,1],centers,mids[:,0]])
    quads[2::3]=np.column_stack([t[:,2],mids[:,2],centers,mids[:,1]])
    points=np.vstack([xy,xy[edges].mean(axis=1),xy[t].mean(axis=1)])
    boundary=directed[first[counts==1]]
    boundary_mid=n+np.where(counts==1)[0]
    successor={int(a):(int(b),int(m)) for (a,b),m in zip(boundary,boundary_mid)}
    rings=[]
    while successor:
        start=next(iter(successor));v=start;ring=[]
        while True:
            nxt,mid=successor.pop(v);ring.extend([v,mid]);v=nxt
            if v==start:break
        rings.append(np.array(ring,np.int32))
    return points,quads,rings

def shelves(charts,scale,gap):
    x=gap;y=gap;row=0;placements={}
    for chart in sorted(charts,key=lambda c:(-c['height'],-c['width'])):
        w=chart['width']*scale;h=chart['height']*scale
        if x+w>1-gap:x=gap;y+=row+gap;row=0
        placements[chart['id']]=(x,y);x+=w+gap;row=max(row,h)
    return placements,y+row+gap

def prepare_height_field(height,material,encoding='legacy',median_size=5,height_sigma=2.):
    """Interpret source heights without changing the source raster files."""
    if encoding=='linear':
        if not np.isfinite(height).all() or height.min()<0 or height.max()>1:
            raise ValueError('Linear heights must be finite and in the 0-1 range')
        return height.copy(),np.zeros(material.shape,dtype=bool)
    if encoding!='legacy':raise ValueError('Unknown height encoding')
    height=ndi.gaussian_filter(ndi.median_filter(height,size=median_size),height_sigma)
    valid=material&(height>.16)
    if not valid.any():raise ValueError('Height has no valid material values above .16; inspect the height encoding')
    nearest=ndi.distance_transform_edt(~valid,return_distances=False,return_indices=True)
    suspect=material&(height<.13);height[suspect]=height[tuple(nearest[:,suspect])]
    height=np.clip(height,.14,.97)
    hmax=float(np.percentile(height[material],99.99))
    return np.clip((height-.14)/(hmax-.14),0,1),suspect

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--area',type=float,default=6e-7);p.add_argument('--maps',required=True)
    p.add_argument('--width-m',type=float,default=1.);p.add_argument('--base-m',type=float,default=.01285);p.add_argument('--relief-m',type=float,default=.02215)
    p.add_argument('--wall-layers',type=int,default=16);p.add_argument('--view-distance-m',type=float,default=5.)
    p.add_argument('--median-size',type=int,default=5);p.add_argument('--height-sigma',type=float,default=2.)
    p.add_argument('--shoulder-m',type=float,default=.004);p.add_argument('--min-component-px',type=int,default=100)
    p.add_argument('--height-encoding',choices=['legacy','linear'],default='legacy',help='linear: preserve authored 0-1 heights and small mask contours; legacy: reproduce original photo-map interpretation')
    a=p.parse_args()
    if not all(np.isfinite(value) for value in (a.width_m,a.base_m,a.relief_m,a.area,a.shoulder_m,a.view_distance_m,a.height_sigma)):raise ValueError('All numeric dimensions and sampling values must be finite')
    if min(a.width_m,a.base_m,a.relief_m,a.area,a.shoulder_m)<=0 or a.wall_layers<1:raise ValueError('Physical dimensions and density must be positive')
    if a.median_size<1 or a.median_size%2==0 or a.height_sigma<0:raise ValueError('Median size must be odd and height sigma nonnegative')
    if a.min_component_px<1:raise ValueError('Minimum component size must be at least one pixel')
    out=Path(a.out).resolve()
    outputs=('ding_quad_uv.npz','mesh_checks.json','uv_charts.json')
    if any((out/name).exists() or (out/name).is_symlink() for name in outputs):raise FileExistsError('Output artifacts already exist; choose a new version directory')
    out.mkdir(parents=True,exist_ok=True);start=time.perf_counter()
    source=Path(a.maps).resolve()
    mask=helper.gray(source/'03_material_mask.png');height=helper.gray(source/'04_height.png')
    if mask.shape!=height.shape:raise ValueError('Mask and height dimensions differ')
    material=mask>.5
    if not material.any():raise ValueError('Empty material footprint')
    labels,_=ndi.label(material);counts=np.bincount(labels.ravel());drop=np.where(counts<a.min_component_px)[0];drop=drop[drop>0];material[np.isin(labels,drop)]=False
    if not material.any():raise ValueError('No material remains after component filtering')
    field,suspect=prepare_height_field(height,material,a.height_encoding,a.median_size,a.height_sigma)
    parts,pixel_scale,signed=helper.polygons_from_mask(material.astype(float),a.width_m,preserve_pixels=a.height_encoding=='linear')
    if not parts:raise ValueError('Material mask produced no valid contours')
    ih,iw=mask.shape
    support=a.base_m;peak=a.base_m+a.relief_m;layer_count=a.wall_layers;zlevels=np.linspace(support,0,layer_count+1)
    vv=[];ff=[];uu=[];kinds=[];components=[];charts=[];face_charts=[];seams=[];loop_records=[];cap_boundaries=[]
    vertex_offset=0;chart_id=0;boundary_loops=0;wall_quads=0
    for ci,poly in enumerate(parts):
        print(f'Quad remesh component {ci+1}/{len(parts)}, area {poly.area:.6f}',flush=True)
        xy,q,rings=planar_quad_mesh(poly,a.area);n=len(xy)
        rows=ih-1-xy[:,1]/pixel_scale;cols=xy[:,0]/pixel_scale
        value=ndi.map_coordinates(field,[rows,cols],order=1,mode='nearest')
        d=ndi.map_coordinates(signed,[rows+4,cols+4],order=1,mode='nearest')*pixel_scale
        blend=np.clip(d/a.shoulder_m,0,1);blend=blend*blend*(3-2*blend)
        if a.height_encoding=='linear':blend=np.ones_like(value)
        z=support+(peak-support)*value*blend
        for r in rings:z[r]=support
        top=np.column_stack([xy,z]);bottom=np.column_stack([xy,np.zeros(n)])
        local=[top,bottom];local_count=2*n
        front_id=chart_id;chart_id+=1;back_id=chart_id;chart_id+=1
        bbox_min=xy.min(axis=0);bbox_size=np.ptp(xy,axis=0)
        charts.extend([{'id':front_id,'kind':'front','width':float(bbox_size[0]),'height':float(bbox_size[1]),'component':ci},
                       {'id':back_id,'kind':'bottom','width':float(bbox_size[0]),'height':float(bbox_size[1]),'component':ci}])
        front_uv=xy[q]-bbox_min
        back_q=q[:,::-1]+n;back_uv=xy[q[:,::-1]]-bbox_min;back_uv[:,:,0]=bbox_size[0]-back_uv[:,:,0]
        local_f=[q,back_q];local_uv=[front_uv,back_uv];local_k=[np.zeros(len(q),np.uint8),np.full(len(q),2,np.uint8)]
        local_chart=[np.full(len(q),front_id,np.int32),np.full(len(q),back_id,np.int32)]
        for r in rings:
            cap_boundaries.append({'kind':'front','chart':front_id,'xy':(xy[r]-bbox_min).tolist()})
            buv=xy[r]-bbox_min;buv[:,0]=bbox_size[0]-buv[:,0]
            cap_boundaries.append({'kind':'bottom','chart':back_id,'xy':buv.tolist()})
            rn=len(r);lengths=np.linalg.norm(xy[np.roll(r,-1)]-xy[r],axis=1);arc=np.r_[0,np.cumsum(lengths)]
            # Additional vertical cuts keep long perimeter strips practical in a single 0-1 tile.
            splits=[0];target=.8*a.width_m
            while arc[-1]-arc[splits[-1]]>target:
                nxt=max(splits[-1]+1,int(np.searchsorted(arc,arc[splits[-1]]+target))-1);splits.append(nxt)
            splits.append(rn)
            ring_indices=[r,r+n]
            for layer in range(1,layer_count):
                rv=np.column_stack([xy[r],np.full(rn,zlevels[layer])]);local.append(rv)
                ring_indices.insert(layer,local_count+np.arange(rn,dtype=np.int32));local_count+=rn
            for layer in range(layer_count+1):
                ids=ring_indices[layer]
                seams.append(np.column_stack([ids,np.roll(ids,-1)])+vertex_offset)
            for cut in splits[:-1]:
                seams.append(np.array([[ring_indices[k][cut],ring_indices[k+1][cut]] for k in range(layer_count)],np.int32)+vertex_offset)
            for layer in range(layer_count):
                upper=ring_indices[layer];lower=ring_indices[layer+1]
                side_q=np.column_stack([upper,lower,np.roll(lower,-1),np.roll(upper,-1)])
                uv=np.stack([np.column_stack([arc[:-1],np.full(rn,zlevels[layer])]),np.column_stack([arc[:-1],np.full(rn,zlevels[layer+1])]),
                             np.column_stack([arc[1:],np.full(rn,zlevels[layer+1])]),np.column_stack([arc[1:],np.full(rn,zlevels[layer])])],axis=1)
                cids=np.empty(rn,np.int32)
                for begin,end in zip(splits[:-1],splits[1:]):
                    cid=chart_id;chart_id+=1;cids[begin:end]=cid
                    uv[begin:end,:,0]-=arc[begin];uv[begin:end,:,1]-=zlevels[layer+1]
                    charts.append({'id':cid,'kind':'thickness','width':float(arc[end]-arc[begin]),'height':float(zlevels[layer]-zlevels[layer+1]),'component':ci,'loop':boundary_loops,'layer':layer})
                local_f.append(side_q);local_uv.append(uv);local_k.append(np.ones(rn,np.uint8));local_chart.append(cids)
                wall_quads+=rn
            loop_records.append({'loop':boundary_loops,'component':ci,'contour_vertices':rn,'perimeter_m':float(arc[-1]),'layers':layer_count,'zlevels_m':zlevels.tolist(),'vertical_uv_cuts':len(splits)-1})
            boundary_loops+=1
        vertices=np.vstack(local);faces=np.vstack(local_f)
        vv.append(vertices);ff.append(faces+vertex_offset);uu.append(np.vstack(local_uv));kinds.append(np.concatenate(local_k));face_charts.append(np.concatenate(local_chart));components.append(np.full(len(faces),ci,np.int16))
        vertex_offset+=len(vertices)
    vertices=np.vstack(vv);quads=np.vstack(ff).astype(np.int32);uv=np.vstack(uu).astype(np.float32);face_chart=np.concatenate(face_charts)
    # Calibrate the actual material bounds; UV chart metric scale follows the same change.
    xy_factor=a.width_m/np.ptp(vertices[:,0]);center=(vertices[:,:2].min(axis=0)+vertices[:,:2].max(axis=0))/2
    vertices[:,:2]=(vertices[:,:2]-center)*xy_factor
    front_ids=np.unique(quads[np.concatenate(kinds)==0])
    relief_peak=float(vertices[front_ids,2].max()-support)
    if a.height_encoding=='legacy':
        if relief_peak<=0:raise ValueError('Zero relief variation')
        vertices[front_ids,2]=support+(vertices[front_ids,2]-support)*(a.relief_m/relief_peak)
    z_factor=1.0  # Base thickness and every sidewall ring remain fixed.
    for c in charts:
        c['width']*=xy_factor
        if c['kind']!='thickness':c['height']*=xy_factor
        else:c['height']*=z_factor
    # Sidewall ring thickness is independent of the relief normalization.
    for record in loop_records:
        record['zlevels_m']=[float(z*z_factor) for z in record['zlevels_m']]
        record['perimeter_m']*=xy_factor
    uv[:,:,0]*=xy_factor
    caps=np.concatenate(kinds)!=1;uv[caps,:,1]*=xy_factor
    uv[~caps,:,1]*=z_factor
    gap=4/4096
    low,high=.01,1.
    for _ in range(28):
        trial=(low+high)/2;_,extent=shelves(charts,trial,gap)
        if extent<=1:low=trial
        else:high=trial
    scale=low;placements,extent=shelves(charts,scale,gap)
    offsets=np.array([placements[i] for i in range(chart_id)],np.float32)
    uv=uv*scale+offsets[face_chart,None,:]
    for boundary in cap_boundaries:
        coords=np.asarray(boundary.pop('xy'))*xy_factor*scale+offsets[boundary['chart']];boundary['uv']=coords.tolist()
    triangle_faces=np.vstack([quads[:,[0,1,2]],quads[:,[0,2,3]]])
    mesh=trimesh.Trimesh(vertices,triangle_faces,process=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume<=0:raise RuntimeError('Mesh manifold/winding check failed')
    if not np.isfinite(uv).all() or uv.min()<0 or uv.max()>1:raise RuntimeError('UV outside 0-1')
    area_uv=.5*np.abs(cross2d(uv[:,1]-uv[:,0],uv[:,2]-uv[:,0]))+.5*np.abs(cross2d(uv[:,2]-uv[:,0],uv[:,3]-uv[:,0]))
    if (area_uv<1e-14).any():raise RuntimeError('Degenerate UV faces')
    metrics={'status':'passed','width_m':a.width_m,'maximum_thickness_m':float(vertices[:,2].max()),'dimensions_m':mesh.extents.tolist(),'vertices':len(vertices),'quads':len(quads),'triangles_equivalent':len(quads)*2,
             'all_quad':True,'material_components':len(parts),'contour_loops':boundary_loops,'horizontal_loop_levels_per_contour':layer_count+1,'wall_layers':layer_count,'wall_quads':wall_quads,
             'front_quads':int(sum((k==0).sum() for k in kinds)),'bottom_quads':int(sum((k==2).sum() for k in kinds)),
             'watertight':bool(mesh.is_watertight),'winding_consistent':bool(mesh.is_winding_consistent),'volume_m3':float(mesh.volume),
             'uv_charts':chart_id,'uv_min':float(uv.min()),'uv_max':float(uv.max()),'minimum_uv_face_area':float(area_uv.min()),'uv_uniform_xy_metric_scale':scale,'uv_gap':gap,'uv_gap_4096_px':4,
             'uv_method':'front/bottom planar projection; arc-length/thickness per horizontal wall band, additional vertical cuts, disjoint chart bounding boxes',
             'face_regions':{'0':'front','1':'thickness','2':'bottom'},'image_inputs_modified':False,'height_sampling_repaired_pixels':int(suspect.sum()),'test_width_assumed':True,
             'test_view_distance_m':a.view_distance_m,'contour_shoulder_width_m':a.shoulder_m if a.height_encoding=='legacy' else 0.,'height_sampling_median_pixels':a.median_size if a.height_encoding=='legacy' else 1,'height_sampling_gaussian_sigma_pixels':a.height_sigma if a.height_encoding=='legacy' else 0.,'through_holes':int((2*len(parts)-mesh.euler_number)/2),
             'height_encoding':a.height_encoding,'height_peak_normalized':a.height_encoding=='legacy','minimum_component_pixels':a.min_component_px,'contour_conditioning':a.height_encoding=='legacy',
             'limitations':['Material components follow the supplied mask. No invented connecting bridges.','Cap projection preserves front/back pattern positions but slopes have UV stretch.','Quad remesh is dense surface sampling, not deformation-oriented lowpoly retopology.'],
             'seconds':round(time.perf_counter()-start,2)}
    np.savez_compressed(out/'ding_quad_uv.npz',vertices=vertices.astype(np.float32),quads=quads,uv=uv,face_kind=np.concatenate(kinds),face_component=np.concatenate(components),face_chart=face_chart,seams=np.unique(np.sort(np.vstack(seams),axis=1),axis=0).astype(np.int32))
    (out/'mesh_checks.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    (out/'uv_charts.json').write_text(json.dumps({'charts':charts,'placements':{str(k):v for k,v in placements.items()},'scale':scale,'gap':gap,'boundaries':cap_boundaries,'contours':loop_records},indent=2),encoding='utf-8')
    print(json.dumps(metrics),flush=True)

if __name__=='__main__':main()
