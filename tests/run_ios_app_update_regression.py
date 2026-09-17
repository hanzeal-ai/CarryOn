"""Run the real update UI/model against an isolated, controllable HTTP transport."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv) != 2:
    raise SystemExit("Usage: python3 tests/run_ios_app_update_regression.py <booted-simulator-id>")
repo = Path(__file__).resolve().parents[1]
work = repo / ".runtime/app-update-regression"
source = work / "source"
source.mkdir(parents=True, exist_ok=True)
for directory in ("CarryOn", "CarryOn.xcodeproj", "Tests"):
    shutil.copytree(repo / "iOS" / directory, source / directory, dirs_exist_ok=True)
shutil.copy2(repo / "iOS/Package.swift", source / "Package.swift")
shutil.copy2(repo / "tests/fixtures/ios_app_update_regression.swift", source / "CarryOn/App/CarryOnApp.swift")
shutil.copy2(repo / "tests/fixtures/app_update_transport.swift", source / "CarryOn/Core/AppUpdateFixtureProtocol.swift")
api = source / "CarryOn/Core/AppUpdate.swift"
transport_default = "configuration: URLSessionConfiguration = .ephemeral"
assert api.read_text().count(transport_default) == 1
api.write_text(api.read_text().replace(transport_default, "configuration: URLSessionConfiguration = AppUpdateFixtureProtocol.configuration"))
project = source / "CarryOn.xcodeproj/project.pbxproj"
project.write_text(project.read_text().replace("com.hanzeal.carryon", "com.hanzeal.carryon.appupdateregression"))
fixture = source / "CarryOn/Core/AppUpdateFixtureProtocol.swift"
fixture.write_text(fixture.read_text().replace('"com.hanzeal.carryon"', '"com.hanzeal.carryon.appupdateregression"'))
device = sys.argv[1]
with (work / "build.log").open("w") as log:
    subprocess.run(["xcodebuild", "-project", str(source / "CarryOn.xcodeproj"), "-scheme", "CarryOn",
                    "-configuration", "Debug", "-sdk", "iphonesimulator", "-destination", f"id={device}",
                    "-derivedDataPath", str(work / "build"), "-clonedSourcePackagesDirPath", str(repo / "iOS/.build/SourcePackages"),
                    "-skipPackageUpdates", "ARCHS=arm64", "CODE_SIGN_IDENTITY=-", "build"], stdout=log, stderr=subprocess.STDOUT, check=True)
app = work / "build/Build/Products/Debug-iphonesimulator/CarryOn.app"
state = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "--json"], text=True))
selected = next(item for group in state["devices"].values() for item in group if item["udid"] == device)
if selected["state"] == "Shutdown":
    subprocess.run(["xcrun", "simctl", "boot", device], check=True)
subprocess.run(["xcrun", "simctl", "bootstatus", device, "-b"], check=True)
subprocess.run(["xcrun", "simctl", "install", device, str(app)], check=True)
bundle = "com.hanzeal.carryon.appupdateregression"
container = Path(subprocess.check_output(["xcrun", "simctl", "get_app_container", device, bundle, "data"], text=True).strip())
result = container / "Documents/app-update-result.json"
# A previous test result must not satisfy this run.
previous = result.stat().st_mtime_ns if result.exists() else None
subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", f"--stdout={work / 'simulator.log'}", f"--stderr={work / 'simulator-errors.log'}", device, bundle], check=True)
for _ in range(150):
    if result.exists() and result.stat().st_mtime_ns != previous:
        data = json.loads(result.read_text())
        shutil.copy2(result, work / "result.json")
        for name in ("app-update-available.png", "app-update-unpublished.png"):
            if (container / "Documents" / name).exists():
                shutil.copy2(container / "Documents" / name, work / name)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data["passed"] else 1)
    time.sleep(0.2)
raise SystemExit("App update regression did not produce a result within 30 seconds")
