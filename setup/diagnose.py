"""Read-only migration readiness report. Never exports credentials."""
import argparse,json,shutil,socket,subprocess,sys,tomllib,importlib.metadata as md
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',type=Path);p.add_argument('--config',type=Path);a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    report={'python':sys.version.split()[0],'python_tested_minor':sys.version_info[:2]==(3,12),'skill_source_present':(root/'.agents/skills/photo-to-ornament/SKILL.md').is_file(),'geometry_dependencies':{},'blender':None,'blender_addon_tcp':False,'mcp':{}}
    for name in ['numpy','scipy','scikit-image','shapely','triangle','trimesh','Pillow']:
        try:report['geometry_dependencies'][name]=md.version(name)
        except md.PackageNotFoundError:report['geometry_dependencies'][name]=None
    executable=str(a.blender) if a.blender else shutil.which('blender')
    if executable and Path(executable).is_file():
        result=subprocess.run([executable,'--version'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        report['blender']={'path':executable,'version_header':result.stdout.splitlines()[0] if result.stdout else '', 'exit_code':result.returncode}
    try:
        with socket.create_connection(('127.0.0.1',9876),timeout=1):report['blender_addon_tcp']=True
    except OSError:pass
    config=a.config if a.config else Path.home()/'.codex/config.toml'
    if config.is_file():
        settings=tomllib.loads(config.read_text(encoding='utf-8-sig')).get('mcp_servers',{})
        report['mcp']['hyper3d_url_correct']=settings.get('hyper3d',{}).get('url')=='https://api.hyper3d.com/api/mcp'
        command=settings.get('blender',{}).get('command')
        report['mcp']['blender_configured']=bool(command)
        report['mcp']['blender_command_available']=bool(command and (Path(command).is_file() or shutil.which(command)))
    report['authentication_verified']=False
    report['next']='Verify live MCP tools in Codex and authenticate Hyper3D on this host if required. TCP presence alone is not MCP verification.'
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
