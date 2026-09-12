#!/usr/bin/python3.11
"""Forced SSH command. Installs only this service, without root shell access."""
import fcntl
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

BASE=Path('/opt/carryon')
UNIT='carryon-gateway.service'

def validate_wheel(data):
    archive=zipfile.ZipFile(io.BytesIO(data))
    entries=archive.infolist()
    if sum(e.file_size for e in entries)>30*1024*1024:raise ValueError('Wheel too large')
    names=set()
    for entry in entries:
        path=PurePosixPath(entry.filename)
        if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename or not path.parts
            or not (path.parts[0]=='carryon' or re.fullmatch(r'carryon_local-[0-9.]+\.dist-info',path.parts[0]))
            or (entry.external_attr>>16)&0o170000==0o120000 or entry.filename in names):
            raise ValueError('Unsafe wheel member')
        names.add(entry.filename)
    if 'carryon/gateway.py' not in names:raise ValueError('Gateway missing')
    return archive

def switch(target):
    link=BASE/'current.next'
    if link.is_symlink():link.unlink()
    link.symlink_to(target)
    os.replace(link,BASE/'current')

def systemctl(action):
    subprocess.run(['/usr/bin/sudo','-n','/usr/bin/systemctl',action,UNIT],check=True,timeout=30)

def healthy(release):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(30):
        try:
            with opener.open('http://127.0.0.1:8780/healthz',timeout=2) as response:
                if json.load(response).get('release')==release:return True
        except (OSError,ValueError):pass
        time.sleep(1)
    return False

def main():
    release=os.environ.get('SSH_ORIGINAL_COMMAND','')
    if not re.fullmatch('[0-9a-f]{40}',release):raise ValueError('Expected exact Git commit SHA')
    data=sys.stdin.buffer.read(10*1024*1024+1)
    if len(data)>10*1024*1024:raise ValueError('Upload too large')
    archive=validate_wheel(data)
    with (BASE/'deploy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        destination=BASE/'releases'/release
        if destination.exists():
            raise ValueError('Release already exists; deploy a new commit or use the documented operator rollback')
        temporary=Path(tempfile.mkdtemp(prefix='.prepare-',dir=BASE/'releases'))
        try:
            archive.extractall(temporary)
            (temporary/'release.env').write_text('CARRYON_RELEASE='+release+'\n')
            for path in temporary.rglob('*'):path.chmod(0o755 if path.is_dir() else 0o644)
            temporary.chmod(0o755)
            subprocess.run(['/usr/bin/python3.11','-B','-c','import carryon.gateway'],cwd=temporary,check=True,timeout=15)
            temporary.rename(destination)
        finally:
            if temporary.exists():shutil.rmtree(temporary)
        current=BASE/'current'
        previous=current.resolve() if current.is_symlink() else None
        previous_release=previous.name if previous else None
        switch(destination)
        try:
            systemctl('restart')
            if not healthy(release):raise RuntimeError('Health check failed')
        except Exception:
            if previous:
                switch(previous);systemctl('restart')
                if not healthy(previous_release):raise RuntimeError('Rollback health check failed; operator action required')
            else:
                systemctl('stop');current.unlink()
            raise
        if previous:
            (BASE/'previous').write_text(str(previous)+'\n')
        print('DEPLOYED '+release)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Deploy failed: '+str(exc),file=sys.stderr);sys.exit(1)
