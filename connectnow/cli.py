"""User-facing lifecycle commands; stop authenticates the service, never a PID."""
import argparse
import getpass
import json
import os
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__
from .paths import state_dir, private_dir, command


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
            if call(directory,'/cloud').get('enabled'):
                try:call(directory,'/bridge',{'enabled':True})
                except (urllib.error.HTTPError,OSError):
                    print('本地服务已启动，但未能自动开启桥接；请打开 Codex 后在页面开启桥接。')
    print(f"ConnectNow {info['version']} 已启动：http://127.0.0.1:{info['port']}/")
    if not args.no_open: open_console(directory, info)
    return 0


def doctor(args):
    sock = args.codex_home/'ipc/ipc.sock'
    try:
        info = sock.stat()
        ipc = stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()
    except OSError: ipc = False
    result = {'version':__version__, 'platform':sys.platform, 'supportedPlatform':sys.platform=='darwin',
        'codexHome':str(args.codex_home), 'ipcSocketAvailable':ipc,
        'databaseAvailable':any(args.codex_home.glob('state_*.sqlite')),
        'stateDirectory':str(args.state_dir), 'service':running(args.state_dir),
        'testedDesktopVersion':'26.901.51231'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ipc and result['supportedPlatform'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog='connectnow', description='启动本地 Codex 控制台与云端设备通道')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command')
    for name in ('start','serve','open','status','stop','doctor','cloud'):
        p = sub.add_parser(name)
        p.add_argument('--state-dir', type=Path, default=state_dir())
        if name in ('start','serve','doctor'):
            p.add_argument('--codex-home', type=Path, default=Path.home()/'.codex')
        if name in ('start','serve'): p.add_argument('--port', type=int, default=8769)
        if name == 'start': p.add_argument('--no-open', action='store_true')
        if name == 'cloud':
            p.add_argument('action', choices=['connect','pair','disconnect','status'])
            p.add_argument('--url')
            p.add_argument('--device-id')
            p.add_argument('--binding-id',help='要断开的云端绑定 ID；多个绑定时必填')
            p.add_argument('--token-file', type=Path)
            p.add_argument('--allow-control', action='store_true', help='授权此网关投递、编辑、设置与审批等会话操作')
            p.add_argument('--dev-local', action='store_true', help='仅用于本机 ws:// 网关测试')
    args = parser.parse_args(argv if argv is not None else (sys.argv[1:] or ['start']))
    if args.command is None: parser.print_help(); return 0
    args.state_dir = args.state_dir.expanduser().resolve()
    if hasattr(args,'codex_home'): args.codex_home=args.codex_home.expanduser().resolve()
    try:
        if args.command == 'start': return start(args)
        if args.command == 'serve':
            from .server import run
            run(args.port,args.codex_home,args.state_dir); return 0
        if args.command == 'doctor': return doctor(args)
        info = running(args.state_dir)
        if args.command == 'status':
            print(json.dumps({'running':bool(info),'service':info,
                'bridge':call(args.state_dir,'/status') if info else None},ensure_ascii=False,indent=2));return 0 if info else 1
        if not info: raise ValueError('服务未运行，请先执行 connectnow start')
        if args.command == 'open': open_console(args.state_dir,info);return 0
        if args.command == 'stop':
            call(args.state_dir,'/service/stop',{})
            deadline=time.monotonic()+10
            while running(args.state_dir) and time.monotonic()<deadline:time.sleep(.1)
            if running(args.state_dir):raise ValueError('服务尚未退出，请稍后检查状态')
            print('ConnectNow 已停止；Codex 已接收的任务不会被撤销。');return 0
        if args.command == 'cloud':
            if args.action=='status': result=call(args.state_dir,'/cloud')
            elif args.action=='disconnect':result=call(args.state_dir,'/cloud',{'enabled':False,'id':args.binding_id})
            elif args.action=='pair':
                from .pairing import redeem
                code=args.token_file.read_text().strip() if args.token_file else getpass.getpass('一次性配对码（不回显）：')
                config=redeem(args.url,code,args.allow_control,args.dev_local)
                result=call(args.state_dir,'/cloud',config,timeout=20)
            else:
                if not args.url or not args.device_id:raise ValueError('需要 --url 和 --device-id')
                token=args.token_file.read_text().strip() if args.token_file else getpass.getpass('设备 Token（不回显）：')
                result=call(args.state_dir,'/cloud',{'enabled':True,'url':args.url,'deviceId':args.device_id,
                    'token':token,'control':args.allow_control,'devLocal':args.dev_local})
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except urllib.error.HTTPError as exc:
        try: message=json.load(exc).get('error','请求失败')
        except (ValueError,OSError):message='请求失败'
        print('错误：'+message,file=sys.stderr);return 1
    except (OSError, ValueError, KeyError) as exc:
        print('错误：'+str(exc),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
