"""Maintain the installed CLI entry point; restart running shared services after a verified update."""
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from . import __version__

REPOSITORY = 'hanzeal-ai/CarryOn'
LATEST = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_ARCHIVE = 512 * 1024 * 1024


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('发布版本格式无效，仅支持正式版本')
    return tuple(map(int, value.removeprefix('v').split('.')))


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':raise ValueError('拒绝非 HTTPS 下载跳转')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, target, limit):
    if urlsplit(url).scheme != 'https':raise ValueError('下载地址必须为 HTTPS')
    opener = urllib.request.build_opener(HTTPSRedirect())
    request = urllib.request.Request(url, headers={'User-Agent':'CarryOn-Updater', 'Accept':'application/vnd.github+json'} if url == LATEST else {'User-Agent':'CarryOn-Updater'})
    try:
        with opener.open(request, timeout=30) as response, target.open('wb') as out:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > limit:raise ValueError('下载内容超过大小限制')
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        code=exc.code;exc.close()
        if code == 404:raise ValueError('官方发布或安装包暂不可用；可使用 update --package 本地安装包') from None
        raise ValueError(f'下载失败（HTTP {code}），未修改现有安装') from None


def latest(directory):
    metadata=directory/'release.json';download(LATEST,metadata,1024*1024)
    data=json.loads(metadata.read_bytes())
    if not isinstance(data,dict) or data.get('draft') is not False or data.get('prerelease') is not False:
        raise ValueError('未找到可用的正式发布')
    tag=data.get('tag_name');version(tag)
    arch=platform.machine()
    if sys.platform!='darwin' or arch not in ('arm64','x86_64'):raise ValueError('仅支持 macOS arm64/x86_64 独立 CLI')
    name=f'CarryOn-{tag.removeprefix("v")}-macos-{arch}-cli.tar.gz'
    assets={}
    entries=data.get('assets')
    if not isinstance(entries,list) or any(not isinstance(asset,dict) for asset in entries):raise ValueError('发布资源列表无效')
    for asset in entries:
        if asset.get('name') in (name,'SHA256SUMS'):
            url=asset.get('browser_download_url','')
            if not isinstance(url,str) or not url.startswith(f'https://github.com/{REPOSITORY}/releases/download/'):
                raise ValueError('发布资源不属于官方仓库')
            if asset['name'] in assets:raise ValueError('发布资源名称重复')
            assets[asset['name']]=url
    if len(assets)!=2:raise ValueError('此发布缺少当前架构 CLI 安装包或 SHA256SUMS')
    return tag.removeprefix('v'),name,assets


def checksum(package):
    sums=package.parent/'SHA256SUMS'
    if not sums.is_file():raise ValueError('安装包同目录缺少 SHA256SUMS')
    if sums.stat().st_size>1024*1024:raise ValueError('校验文件过大')
    matches=[]
    for line in sums.read_text().splitlines():
        parts=line.split(None,1)
        if len(parts)==2 and parts[1].lstrip('*')==package.name:matches.append(parts[0])
    if len(matches)!=1 or not re.fullmatch('[0-9a-fA-F]{64}',matches[0]):raise ValueError('找不到唯一有效的安装包校验值')
    digest=hashlib.sha256()
    with package.open('rb') as source:
        while chunk:=source.read(1024*1024):digest.update(chunk)
    if digest.hexdigest()!=matches[0].lower():raise ValueError('安装包 SHA256 校验失败，未修改现有安装')
    return digest.hexdigest()


def extract(package, directory):
    """Extract regular files first, then confined symlinks; never follow archive links."""
    root=directory/'carryon';seen=set();links=[];size=0
    try:
        with tarfile.open(package,'r:gz') as archive:
            for number,member in enumerate(archive):
                if number>=10000:raise ValueError('安装包条目数量过多')
                path=PurePosixPath(member.name)
                if member.isfile():
                    size+=member.size
                    if size>1024*1024*1024:raise ValueError('安装包展开后过大')
                # BSD tar includes AppleDouble metadata beside the bundle root.
                if path.parts==('._carryon',) and member.isfile():continue
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='carryon':
                    raise ValueError('安装包路径或条目数量无效')
                if path.name.startswith('._') and member.isfile():continue
                key=str(path).casefold()
                if key in seen:raise ValueError('安装包包含重复路径')
                seen.add(key)
                target=directory.joinpath(*path.parts)
                if member.isdir():target.mkdir(parents=True,exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as source, target.open('xb') as out:shutil.copyfileobj(source,out)
                    target.chmod(member.mode & 0o777)
                elif member.issym():links.append((target,member.linkname))
                else:raise ValueError('安装包包含不支持的文件类型')
            for target,link in links:
                if PurePosixPath(link).is_absolute():raise ValueError('安装包包含外部链接')
                destination=(target.parent/link).resolve()
                if not destination.is_relative_to(root.resolve()):raise ValueError('安装包链接超出程序目录')
                target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(link)
            for target,_ in links:
                if not target.resolve().is_relative_to(root.resolve()):raise ValueError('安装包链接超出程序目录')
    except (tarfile.TarError,RuntimeError) as exc:raise ValueError('安装包损坏或包含无效链接') from exc
    binary=next((root/name for name in ('carryon',) if (root/name).is_file()),None)
    if binary is None or binary.is_symlink() or not os.access(binary,os.X_OK) or not (root/'_internal').is_dir():
        raise ValueError('不是完整的 CarryOn CLI 安装包')
    return binary


def current_link():
    if not getattr(sys,'frozen',False):raise ValueError('此命令用于独立 CLI 安装；源码或 Python 包请使用对应的安装方式')
    executable=Path(sys.executable).resolve()
    for candidate in (sys.argv[0],shutil.which('carryon')):
        if candidate:
            link=Path(candidate).absolute()
            if link.is_symlink() and link.samefile(executable) and link.lstat().st_uid==os.getuid():return link
    raise ValueError('找不到当前 CLI 的安装符号链接；请通过已安装的 carryon 命令运行')


@contextlib.contextmanager
def installation_lock(link):
    with (link.parent/'.carryon-maintenance.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield


def replace_link(link, target):
    temporary=link.with_name('.carryon-'+secrets.token_hex(8))
    try:
        temporary.symlink_to(target);os.replace(temporary,link)
    finally:
        if temporary.is_symlink():temporary.unlink()


def service_snapshots():
    from .services import list_services
    from .services import call
    snapshots=[]
    for row in list_services()['services']:
        if not row['running']:continue
        directory=Path(row['directory'])
        status=call(directory,'/status')
        # Each service may have been launched by a different CLI or desktop release.
        executable=subprocess.check_output(['ps','-p',str(row['service']['pid']),'-o','comm='],text=True,timeout=5).strip()
        if (not Path(executable).is_absolute() or not Path(executable).is_file()
                or Path(executable).name not in ('carryon','carryon-service')):
            raise ValueError('无法确定后台原程序，未停止服务：'+str(directory))
        snapshots.append({**row,'status':status,'executable':executable})
    return snapshots


def stop_service(row, expected):
    from .services import call, running
    directory=Path(row['directory']);info=running(directory)
    if not info:return
    if info['instanceId']!=expected:raise ValueError('后台实例已改变：'+str(directory))
    call(directory,'/service/stop',{})
    deadline=time.monotonic()+20
    # Wait for final cleanup, not merely the HTTP listener to stop responding.
    while (directory/'service.json').exists():
        try:record=json.loads((directory/'service.json').read_text())
        except FileNotFoundError:break
        if record.get('instanceId')!=expected:raise ValueError('后台实例已改变：'+str(directory))
        if time.monotonic()>=deadline:raise ValueError('后台停止超时：'+str(directory))
        time.sleep(.1)


def start_service(row, executable, expected_version=None):
    from .services import call, running
    directory=Path(row['directory'])
    if running(directory):raise ValueError('已有其他后台启动：'+str(directory))
    with (directory/'server.log').open('ab') as log:
        process=subprocess.Popen([str(executable),'serve','--state-dir',str(directory),
            '--port',str(row['port']),'--codex-home',row['codexHome']],stdin=subprocess.DEVNULL,
            stdout=log,stderr=log,start_new_session=True,cwd=str(directory))
    try:
        deadline=time.monotonic()+25
        while True:
            info=running(directory)
            if info:
                if info['pid']!=process.pid:raise ValueError('后台被其他启动器接管：'+str(directory))
                if expected_version and info['version']!=expected_version:raise ValueError('后台版本验证失败')
                break
            if process.poll() is not None or time.monotonic()>=deadline:raise ValueError('后台启动失败：'+str(directory))
            time.sleep(.15)
        status=row['status']
        if status['enabled'] or status.get('controllerId'):
            call(directory,'/bridge',{'enabled':True})
        if status.get('controllerId'):call(directory,'/controller',{'threadId':status['controllerId']})
        call(directory,'/bridge',{'enabled':status['enabled']})
        restored=call(directory,'/status')
        if restored['enabled']!=status['enabled'] or restored.get('controllerId')!=status.get('controllerId'):
            raise ValueError('后台状态恢复失败：'+str(directory))
        return info['instanceId']
    except BaseException:
        # Only signal the child we created, never an arbitrary recorded PID.
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:pass
        raise


def activate(target, link, previous, release, rows):
    from .services import running
    touched=[];started={};switched=False
    try:
        for row in rows:
            touched.append(row)
            stop_service(row,row['service']['instanceId'])
        if not link.is_symlink() or os.readlink(link)!=previous:raise ValueError('CLI 安装入口已改变，取消更新')
        replace_link(link,target);switched=True
        for row in rows:started[row['directory']]=start_service(row,target,release)
    except BaseException as exc:
        errors=[]
        if switched:
            try:
                if not link.is_symlink() or os.readlink(link)!=str(target):raise ValueError('CLI 入口已被其他程序修改')
                replace_link(link,previous)
            except Exception as error:errors.append(str(error))
        for row in reversed(touched):
            try:
                info=running(Path(row['directory']))
                if info and info['instanceId']==row['service']['instanceId']:continue
                if row['directory'] in started:stop_service(row,started[row['directory']])
                start_service(row,row['executable'],row['service']['version'])
            except Exception as error:errors.append(str(error))
        detail='；恢复未完成：'+'；'.join(errors) if errors else '；已恢复原入口和原运行服务'
        raise ValueError('更新失败：'+str(exc)+detail) from exc


def install(package, link, releases, restart=False):
    match=re.fullmatch(r'CarryOn-(\d+\.\d+\.\d+)-macos-(arm64|x86_64)-cli\.tar\.gz',package.name)
    if not match or sys.platform!='darwin' or match[2]!=platform.machine():raise ValueError('安装包名称或架构与本机不匹配')
    if package.stat().st_size>MAX_ARCHIVE:raise ValueError('安装包过大')
    digest=checksum(package)
    releases.mkdir(parents=True,exist_ok=True,mode=0o700)
    with installation_lock(link):
        if not link.is_symlink():raise ValueError('CLI 安装入口已改变，取消更新')
        previous=os.readlink(link)
        with tempfile.TemporaryDirectory(prefix='.update-',dir=releases) as temp:
            binary=extract(package,Path(temp))
            result=subprocess.run([str(binary),'--version'],capture_output=True,text=True,timeout=20)
            if result.returncode!=0 or result.stdout.strip()!=match[1]:raise ValueError('新 CLI 版本验证失败，未修改现有安装')
            destination=releases/(match[1]+'-'+digest[:12]+'-'+secrets.token_hex(4))
            os.rename(binary.parent,destination)
            target=destination/binary.name
            rows=service_snapshots() if restart else []
            activate(target,link,previous,match[1],rows)
    return target,previous


def update(package=None, check=False):
    if package is not None and check:raise ValueError('--check 与 --package 不能同时使用')
    try:
        with tempfile.TemporaryDirectory(prefix='carryon-download-') as temp:
            if package is None:
                release,name,assets=latest(Path(temp))
                if version(release)<=version(__version__):print('当前 CLI 版本不低于最新正式版本：'+__version__);return 0
                print(f'当前版本：{__version__}；最新版本：{release}')
                if check:return 0
                link=current_link()
                package=Path(temp)/name
                download(assets[name],package,MAX_ARCHIVE)
                download(assets['SHA256SUMS'],package.parent/'SHA256SUMS',1024*1024)
            else:link=current_link();package=package.expanduser().resolve()
            target,previous=install(package,link,Path.home()/'.local/share/carryon-releases',restart=True)
            print('CLI 已更新：'+str(target))
            print('原版本保留：'+previous)
            print('更新前运行中的后台已自动重启，原端口、目录和桥接状态已恢复；未启动的服务保持关闭。')
            return 0
    except (subprocess.SubprocessError,tarfile.TarError) as exc:raise ValueError('更新准备失败，现有 CLI 入口未切换') from exc


def uninstall():
    link=current_link()
    with installation_lock(link):
        # Recheck after taking the shared update/uninstall lock.
        if current_link()!=link:raise ValueError('CLI 安装入口已改变，取消卸载')
        target=link.resolve();link.unlink()
    print('已移除 CLI 命令入口：'+str(link))
    print('桌面端、后台服务、绑定和配置保持不变。')
    print('程序版本目录保留，供后台使用和恢复：'+str(target.parent))
    return 0
