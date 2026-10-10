"""Install this self-contained skill and back up an existing installation."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil

EXCLUDED = {'.git', '.venv', '.venv-studio', '__pycache__', 'runs', 'backups', '.pytest_cache'}

def ignore(directory, names):
    return [n for n in names if n in EXCLUDED or n.endswith(('.pyc', '.pyo'))]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    codex_dir = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
    target = (args.destination or codex_dir / 'skills/photo-to-ornament').expanduser().absolute()
    if target.is_symlink():
        parser.error('Destination must not be a symlink')
    target = target.resolve()
    if target.name != 'photo-to-ornament':
        parser.error('Destination folder must be named photo-to-ornament')
    if not (source / 'SKILL.md').is_file():
        parser.error('Skill source missing')
    if target == source:
        print(json.dumps({'status': 'already_available', 'destination': str(target)}))
        return
    if source in target.parents or target in source.parents:
        parser.error('Source and destination must not contain each other')
    result = {'source': str(source), 'destination': str(target), 'dry_run': args.dry_run}
    if args.dry_run:
        print(json.dumps(result, ensure_ascii=False))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    stage = target.parent / ('.photo-to-ornament-stage-' + stamp)
    backup = target.parent.parent / 'skill-backups' / ('photo-to-ornament-' + stamp)
    shutil.copytree(source, stage, ignore=ignore)
    if target.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        target.rename(backup)
        result['backup'] = str(backup)
    try:
        stage.rename(target)
    except OSError:
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise
    result['status'] = 'installed'
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
