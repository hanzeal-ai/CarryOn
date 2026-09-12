"""Build the Swift model test and verify both packaged entry points against isolated state."""
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cli = ROOT/'dist/carryon/carryon'
helper = ROOT/'dist/CarryOn.app/Contents/MacOS/carryon-service'
with tempfile.TemporaryDirectory(prefix='carryon-desktop-') as temp:
    state = Path(temp).resolve()/'state'; state.mkdir(mode=0o700)
    os.environ['CARRYON_REGISTRY_DIR']=str(Path(temp)/'registry')
    configs = {letter*32: {'enabled':False, 'url':f'wss://test-{letter}.invalid/device',
               'deviceId':f'test-{letter}', 'token':'test-only-'+'x'*40, 'control':False} for letter in ('a','b')}
    config = state/'cloud.json'
    config.write_text(json.dumps({'version':2,'bindings':configs})); config.chmod(0o600)
    second = Path(temp).resolve()/'second'; second.mkdir(mode=0o700)
    (second/'cloud.json').write_text(config.read_text()); (second/'cloud.json').chmod(0o600)
    binary = Path(temp)/'desktop-smoke'
    subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-D','DESKTOP_TEST',
                    '-target',platform.machine()+'-apple-macos13.0',*map(str,sorted((ROOT/'desktop').glob('*.swift'))),
                    str(ROOT/'tests/DesktopSmoke.swift'),'-o',str(binary)],check=True)
    try:
        subprocess.run([str(cli),'start','--no-open','--port','0','--codex-home',str(Path(temp)/'empty-codex'),
                        '--state-dir',str(state)],check=True,timeout=30)
        subprocess.run([str(cli),'start','--no-open','--port','0','--codex-home',str(Path(temp)/'empty-codex'),
                        '--state-dir',str(second)],check=True,timeout=30)
        env = dict(os.environ,CARRYON_HOME=str(state),CARRYON_DESKTOP_CLI=str(helper),
                   CARRYON_TEST_EXTERNAL_CLI=str(cli),CARRYON_TEST_SECOND=str(second),CARRYON_TEST_THIRD=str(Path(temp).resolve()/'third'))
        subprocess.run([str(binary)],env=env,check=True,timeout=120)
    finally:
        for directory in [state,second,Path(temp)/'third']:
            subprocess.run([str(cli),'stop','--state-dir',str(directory)],check=False,timeout=30)
