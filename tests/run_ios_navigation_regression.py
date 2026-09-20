"""Run conversation navigation in an isolated simulator application."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv) not in (2, 3):
    raise SystemExit("Usage: python3 tests/run_ios_navigation_regression.py <booted-simulator-id> [navigation|alignment]")
repo = Path(__file__).resolve().parents[1]
mode = sys.argv[2] if len(sys.argv) == 3 else "navigation"
if mode not in ("navigation", "alignment"): raise SystemExit("Unknown regression")
work = repo / (".runtime/" + mode + "-regression")
source = work / "source"
source.mkdir(parents=True, exist_ok=True)
for directory in ("CarryOn", "CarryOn.xcodeproj", "Tests"):
    shutil.copytree(repo / "iOS" / directory, source / directory, dirs_exist_ok=True)
shutil.copy2(repo / "iOS/Package.swift", source / "Package.swift")
shutil.copy2(repo / ("tests/fixtures/ios_navigation_regression.swift" if mode == "navigation" else "tests/fixtures/ios_codex_alignment.swift"), source / "CarryOn/App/CarryOnApp.swift")
if mode == "alignment":
    with (source / "CarryOn/App/AppModel.swift").open("a") as handle:
        handle.write("\nextension AppModel { func fixtureClient(_ client: ConsoleAPI) { api = client } }\n")
project = source / "CarryOn.xcodeproj/project.pbxproj"
project.write_text(project.read_text().replace("com.hanzeal.carryon", "com.hanzeal.carryon." + mode + "regression"))
# The project bundles its product configuration from the adjacent package.
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
bundle = "com.hanzeal.carryon." + mode + "regression"
container = Path(subprocess.check_output(["xcrun", "simctl", "get_app_container", device, bundle, "data"], text=True).strip())
result = container / ("Documents/" + mode + "-result.json")
# A previous test result must not satisfy this run.
previous = result.stat().st_mtime_ns if result.exists() else None
subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", f"--stdout={work / 'simulator.log'}", f"--stderr={work / 'simulator-errors.log'}", device, bundle], check=True)
for _ in range(150):
    if result.exists() and result.stat().st_mtime_ns != previous:
        data = json.loads(result.read_text())
        shutil.copy2(result, work / "result.json")
        if mode == "navigation": shutil.copy2(container / "Documents/navigation.png", work / "navigation.png")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data["passed"] else 1)
    time.sleep(0.2)
raise SystemExit("Startup regression did not produce a result within 30 seconds")
