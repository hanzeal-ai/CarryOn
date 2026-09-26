"""Run the real startup UI/model against an isolated, controllable HTTP transport."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv) != 2:
    raise SystemExit("Usage: python3 tests/run_ios_startup_regression.py <booted-simulator-id>")
repo = Path(__file__).resolve().parents[1]
work = repo / ".runtime/startup-regression"
source = work / "source"
source.mkdir(parents=True, exist_ok=True)
for directory in ("CarryOn", "CarryOn.xcodeproj", "Tests"):
    shutil.copytree(repo / "iOS" / directory, source / directory, dirs_exist_ok=True)
shutil.copy2(repo / "iOS/Package.swift", source / "Package.swift")
shutil.copy2(repo / "tests/fixtures/ios_startup_regression.swift", source / "CarryOn/App/CarryOnApp.swift")
shutil.copy2(repo / "tests/fixtures/ios_startup_transport.swift", source / "CarryOn/Core/StartupProtocol.swift")
api = source / "CarryOn/Core/ConsoleAPI.swift"
transport_default = "configuration: URLSessionConfiguration = .ephemeral"
assert api.read_text().count(transport_default) == 1, "The test transport injection no longer matches ConsoleAPI"
api.write_text(api.read_text().replace(transport_default, "configuration: URLSessionConfiguration = StartupProtocol.configuration"))
project = source / "CarryOn.xcodeproj/project.pbxproj"
project.write_text(project.read_text().replace("com.hanzeal.carryon", "com.hanzeal.carryon.startupregression"))
# The app target copies its product configuration from the adjacent package.
(work / "carryon").mkdir(exist_ok=True)
shutil.copy2(repo / "carryon/product.json", work / "carryon/product.json")
device = sys.argv[1]
with (work / "build.log").open("w") as log:
    subprocess.run(["xcodebuild", "-project", str(source / "CarryOn.xcodeproj"), "-scheme", "CarryOn",
                    "-configuration", "Debug", "-sdk", "iphonesimulator", "-destination", f"id={device}",
                    "-derivedDataPath", str(work / "build"), "-clonedSourcePackagesDirPath", str(repo / "iOS/.build/SourcePackages"),
                    "ARCHS=arm64", "CODE_SIGN_IDENTITY=-", "build"], stdout=log, stderr=subprocess.STDOUT, check=True)
app = work / "build/Build/Products/Debug-iphonesimulator/CarryOn.app"
subprocess.run(["xcrun", "simctl", "install", device, str(app)], check=True)
bundle = "com.hanzeal.carryon.startupregression"
container = Path(subprocess.check_output(["xcrun", "simctl", "get_app_container", device, bundle, "data"], text=True).strip())
result = container / "Documents/startup-result.json"
# A previous test result must not satisfy this run.
previous = result.stat().st_mtime_ns if result.exists() else None
subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", f"--stdout={work / 'simulator.log'}", f"--stderr={work / 'simulator-errors.log'}", device, bundle], check=True)
for _ in range(150):
    if result.exists() and result.stat().st_mtime_ns != previous:
        data = json.loads(result.read_text())
        shutil.copy2(result, work / "result.json")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data["passed"] else 1)
    time.sleep(0.2)
raise SystemExit("Startup regression did not produce a result within 30 seconds")
