"""Shared contour sampling and constrained triangulation helpers.
Image files are sampled without editing. Requires scipy, skimage, triangle,
shapely, trimesh, Pillow, numpy. No image files are modified.
"""
import argparse, json, time
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage.measure import find_contours
from shapely.geometry import Polygon, MultiPolygon
from shapely import union_all
from shapely.geometry.polygon import orient
import triangle
import trimesh

def gray(path):
    # Encoding, not the brightest pixel, determines the integer range. A dark
    # 16-bit map may contain only values below 256 and must remain near zero.
    with Image.open(path) as image:
        if min(image.size)<2:raise ValueError('Map images must be at least 2 by 2 pixels')
        source=np.asarray(image)
        is_16bit=image.mode.startswith('I;16') or (image.mode=='I' and image.format=='PNG') or (source.dtype.kind=='u' and source.dtype.itemsize==2)
        if is_16bit:
            result=source.astype(np.float32)/65535
            if 'transparency' in image.info:result[source==image.info['transparency']]=0
            return result
        # Palette values are indices, and bilevel pixels are booleans. Decode
        # them before sampling; alpha masks out hidden RGB values.
        if image.mode in ('P','PA') or 'transparency' in image.info:
            image=image.convert('RGBA')
        elif image.mode=='1':
            image=image.convert('L')
        source=np.asarray(image)
        a=source.astype(np.float32)
        mode=image.mode
    maximum=65535 if is_16bit else 255
    if mode=='RGBA':
        return a[:,:,:3].mean(axis=2)/maximum*(a[:,:,3]/maximum)
    if mode=='LA':
        return a[:,:,0]/maximum*(a[:,:,1]/maximum)
    if a.ndim==3:a=a[:,:,:3].mean(axis=2)
    return a/maximum

def polygons_from_mask(mask,width,preserve_pixels=False):
    if mask.ndim!=2 or min(mask.shape)<2:raise ValueError('Map images must be at least 2 by 2 pixels')
    if not np.isfinite(width) or width<=0:raise ValueError('Width must be finite and positive')
    ih,iw=mask.shape;scale=width/(iw-1)
    binary=mask>0.5
    padded=np.pad(binary,4)
    signed=ndi.distance_transform_edt(padded)-ndi.distance_transform_edt(~padded)
    if not preserve_pixels:signed=ndi.gaussian_filter(signed,1.1)
    minimum_area=0. if preserve_pixels else 2e-7
    contours=find_contours(signed,0)
    rings=[]
    for c in contours:
        xy=np.column_stack([(c[:,1]-4)*scale,(ih-1-(c[:,0]-4))*scale])
        polygon=Polygon(xy).buffer(0)
        if polygon.area>minimum_area:rings.append(polygon)
    # Determine alternating fill parity; outer loops contain inner loops.
    outer=[]
    for i,p in enumerate(rings):
        containers=sum(q.contains(p.representative_point()) and q.area>p.area for j,q in enumerate(rings) if j!=i)
        if containers%2==0:
            holes=[q.exterior.coords for q in rings if q.area<p.area and p.contains(q) and sum(r.contains(q.representative_point()) and r.area>q.area for r in rings)==containers+1]
            outer.append(Polygon(p.exterior.coords,holes).buffer(0))
    geom=union_all(outer)
    parts=list(geom.geoms) if isinstance(geom,MultiPolygon) else [geom]
    # This is mesh contour conditioning, not a raster-image edit.
    # Sub-millimetre raster ripples are below the selected metal-edge bevel.
    return [orient(p if preserve_pixels else p.simplify(0.00025,preserve_topology=True),sign=1) for p in parts if p.area>minimum_area],scale,signed

def ring_sample(coords,spacing=0.0008):
    c=np.asarray(coords,dtype=np.float64)
    points=[]
    for a,b in zip(c[:-1],c[1:]):
        n=max(1,int(np.ceil(np.linalg.norm(b-a)/spacing)))
        points.extend(a+(b-a)*np.arange(n)[:,None]/n)
    return np.asarray(points)

def triangulate_polygon(poly,max_area):
    arrays=[];segments=[];offset=0;holes=[]
    for ring in [poly.exterior,*poly.interiors]:
        a=ring_sample(ring.coords)
        arrays.append(a);n=len(a)
        segments.append(np.column_stack([np.arange(n)+offset,np.roll(np.arange(n),-1)+offset]))
        offset+=n
    for ring in poly.interiors:
        rp=Polygon(ring).representative_point();holes.append([rp.x,rp.y])
    args={'vertices':np.vstack(arrays),'segments':np.vstack(segments)}
    if holes:args['holes']=holes
    result=triangle.triangulate(args,f'pq20a{max_area:.12f}C')
    return result['vertices'],result['triangles']

