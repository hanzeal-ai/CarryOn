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
from carryon import __version__


def run(*args):subprocess.run(args,cwd=ROOT,check=True)


def main():
    if sys.platform!='darwin':raise SystemExit('请在目标 macOS 架构上构建')
    out=ROOT/'dist';work=ROOT/'build';out.mkdir(exist_ok=True);work.mkdir(exist_ok=True)
    assets=['logo.svg','favicon.png','apple-touch-icon.png','example.html','app.js','subagents.js','notification-client.js','client.js','timeline.js','operations.js','cloud-console-client.js','console-login.js','qrcode.js','style.css','mobile.css','mobile-ui.js']
    common=[sys.executable,'-m','PyInstaller','--noconfirm','--log-level','WARN',
        '--paths',str(ROOT),'--collect-data','carryon','--collect-submodules','carryon',
        ]
    for name in assets:common += ['--add-data',str(ROOT/name)+':carryon/web']
    identity=os.environ.get('CARRYON_SIGN_IDENTITY')
    if identity:common+=['--codesign-identity',identity]
    run(*common,'--workpath',str(work/'cli'),'--specpath',str(work/'cli'),'--distpath',str(out),
        '--name','carryon','--onedir',str(ROOT/'packaging/cli_entry.py'))
    # Recreate the generated bundle before replacing its executable with the native UI.
    if (out/'CarryOn.app').exists():shutil.rmtree(out/'CarryOn.app')
    # Separate all PyInstaller paths: CarryOn and carryon collide on default APFS.
    app_out=work/'app-dist'
    run(*common,'--workpath',str(work/'app'),'--specpath',str(work/'app'),'--distpath',str(app_out),
        '--name','CarryOn','--windowed','--osx-bundle-identifier','local.carryon.desktop',str(ROOT/'packaging/cli_entry.py'))
    shutil.copytree(app_out/'CarryOn.app',out/'CarryOn.app',symlinks=True)
    app=out/'CarryOn.app'
    executable=app/'Contents/MacOS/CarryOn'
    executable.rename(executable.with_name('carryon-service'))
    run('xcrun','swiftc','-parse-as-library','-swift-version','5','-target',platform.machine()+'-apple-macos13.0',
        *map(str,sorted((ROOT/'desktop').glob('*.swift'))),'-o',str(executable))
    import plistlib
    info_path=app/'Contents/Info.plist'
    info=plistlib.loads(info_path.read_bytes());info['LSMinimumSystemVersion']='13.0'
    info['CFBundleShortVersionString']=__version__;info['CFBundleVersion']=__version__
    info['CFBundleIconFile']='CarryOn.icns'
    for resource in (ROOT/'desktop/Resources').iterdir():
        shutil.copy2(resource,app/'Contents/Resources'/resource.name)
    info_path.write_bytes(plistlib.dumps(info))
    run('codesign','--force','--deep','--sign',identity or '-',str(app))
    arch=platform.machine();prefix=f'CarryOn-{__version__}-macos-{arch}'
    shutil.copy2(ROOT/'scripts/install.sh',out/'carryon/install.sh')
    shutil.copy2(ROOT/'README.md',out/'carryon/README.md')
    shutil.copytree(ROOT/'docs',out/'carryon/docs',dirs_exist_ok=True)
    shutil.copy2(ROOT/'docs/INSTALL.md',out/'carryon/安装说明.md')
    run('tar','-czf',str(out/(prefix+'-cli.tar.gz')),'-C',str(out),'carryon')
    import tarfile
    with tarfile.open(out/(prefix+'-cli.tar.gz')) as archive:
        names=archive.getnames()
        if 'carryon/carryon' not in names or 'carryon/CarryOn' in names:
            raise RuntimeError('CLI archive executable casing is invalid')
    stage=work/'carryon-dmg';stage.mkdir(exist_ok=True)
    if (stage/'CarryOn.app').exists():shutil.rmtree(stage/'CarryOn.app')
    shutil.copytree(out/'CarryOn.app',stage/'CarryOn.app',symlinks=True)
    if not (stage/'Applications').is_symlink():(stage/'Applications').symlink_to('/Applications')
    shutil.copy2(ROOT/'docs/INSTALL.md',stage/'安装说明.md')
    dmg=out/(prefix+'.dmg')
    if dmg.exists():dmg.unlink()
    run('hdiutil','create','-volname','CarryOn','-srcfolder',str(stage),'-format','UDZO',str(dmg))
    run(sys.executable,'-m','build','--outdir',str(out))
    artifacts=sorted(p for p in out.iterdir() if p.name == f'carryon_local-{__version__}-py3-none-any.whl' or p.name in (prefix+'.dmg',prefix+'-cli.tar.gz'))
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in artifacts))
    print(json.dumps({'version':__version__,'architecture':arch,'developerSigned':bool(identity),
        'notarized':False,'artifacts':[str(p) for p in artifacts]},indent=2))

if __name__=='__main__':main()
