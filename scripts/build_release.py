#!/usr/bin/env python3
"""Build on the target Mac. No installation, account changes or publishing."""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from connectnow import __version__


def run(*args):subprocess.run(args,cwd=ROOT,check=True)


def main():
    if sys.platform!='darwin':raise SystemExit('请在目标 macOS 架构上构建')
    out=ROOT/'dist';work=ROOT/'build';out.mkdir(exist_ok=True);work.mkdir(exist_ok=True)
    assets=['example.html','app.js','notification-client.js','client.js','timeline.js','operations.js','cloud-console-client.js','style.css','mobile.css','mobile-ui.js']
    common=[sys.executable,'-m','PyInstaller','--noconfirm','--log-level','WARN',
        '--paths',str(ROOT),'--collect-data','connectnow','--collect-submodules','connectnow',
        '--workpath',str(work),'--specpath',str(work),'--distpath',str(out)]
    for name in assets:common += ['--add-data',str(ROOT/name)+':connectnow/web']
    identity=os.environ.get('CONNECTNOW_SIGN_IDENTITY')
    if identity:common+=['--codesign-identity',identity]
    run(*common,'--name','connectnow','--onedir',str(ROOT/'packaging/cli_entry.py'))
    # Recreate the generated bundle before replacing its executable with the native UI.
    if (out/'ConnectNow.app').exists():shutil.rmtree(out/'ConnectNow.app')
    run(*common,'--name','ConnectNow','--windowed','--osx-bundle-identifier','local.connectnow.desktop',str(ROOT/'packaging/cli_entry.py'))
    app=out/'ConnectNow.app'
    executable=app/'Contents/MacOS/ConnectNow'
    executable.rename(executable.with_name('connectnow-service'))
    run('xcrun','swiftc','-parse-as-library','-swift-version','5','-target',platform.machine()+'-apple-macos13.0',
        *map(str,sorted((ROOT/'desktop').glob('*.swift'))),'-o',str(executable))
    import plistlib
    info_path=app/'Contents/Info.plist'
    info=plistlib.loads(info_path.read_bytes());info['LSMinimumSystemVersion']='13.0'
    info['CFBundleShortVersionString']=__version__;info['CFBundleVersion']=__version__
    info_path.write_bytes(plistlib.dumps(info))
    run('codesign','--force','--deep','--sign',identity or '-',str(app))
    arch=platform.machine();prefix=f'ConnectNow-{__version__}-macos-{arch}'
    shutil.copy2(ROOT/'scripts/install.sh',out/'connectnow/install.sh')
    shutil.copy2(ROOT/'README.md',out/'connectnow/README.md')
    shutil.copytree(ROOT/'docs',out/'connectnow/docs',dirs_exist_ok=True)
    shutil.copy2(ROOT/'docs/INSTALL.md',out/'connectnow/安装说明.md')
    run('tar','-czf',str(out/(prefix+'-cli.tar.gz')),'-C',str(out),'connectnow')
    stage=work/'dmg';stage.mkdir(exist_ok=True)
    if (stage/'ConnectNow.app').exists():shutil.rmtree(stage/'ConnectNow.app')
    shutil.copytree(out/'ConnectNow.app',stage/'ConnectNow.app',symlinks=True)
    if not (stage/'Applications').is_symlink():(stage/'Applications').symlink_to('/Applications')
    shutil.copy2(ROOT/'docs/INSTALL.md',stage/'安装说明.md')
    dmg=out/(prefix+'.dmg')
    if dmg.exists():dmg.unlink()
    run('hdiutil','create','-volname','ConnectNow','-srcfolder',str(stage),'-format','UDZO',str(dmg))
    run(sys.executable,'-m','build','--outdir',str(out))
    artifacts=sorted(p for p in out.iterdir() if p.suffix in ('.dmg','.whl') or p.name.endswith('.tar.gz'))
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts))
    print(json.dumps({'version':__version__,'architecture':arch,'developerSigned':bool(identity),
        'notarized':False,'artifacts':[str(p) for p in artifacts]},indent=2))

if __name__=='__main__':main()
