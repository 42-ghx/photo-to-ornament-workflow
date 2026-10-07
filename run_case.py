"""Reproduce the approved case on Windows or Linux without altering source data."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blender', type=Path)
    parser.add_argument('--rebuild-from-maps', action='store_true')
    parser.add_argument('--mesh-only', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    scripts = root / '.agents/skills/photo-to-ornament/scripts'
    output = (args.out or root / 'runs/ding').resolve()
    before = root / 'cases/ding/mesh_before'
    source = before / 'ding_quad_uv.npz'
    if source.exists():
        with source.open('rb') as handle:
            if handle.read(43).startswith(b'version https://git-lfs.github.com/spec/v1'):
                parser.error('Before data is an LFS pointer. Run git lfs pull first.')
    blender = None
    if not args.mesh_only:
        found = str(args.blender) if args.blender else shutil.which('blender')
        if not found or not Path(found).is_file():
            parser.error('Provide --blender with an installed executable, or use --mesh-only.')
        blender = str(Path(found).resolve())
    if args.rebuild_from_maps or not source.exists():
        before = output / 'rebuilt_before'
        subprocess.run([sys.executable, str(scripts / 'build_quad_uv.py'),
                        '--maps', str(root / 'cases/ding/maps'), '--out', str(before),
                        '--width-m', '1', '--base-m', '0.01285', '--relief-m', '0.02215',
                        '--area', '6e-7', '--wall-layers', '16'], check=True)
    mesh = output / 'mesh'
    subprocess.run([sys.executable, str(scripts / 'scale_relief.py'), '--source', str(before),
                    '--out', str(mesh), '--factor', '0.5'], check=True)
    if args.mesh_only:
        print(json.dumps({'stage': 'mesh_arrays_only', 'output': str(mesh)}))
        return
    command = [blender, '--factory-startup', '-b', '--python', str(scripts / 'build_scene.py'),
               '--', '--source', str(mesh), '--out', str(output / 'result')]
    if sys.platform.startswith('linux') and not os.environ.get('DISPLAY'):
        xvfb = shutil.which('xvfb-run')
        if not xvfb:
            raise RuntimeError('Workbench previews on headless Linux require xvfb-run.')
        command = [xvfb, '-a', *command]
    subprocess.run(command, check=True)
    checks = json.loads((output / 'result/fbx_uv_checks.json').read_text(encoding='utf-8'))
    if checks.get('status') != 'passed':
        raise RuntimeError('FBX round-trip validation failed')
    print(json.dumps({'status': 'passed', 'output': str(output / 'result')}))


if __name__ == '__main__':
    main()
