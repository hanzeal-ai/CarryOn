"""Local service directory catalog. Liveness always comes from authenticated services."""
import concurrent.futures
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from .paths import private_dir, save_json, state_dir, default_codex_home, command


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


def register(directory, *, name=None, port=None, codex_home=None, backend=None):
    directory=str(Path(directory).expanduser().resolve())
    if name is not None and (not isinstance(name,str) or not name.strip() or len(name)>100):raise ValueError('工作区名称应为 1–100 个字符')
    if port is not None and (type(port) is not int or not 0<=port<=65535):raise ValueError('端口无效')
    root=private_dir(catalog_directory())
    with (root/'services.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=records();previous=data.get(directory,{})
        if previous.get('backend') == 'app-server':
            if codex_home is not None and str(Path(codex_home).expanduser().resolve()) != previous['codexHome']:
                raise ValueError('独立工作区的 Codex 目录不能更改')
            if backend not in (None, 'app-server'): raise ValueError('独立工作区的后端不能更改')
        entry={**previous,'removed':False,'directory':directory,'name':name.strip() if name is not None else previous.get('name',Path(directory).name)}
        if port is not None:entry['port']=port
        if codex_home is not None:entry['codexHome']=str(Path(codex_home).expanduser().resolve())
        if backend is not None:
            if backend not in ('desktop-ipc','app-server'): raise ValueError('工作区后端无效')
            entry['backend']=backend
        if 'backend' not in entry: entry['backend'] = workspace_backend(directory)
        if entry['backend'] == 'app-server':
            entry['codexHome'] = str(workspace_codex_home(directory, entry.get('codexHome')))
            for other, saved in data.items():
                if other != directory and not saved.get('removed') and saved.get('codexHome') and Path(saved['codexHome']).resolve() == Path(entry['codexHome']):
                    raise ValueError('此 Codex 目录已被其他工作区使用，请选择独立目录')
        elif 'codexHome' not in entry:
            entry['codexHome'] = str(workspace_codex_home(directory))
        data[directory]=entry
        save_json(root/'services.json',{'version':1,'services':data})
    return entry


def remove(directory):
    """Remove a catalog registration, retaining service files and Codex data."""
    directory = str(Path(directory).expanduser().resolve())
    root = private_dir(catalog_directory())
    workspace = private_dir(Path(directory))
    with (workspace/'launcher.lock').open('a+') as launcher, (workspace/'server.lock').open('a+') as service:
        fcntl.flock(launcher, fcntl.LOCK_EX)
        try: fcntl.flock(service, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('请先停止此工作区的服务，再删除工作区') from None
        with (root/'services.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if running(Path(directory)):
                raise ValueError('请先停止此工作区的服务，再删除工作区')
            data = records()
            # Tombstone prevents implicit discovery from restoring a removed entry.
            data[directory] = {**data.get(directory, {}), 'directory': directory, 'removed': True}
            save_json(root/'services.json', {'version': 1, 'services': data})
    return {'removed': True, 'directory': directory}


def inspect(entry):
    directory=Path(entry['directory'])
    info=running(directory)
    if info:
        return {**entry,'running':True,'state':'running','service':info,
                'port':info['port'],'codexHome':info['codexHome'], 'backend':info.get('backend', 'desktop-ipc')}
    return {**entry, 'backend':workspace_backend(directory), 'codexHome':str(workspace_codex_home(directory, entry.get('codexHome'))),
            'running':False,'state':'unavailable' if (directory/'service.json').exists() else 'stopped','service':None}


def list_services(current=None):
    known=records()
    candidates={str(state_dir().resolve())}
    if current is not None:candidates.add(str(Path(current).resolve()))
    extra={path:{'directory':path,'name':'默认工作区' if Path(path)==Path.home()/'Library/Application Support/CarryOn' else Path(path).name}
           for path in candidates if path not in known}
    # Authenticate registered and explicitly selected service directories.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows=list(pool.map(inspect,[entry for entry in known.values() if not entry.get('removed')]+list(extra.values())))
    result=[]
    for row in rows:
        if row['running'] and row['directory'] not in known:
            register(row['directory'],name=row['name'],port=row['port'],codex_home=row['codexHome'])
        if row['directory'] in known or row['running'] or row['directory']==str(Path(current or state_dir()).resolve()):result.append(row)
    return {'services':sorted(result,key=lambda row:(not row['running'],row['name'],row['directory']))}


def workspace_backend(directory):
    directory = Path(directory).expanduser().resolve()
    saved = records().get(str(directory), {}).get('backend')
    if saved == 'desktop-ipc': return 'desktop-ipc'
    if saved == 'app-server': return saved
    return 'desktop-ipc' if directory == state_dir().resolve() else 'app-server'


def workspace_codex_home(directory, configured=None):
    """Resolve workspace storage while keeping independent Codex homes isolated."""
    directory = Path(directory).expanduser().resolve()
    home = Path(configured).expanduser().resolve() if configured else None
    if workspace_backend(directory) == 'desktop-ipc':
        return home or default_codex_home()
    shared = {default_codex_home(), (Path.home() / '.codex').resolve()}
    result = (directory / 'codex-home').resolve() if home is None or home in shared else home
    if result in shared: raise ValueError('独立工作区目录不能链接到默认 Codex 目录')
    return result



def call(directory, path, body=None, timeout=5):
    info = json.loads((directory/'service.json').read_text())
    port = info['port']
    if type(port) is not int or not 1 <= port <= 65535: raise ValueError('服务端口记录无效')
    token = (directory/'token').read_text().strip()
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api'+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization':'Bearer '+token, 'Content-Type':'application/json'})
    # Never pass pairing credentials through a system HTTP proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.load(response)


def running(directory):
    try:
        expected = json.loads((directory/'service.json').read_text())
        actual = call(directory, '/service')
        return actual if actual.get('instanceId') == expected.get('instanceId') else None
    except (OSError, ValueError, KeyError): return None


def open_console(directory, info):
    token = (directory/'token').read_text().strip()
    url = f"http://127.0.0.1:{info['port']}/example.html#token={token}"
    if not webbrowser.open(url):
        print('无法自动打开浏览器，请在本机打开：'+url)


def start(args):
    directory = private_dir(args.state_dir)
    args.codex_home = workspace_codex_home(directory, args.codex_home)
    import fcntl
    with (directory/'launcher.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = running(directory)
        if info is None:
            with (directory/'server.log').open('ab') as log:
                env = dict(os.environ)
                if not getattr(sys, 'frozen', False):
                    env['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent)
                process = subprocess.Popen(command()+['serve','--state-dir',str(directory),
                    '--port',str(args.port),'--codex-home',str(args.codex_home)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                    cwd=str(directory), env=env)
            deadline = time.monotonic()+20
            while time.monotonic()<deadline:
                info = running(directory)
                if info: break
                if process.poll() is not None: break
                time.sleep(.15)
            if not info:
                raise ValueError('启动失败，请检查端口是否占用以及日志：'+str(directory/'server.log'))
        bridge = call(directory, '/bridge', {'enabled': True}, timeout=20)
    print(f"CarryOn {info['version']} 本地服务已启动：http://127.0.0.1:{info['port']}/")
    print('工作区 app-server 已启动，尚未完成 Codex 登录。' if bridge.get('accountReady') is False else
          'Codex 已连接' if bridge.get('enabled') else bridge.get('connectionError') or '正在等待 Codex 连接。')
    if not args.no_open: open_console(directory, info)
    return 0
