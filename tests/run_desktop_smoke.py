"""Run native desktop lifecycle model against the real CLI and isolated app-servers."""
import os
import platform
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix='carryon-desktop-') as temp:
    root=Path(temp).resolve(); cli=root/'cli'; binary=root/'desktop-smoke'
    cli.write_text('#!/bin/sh\ncd '+shlex.quote(str(ROOT))+'\nexec '+shlex.quote(sys.executable)+' -m carryon "$@"\n');cli.chmod(0o700)
    env=dict(os.environ,CARRYON_HOME=str(root/'default'),CARRYON_REGISTRY_DIR=str(root/'registry'),
             CODEX_HOME=str(root/'native-codex'),CARRYON_DESKTOP_CLI=str(cli))
    subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-D','DESKTOP_TEST',
        *map(str,sorted((ROOT/'desktop').glob('*.swift'))),str(ROOT/'tests/DesktopSmoke.swift'),'-o',str(binary)],check=True)
    try:
        subprocess.run([str(binary)],env=env,check=True,timeout=90)
    finally:
        registry=root/'registry/services.json'
        if registry.exists():
            import json
            for directory in json.loads(registry.read_text())['services']:
                subprocess.run([str(cli),'stop','--state-dir',directory],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
