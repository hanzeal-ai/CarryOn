"""Render the real Mac update view against an isolated HTTP fixture."""
import json
import os
import platform
import plistlib
import shutil
import subprocess
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
work = repo/'.runtime/app-update-mac-regression'
app = work/'CarryOn.app'
executable = app/'Contents/MacOS/CarryOn'
executable.parent.mkdir(parents=True, exist_ok=True)
resources = app/'Contents/Resources'
resources.mkdir(exist_ok=True)
shutil.copy2(repo/'desktop/Resources/CarryOnLogo.png', resources/'CarryOnLogo.png')
(app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'CarryOn', 'CFBundleIdentifier': 'local.carryon.desktop',
    'CFBundleShortVersionString': '0.2.2', 'CFBundleVersion': '0.2.2', 'CFBundlePackageType': 'APPL'}))
subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5', '-target', platform.machine()+'-apple-macos13.0',
    str(repo/'iOS/CarryOn/Core/AppUpdate.swift'), str(repo/'desktop/AppUpdateView.swift'),
    str(repo/'tests/fixtures/app_update_transport.swift'), str(repo/'tests/AppUpdateDesktop.swift'), '-o', str(executable)], check=True)
result = work/'result.json'
previous = result.stat().st_mtime_ns if result.exists() else None
subprocess.run([str(executable)], env=dict(os.environ, UPDATE_TEST_OUTPUT=str(work)), check=True, timeout=30)
assert result.exists() and result.stat().st_mtime_ns != previous, 'No fresh desktop result'
data = json.loads(result.read_text())
print(json.dumps(data, ensure_ascii=False, indent=2))
raise SystemExit(0 if data['passed'] else 1)
