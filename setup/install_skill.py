"""Install only this skill, preserving and backing up any previous installation."""
import argparse,datetime,json,shutil
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['user','project'],default='user');p.add_argument('--destination',type=Path);p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    package=Path(__file__).resolve().parents[1];source=package/'.agents/skills/photo-to-ornament'
    target=(a.destination if a.destination else (Path.home() if a.scope=='user' else package)/'.agents/skills/photo-to-ornament').expanduser().resolve()
    if target.name!='photo-to-ornament':raise ValueError('Destination must be the photo-to-ornament folder')
    if target==source.resolve():
        print(json.dumps({'status':'already_available_in_project','destination':str(target)}));return
    files=[x for x in source.rglob('*') if x.is_file() and '__pycache__' not in x.parts]
    if not (source/'SKILL.md').is_file():raise FileNotFoundError('Skill source missing')
    result={'source':str(source),'destination':str(target),'files':len(files),'dry_run':a.dry_run,'other_settings_modified':False}
    if a.dry_run:print(json.dumps(result,ensure_ascii=False));return
    if target.exists():
        backup=package/'backups'/('photo-to-ornament-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(target,backup,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        result['backup']=str(backup)
    for src in files:
        dst=target/src.relative_to(source);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    result['status']='installed';print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
