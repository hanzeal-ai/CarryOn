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
        bridge = call(directory, '/bridge', {'enabled': True}, timeout=20)
    print(f"CarryOn {info['version']} 本地服务已启动：http://127.0.0.1:{info['port']}/")
    print('Codex 已连接' if bridge.get('enabled') else '正在等待 Codex App；打开并登录后将自动连接。')
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
    parser = argparse.ArgumentParser(prog='carryon', description='启动本地 Codex 控制台与云端设备通道')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command')
    init = sub.add_parser('init', help='初始化工作区并使用手机扫码绑定')
    init.add_argument('--state-dir', type=Path, default=state_dir())
    init.add_argument('--url')
    init.add_argument('--permissions', help='逗号分隔的工作区成员权限；省略时交互选择')
    init.add_argument('--input-json', action='store_true')
    members = sub.add_parser('members', help='管理当前工作区的使用者与权限')
    members.add_argument('action', nargs='?', choices=('list','grant','revoke','invite'), default='list')
    members.add_argument('--state-dir', type=Path, default=state_dir())
    members.add_argument('--binding-id')
    members.add_argument('--account-id')
    members.add_argument('--permissions', help='逗号分隔：view,create,send,stop,edit,files,approve')
    members.add_argument('--source-state-dir', type=Path, help='复用同一云端的已确认账号所在工作区')
    members.add_argument('--input-json', action='store_true')
    for name in ('start','serve','open','status','stop','doctor','cloud','bridge','standby','controller','notifications','services'):
        p = sub.add_parser(name)
        p.add_argument('--state-dir', type=Path, default=state_dir())
        if name in ('start','serve','doctor'):
            p.add_argument('--codex-home', type=Path)
        if name in ('start','serve'): p.add_argument('--port', type=int)
        if name == 'start':
            p.add_argument('--no-open', action='store_true', default=True)
            p.add_argument('--open', dest='no_open', action='store_false')
        if name=='services':
            p.add_argument('action',choices=['list','add'])
            p.add_argument('--name')
            p.add_argument('--port',type=int,default=0)
            p.add_argument('--codex-home',type=Path,default=Path.home()/'.codex')
        if name in ('bridge','standby'):p.add_argument('action',choices=['on','off','status'])
        if name == 'controller':
            p.add_argument('action',choices=['set','status'])
            p.add_argument('--thread-id')
        if name == 'notifications':
            p.add_argument('action',choices=['status','set'])
            for kind in ('message','done','failed','approval'):p.add_argument('--'+kind,action=argparse.BooleanOptionalAction)
        if name == 'cloud':
            p.add_argument('action', choices=['connect','pair','disconnect','status','control','link-status','account','qr'])
            p.add_argument('account_action',nargs='?',choices=['status','setup','change'])
            p.add_argument('--input-json',action='store_true',help='账号设置从标准输入读取 JSON，不将密码放入命令行')
            p.add_argument('--url', help='云端控制台 HTTPS 地址；connect 发起申请后由云端确认')
            p.add_argument('--device-id', help='使用已有设备凭证连接时的设备 ID')
            p.add_argument('--binding-id',help='要断开的云端绑定 ID；多个绑定时必填')
            p.add_argument('--token-file', type=Path)
            permission=p.add_mutually_exclusive_group()
            permission.add_argument('--allow-control', action='store_true', help='授权此网关投递、编辑、设置与审批等会话操作')
            permission.add_argument('--read-only',action='store_true',help='将已有云端绑定设为只读')
            p.add_argument('--dev-local', action='store_true', help='仅用于本机 ws:// 网关测试')
    for name in ('update','uninstall'):
        p=sub.add_parser(name,help='更新 CLI' if name=='update' else '移除 CLI 命令入口，保留共享服务和数据')
        if name=='update':
            p.add_argument('--check',action='store_true',help='仅检查官方最新发布，不安装')
            p.add_argument('--package',type=Path,help='使用本地 CLI tar.gz（同目录需有 SHA256SUMS）')
    args = parser.parse_args(argv if argv is not None else (sys.argv[1:] or ['start']))
    if args.command is None: parser.print_help(); return 0
    if hasattr(args,'state_dir'):args.state_dir = args.state_dir.expanduser().resolve()
    try:
        if args.command == 'init':
            from .onboarding import command as initialize
            return initialize(args)
        if args.command == 'members':
            from .members_cli import command as manage_members
            return manage_members(args)
        if args.command in ('start', 'serve', 'doctor'):
            from .services import records
            saved = records().get(str(args.state_dir), {})
            args.codex_home = (args.codex_home or Path(saved.get('codexHome', Path.home()/'.codex'))).expanduser().resolve()
            if hasattr(args, 'port') and args.port is None:
                args.port = saved.get('port', 8769)
        elif hasattr(args, 'codex_home'):
            args.codex_home = args.codex_home.expanduser().resolve()
        if args.command=='services':
            from .services import list_services, register
            if args.action=='add':
                private_dir(args.state_dir)
                active=running(args.state_dir)
                result=register(args.state_dir,name=args.name,port=active['port'] if active else args.port,
                                codex_home=active['codexHome'] if active else args.codex_home)
            else:result=list_services(args.state_dir)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if args.command in ('update','uninstall'):
            from .maintenance import update, uninstall
            return update(args.package,args.check) if args.command=='update' else uninstall()
        if args.command == 'start': return start(args)
        if args.command == 'serve':
            from .server import run
            run(args.port,args.codex_home,args.state_dir); return 0
        if args.command == 'doctor': return doctor(args)
        if args.command=='cloud' and args.action=='qr':
            if not args.url:raise ValueError('需要 --url 指定云端 HTTPS 地址')
            from .qr_client import command as qr_command
            return qr_command(args)
        if args.command=='cloud' and args.action=='account':
            if not args.account_action or not args.url:raise ValueError('使用 carryon cloud account status|setup|change --url HTTPS地址')
            from .account_client import command as account_command
            return account_command(args)
        info = running(args.state_dir)
        if not info and args.command == 'cloud' and args.action == 'status':
            from .cloud_manager import CloudManager
            print(json.dumps(CloudManager.saved_status(args.state_dir), ensure_ascii=False, indent=2)); return 0
        if args.command == 'status':
            print(json.dumps({'running':bool(info),'service':info,
                'bridge':call(args.state_dir,'/status') if info else None},ensure_ascii=False,indent=2));return 0 if info else 1
        if not info: raise ValueError('服务未运行，请先执行 carryon start')
        if args.command=='notifications':
            updates={kind:getattr(args,kind) for kind in ('message','done','failed','approval') if getattr(args,kind) is not None}
            if args.action=='set' and not updates:raise ValueError('至少指定一个通知开关，例如 --message 或 --no-message')
            result=call(args.state_dir,'/notifications/preferences')
            if args.action=='set':result=call(args.state_dir,'/notifications/preferences',{**result['preferences'],**updates})
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if args.command in ('bridge','standby','controller'):
            if args.command=='controller':
                if args.action=='set' and not args.thread_id:raise ValueError('需要 --thread-id 指定控制会话')
                result=call(args.state_dir,'/controller',{'threadId':args.thread_id}) if args.action=='set' else call(args.state_dir,'/status')
            else:
                path='/bridge' if args.command=='bridge' else '/service/standby'
                if args.action=='status':result=call(args.state_dir,'/status' if args.command=='bridge' else path)
                else:result=call(args.state_dir,path,{'enabled':args.action=='on'},timeout=20)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if args.command == 'open': open_console(args.state_dir,info);return 0
        if args.command == 'stop':
            call(args.state_dir,'/service/stop',{})
            deadline=time.monotonic()+10
            while running(args.state_dir) and time.monotonic()<deadline:time.sleep(.1)
            if running(args.state_dir):raise ValueError('服务尚未退出，请稍后检查状态')
            print('CarryOn 已停止；Codex 已接收的任务不会被撤销。');return 0
        if args.command == 'cloud':
            if args.action=='status': result=call(args.state_dir,'/cloud')
            elif args.action=='link-status':result=call(args.state_dir,'/cloud/link/status',timeout=20)
            elif args.action=='control':
                if not (args.allow_control or args.read_only):raise ValueError('需要 --allow-control 或 --read-only 明确设置权限')
                result=call(args.state_dir,'/cloud/control',{'id':args.binding_id,'control':args.allow_control},timeout=20)
            elif args.action=='disconnect':result=call(args.state_dir,'/cloud',{'enabled':False,'id':args.binding_id})
            elif args.action=='pair':
                from .pairing import redeem
                code=args.token_file.read_text().strip() if args.token_file else getpass.getpass('一次性配对码（不回显）：')
                config=redeem(args.url,code,args.allow_control,args.dev_local)
                result=call(args.state_dir,'/cloud',config,timeout=20)
            elif not args.device_id:
                if not args.url:raise ValueError('需要 --url 指定云端控制台 HTTPS 地址')
                if args.token_file or args.dev_local:
                    raise ValueError('申请连接使用 HTTPS 地址，无需 Token；已有设备凭证连接需要 --device-id')
                result=call(args.state_dir,'/cloud/link/start',{'url':args.url,'control':args.allow_control},timeout=20)
                print('连接申请已提交，请在云端「连接申请」核对并确认。')
                print('核对码：'+result['verification'])
                print('云端链接：'+result['url'])
                print('本地服务将在确认后自动完成绑定；申请有效期为五分钟，请保持本地服务运行。')
                return 0
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
    except KeyboardInterrupt:
        print('已取消当前操作；已保存的配置保留。', file=sys.stderr); return 130


if __name__=='__main__':raise SystemExit(main())
