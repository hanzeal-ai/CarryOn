"""Run conversation navigation, alignment or root tab checks in an isolated app."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv) not in (2, 3):
    raise SystemExit("Usage: python3 tests/run_ios_navigation_regression.py <booted-simulator-id> [navigation|alignment|tabs|statuses|activity]")
repo = Path(__file__).resolve().parents[1]
mode = sys.argv[2] if len(sys.argv) == 3 else "navigation"
if mode not in ("navigation", "alignment", "tabs", "statuses", "activity"): raise SystemExit("Unknown regression")
work = repo / (".runtime/" + mode + "-regression")
source = work / "source"
source.mkdir(parents=True, exist_ok=True)
for directory in ("CarryOn", "CarryOn.xcodeproj", "Tests"):
    shutil.copytree(repo / "iOS" / directory, source / directory, dirs_exist_ok=True)
shutil.copy2(repo / "iOS/Package.swift", source / "Package.swift")
fixtures = {"navigation": "ios_navigation_regression.swift", "alignment": "ios_codex_alignment.swift", "tabs": "ios_tabs_regression.swift", "statuses": "ios_list_status_regression.swift", "activity": "ios_activity_regression.swift"}
shutil.copy2(repo / "tests/fixtures" / fixtures[mode], source / "CarryOn/App/CarryOnApp.swift")
if mode == "tabs":
    # Drive the same selection state as the bottom buttons, only in the test copy.
    root = source / "CarryOn/App/RootView.swift"
    original = root.read_text()
    anchor = '.foregroundStyle(Design.ink)'
    if anchor not in original:
        raise SystemExit("Root tab fixture injection point is missing")
    hooks = r''' .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.tab"))) { tab = $0.object as! Int }
        .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.seed"))) { _ in
            threadList.filter = "running"
            projectList.search = "项目"
            projectList.loadedQueryIdentity = model.scope + "/api/projects项目allfalse"
            projectList.updatedAt = Date()
            projectList.scrollID = "p3"
        }
        .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.inspect"))) { _ in
            NotificationCenter.default.post(name: Notification.Name("fixture.state"), object: [
                "search": projectList.search, "records": projectList.records.count,
                "projectFilter": projectList.filter, "threadFilter": threadList.filter,
                "scroll": projectList.scrollID ?? "", "query": projectList.loadedQueryIdentity])
        }
        '''
    root.write_text(original.replace(anchor, hooks + anchor, 1))
if mode in ("alignment", "activity"):
    with (source / "CarryOn/App/AppModel.swift").open("a") as handle:
        handle.write("\nextension AppModel { func fixtureClient(_ client: ConsoleAPI) { api = client } }\n")
if mode == "activity":
    row = source / "CarryOn/App/ActivityRow.swift"
    anchor = '.accessibilityValue(unread ? "未读" : "已读")'
    original = row.read_text()
    if anchor not in original: raise SystemExit("Activity fixture injection point is missing")
    row.write_text(original.replace(anchor, anchor + '''
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.activity.open"))) { note in
                if note.object as? String == record.id { openDetails() }
            }
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.activity.close"))) { note in
                if note.object as? String == record.id { showingDetails = false }
            }
            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.activity.inspect"))) { note in
                if note.object as? String == record.id {
                    NotificationCenter.default.post(name: Notification.Name("fixture.activity.state"), object: [
                        "loading": showInitialLoading, "snapshot": snapshot != .null,
                        "canPerform": model.canPerform(target), "failure": failure != nil])
                }
            }
''', 1))
if mode == "statuses":
    # Trigger the production refresh action in both real SwiftUI lists. This
    # notification hook exists only in the isolated regression app copy.
    lists = source / "CarryOn/App/ProjectsView.swift"
    anchor = '.refreshable { await load(reset: true, kind: .refresh) }'
    original = lists.read_text()
    if anchor not in original: raise SystemExit("List refresh fixture injection point is missing")
    lists.write_text(original.replace(anchor, anchor + '''
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.listRefresh"))) { _ in
                    Task { await load(reset: true, kind: .refresh) }
                }
''', 1))
    with (source / "CarryOn/App/AppModel.swift").open("a") as handle:
        handle.write('''
extension AppModel {
    func fixtureClient(_ client: ConsoleAPI) { api = client }
    func fixtureSelection() -> JSONValue { selection(selectedThread?.id) }
    func fixturePacket(_ packet: JSONValue) async { await apply(packet, threadID: selectedThread?.id) }
    func fixtureResetScope() { epoch = UUID() }
}
''')
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
                    "-skipPackageUpdates", "ARCHS=arm64", "CODE_SIGN_IDENTITY=-", "build"], stdout=log, stderr=subprocess.STDOUT, check=True)
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
        shutil.copy2(container / ("Documents/" + mode + ".png"), work / (mode + ".png"))
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data["passed"] else 1)
    time.sleep(0.2)
raise SystemExit(f"{mode} regression did not produce a result within 30 seconds")
