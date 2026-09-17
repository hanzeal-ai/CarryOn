"""Local service directory catalog. Liveness always comes from authenticated services."""
import concurrent.futures
import fcntl
import json
import os
import re
import subprocess
from pathlib import Path
from .paths import private_dir, save_json, state_dir, workspace_codex_home, workspace_backend


def catalog_directory():
    override=os.environ.get('CARRYON_REGISTRY_DIR')
    return Path(override).expanduser().resolve() if override else Path.home()/'Library/Application Support/CarryOn'


def records():
    path=catalog_directory()/'services.json'
    if not path.exists():return {}
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('services'),dict):
        raise ValueError('本机服务目录格式无效，请保留原文件后检查 services.json')
    return data['services']


def register(directory, *, name=None, port=None, codex_home=None):
    directory=str(Path(directory).expanduser().resolve())
    if name is not None and (not isinstance(name,str) or not name.strip() or len(name)>100):raise ValueError('工作区名称应为 1–100 个字符')
    if port is not None and (type(port) is not int or not 0<=port<=65535):raise ValueError('端口无效')
    root=private_dir(catalog_directory())
    with (root/'services.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=records();previous=data.get(directory,{})
        entry={**previous,'removed':False,'directory':directory,'name':name.strip() if name is not None else previous.get('name',Path(directory).name)}
        if port is not None:entry['port']=port
        entry['backend'] = previous.get('backend') or workspace_backend(directory)
        entry['codexHome'] = str(workspace_codex_home(directory, codex_home or previous.get('codexHome')))
        if entry['backend'] == 'app-server':
            for other, saved in data.items():
                if other != directory and not saved.get('removed') and workspace_codex_home(other, saved.get('codexHome')) == Path(entry['codexHome']):
                    raise ValueError('此 Codex 目录已被其他工作区使用，请选择独立目录')
        data[directory]=entry
        save_json(root/'services.json',{'version':1,'services':data})
    return entry


def remove(directory):
    """Remove a catalog registration, retaining service files and Codex data."""
    from .cli import running
    directory = str(Path(directory).expanduser().resolve())
    root = private_dir(catalog_directory())
    with (root/'services.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if running(Path(directory)):
            raise ValueError('请先停止此工作区的服务，再删除工作区')
        data = records()
        # Keep a tombstone so the implicit default/current candidate stays removed.
        data[directory] = {**data.get(directory, {}), 'directory': directory, 'removed': True}
        save_json(root/'services.json', {'version': 1, 'services': data})
    return {'removed': True, 'directory': directory}


def process_directories():
    """Backfill older running releases, without recursively searching user files."""
    try:
        output=subprocess.check_output(['ps','-U',str(os.getuid()),'-o','command='],text=True,timeout=3)
    except (OSError,subprocess.SubprocessError):return set()
    found=set()
    for line in output.splitlines():
        if not re.search(r'(?:^|/|\s)(?:carryon|carryon-service)(?:\s+serve|\.server\s)',line):continue
        match=re.search(r'--state-dir\s+(.+?)(?=\s+--(?:port|codex-home)(?:\s|=)|$)',line)
        if match:
            value=match[1].strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            found.add(str(Path(value).expanduser().resolve()))
    return found


def inspect(entry):
    from .cli import running
    directory=Path(entry['directory'])
    info=running(directory)
    if info:
        return {**entry,'running':True,'state':'running','service':info,
                'port':info['port'],'codexHome':info['codexHome'], 'backend':info.get('backend', 'desktop-ipc')}
    return {**entry, 'backend':workspace_backend(directory), 'codexHome':str(workspace_codex_home(directory, entry.get('codexHome'))),
            'running':False,'state':'unavailable' if (directory/'service.json').exists() else 'stopped','service':None}


def list_services(current=None):
    known=records()
    candidates=process_directories()|{str(state_dir().resolve())}
    if current is not None:candidates.add(str(Path(current).resolve()))
    extra={path:{'directory':path,'name':'默认工作区' if Path(path)==Path.home()/'Library/Application Support/CarryOn' else Path(path).name}
           for path in candidates if path not in known}
    # Authenticate every candidate before treating a discovered process as a service.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows=list(pool.map(inspect,[entry for entry in known.values() if not entry.get('removed')]+list(extra.values())))
    result=[]
    for row in rows:
        if row['running'] and row['directory'] not in known:
            register(row['directory'],name=row['name'],port=row['port'],codex_home=row['codexHome'])
        if row['directory'] in known or row['running'] or row['directory']==str(Path(current or state_dir()).resolve()):result.append(row)
    return {'services':sorted(result,key=lambda row:(not row['running'],row['name'],row['directory']))}
