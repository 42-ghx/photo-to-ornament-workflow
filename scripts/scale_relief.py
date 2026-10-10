"""Scale only front relief relative to its support plane; never smooth details."""
import argparse,json,shutil
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--factor',type=float,required=True);a=p.parse_args()
    if not np.isfinite(a.factor) or a.factor<=0:raise ValueError('Factor must be finite and positive')
    source=a.source.resolve();source=source/'ding_quad_uv.npz' if source.is_dir() else source
    out=a.out.resolve()
    target=out/'ding_quad_uv.npz'
    if target==source:raise ValueError('Choose a separate output; keep the accepted source immutable')
    outputs=('ding_quad_uv.npz','uv_charts.json','scale_checks.json')
    if any((out/name).exists() or (out/name).is_symlink() for name in outputs):raise FileExistsError('Output artifacts already exist; choose a new version directory')
    out.mkdir(parents=True,exist_ok=True)
    data=np.load(source);old=data['vertices'];v=old.copy();q=data['quads'];kind=data['face_kind']
    if not ((kind==0).any() and (kind==1).any()):raise ValueError('Requires front and thickness face regions')
    front=np.unique(q[kind==0]);side=np.unique(q[kind==1]);bottom=np.unique(q[kind==2])
    base=float(old[side,2].max());old_amplitude=float(old[front,2].max()-base)
    if old_amplitude<=0:raise ValueError('No relief above the support plane')
    v[front,2]=base+a.factor*(old[front,2]-base)
    assert np.array_equal(v[side],old[side]) and np.array_equal(v[bottom],old[bottom])
    assert np.array_equal(v[:,:2],old[:,:2])
    error=float(np.max(np.abs((v[front,2]-base)-a.factor*(old[front,2]-base))))
    np.savez_compressed(target,**{k:(v if k=='vertices' else data[k]) for k in data.files})
    for name in ['uv_charts.json']:
        src=source.parent/name
        if src.exists() and src.resolve()!=(out/name).resolve():shutil.copy2(src,out/name)
    result={'status':'passed','source_file':source.name,'factor':a.factor,'new_smoothing':False,'height_quantization':False,'support_thickness_m':base,'old_relief_amplitude_m':old_amplitude,'new_relief_amplitude_m':float(v[front,2].max()-base),'maximum_total_height_m':float(v[:,2].max()),'pointwise_transform_error_m':error,'side_and_bottom_exactly_preserved':True,'xy_faces_uv_seams_exactly_preserved':True,'vertices':len(v),'quads':len(q)}
    (out/'scale_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)

if __name__=='__main__':main()
