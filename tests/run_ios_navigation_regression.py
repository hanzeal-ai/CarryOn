"""Run conversation navigation, alignment or root tab checks in an isolated app."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv) not in (2, 3):
    raise SystemExit("Usage: python3 tests/run_ios_navigation_regression.py <booted-simulator-id> [navigation|alignment|tabs|statuses|activity|parity|home|fork]")
repo = Path(__file__).resolve().parents[1]
mode = sys.argv[2] if len(sys.argv) == 3 else "navigation"
if mode not in ("navigation", "alignment", "tabs", "statuses", "activity", "parity", "home", "fork"): raise SystemExit("Unknown regression")
work = repo / (".runtime/" + mode + "-regression")
source = work / "source"
source.mkdir(parents=True, exist_ok=True)
for directory in ("CarryOn", "CarryOn.xcodeproj", "Tests"):
    shutil.copytree(repo / "iOS" / directory, source / directory, dirs_exist_ok=True)
shutil.copy2(repo / "iOS/Package.swift", source / "Package.swift")
fixtures = {"navigation": "ios_navigation_regression.swift", "alignment": "ios_codex_alignment.swift", "tabs": "ios_tabs_regression.swift", "statuses": "ios_list_status_regression.swift", "activity": "ios_activity_regression.swift", "parity": "ios_parity_regression.swift", "home": "ios_home_regression.swift", "fork": "ios_fork_regression.swift"}
shutil.copy2(repo / "tests/fixtures" / fixtures[mode], source / "CarryOn/App/CarryOnApp.swift")
if mode == "tabs":
    # Drive the same selection state as the navigation menu, only in the test copy.
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
if mode in ("alignment", "activity", "parity", "home", "fork"):
    with (source / "CarryOn/App/AppModel.swift").open("a") as handle:
        handle.write("\nextension AppModel { func fixtureClient(_ client: ConsoleAPI) { api = client } }\n")
if mode == "fork":
    # Isolate command/navigation behavior from unrelated SSE authentication startup.
    model_file = source / "CarryOn/App/AppModel.swift"
    model_text = model_file.read_text()
    start = model_text.index("private func startStream()")
    opening = model_text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (model_text[end] == "{") - (model_text[end] == "}")
        end += 1
    model_file.write_text(model_text[:opening] + "{}" + model_text[end:])
    view = source / "CarryOn/App/ForkConversationView.swift"
    text = view.read_text().replace('}.interactiveDismissDisabled(submitting)', '}.interactiveDismissDisabled(submitting)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.fork.submit"))) { note in\n                lastTurnID = note.object as? String ?? ""\n                Task { await fork(); NotificationCenter.default.post(name: Notification.Name("fixture.fork.finished"), object: nil) }\n            }', 1)
    text = text.replace('.accessibilityIdentifier("fork-error")', '.accessibilityIdentifier("fork-error").onAppear { NotificationCenter.default.post(name: Notification.Name("fixture.fork.errorVisible"), object: failure) }', 1)
    view.write_text(text)
if mode == "home":
    picker = source / "CarryOn/App/CreationModelPicker.swift"
    text = picker.read_text()
    save = text.split('Button("完成") {', 1)[1].split('}.disabled', 1)[0]
    text = text.replace('    var body: some View {', '    private func fixtureSave() {' + save + '}\n    var body: some View {', 1)
    text = text.replace('}.presentationDetents([.medium])', '}.presentationDetents([.medium])\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.model.choose"))) { _ in selected = "fixture-model"; effort = "high" }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.model.save"))) { _ in fixtureSave() }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.model.inspect"))) { _ in\n                NotificationCenter.default.post(name: Notification.Name("fixture.model.state"), object: ["selected": selected, "effort": effort, "loading": loading, "failure": failure ?? ""] as [String: Any])\n            }\n', 1)
    picker.write_text(text)
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
if mode == "parity":
    composer = source / "CarryOn/App/ChatAppearance.swift"
    text = composer.read_text().replace('    @Binding var text: String', '    @FocusState private var fixtureFocused: Bool\n    @Binding var text: String', 1)
    text = text.replace('.font(.body).lineLimit(1...6)', '.focused($fixtureFocused)\n                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.composer.focus"))) { _ in fixtureFocused = true }\n                .font(.body).lineLimit(1...6)', 1)
    composer.write_text(text)
    creation = source / "CarryOn/App/ConversationActions.swift"
    text = creation.read_text().replace('.sheet(isPresented: $choosingModel)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.creation"))) { _ in\n                    creationSettings = .object(["model": .string("gpt-5.5"), "effort": .string("high")])\n                }\n                .sheet(isPresented: $choosingModel)', 1)
    creation.write_text(text)
    review = source / "CarryOn/App/ConversationChangesView.swift"
    text = review.read_text().replace('.sheet(item: $commentLine)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.comment"))) { _ in\n                    commentScope = model.scope; commentPath = "src/example.swift"; commentText = "请检查这里的边界"\n                    commentLine = UnifiedDiff.lines("@@ -1,0 +2,1 @@\\n+new()")[1]\n                }\n                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.submitComment"))) { _ in\n                    if let line = commentLine { addComment(line) }\n                }\n                .sheet(item: $commentLine)', 1)
    review.write_text(text)
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
                    "-derivedDataPath", str(work / "build"), "-clonedSourcePackagesDirPath", os.environ.get("CARRYON_SWIFT_PACKAGES", str(repo / "iOS/.build/SourcePackages")),
                    "-skipPackageUpdates", "ARCHS=arm64", "CODE_SIGN_IDENTITY=-", "build"], stdout=log, stderr=subprocess.STDOUT, check=True)
app = work / "build/Build/Products/Debug-iphonesimulator/CarryOn.app"
subprocess.run(["xcrun", "simctl", "install", device, str(app)], check=True)
bundle = "com.hanzeal.carryon." + mode + "regression"
container = Path(subprocess.check_output(["xcrun", "simctl", "get_app_container", device, bundle, "data"], text=True).strip())
result = container / ("Documents/" + mode + "-result.json")
# A previous test result must not satisfy this run.
previous = result.stat().st_mtime_ns if result.exists() else None
screens = ("parity-new-single", "parity-new-multiline", "parity-new-image") if mode == "parity" else ("tabs-top",) if mode == "tabs" else ()
for name in screens:
    (container / ("Documents/" + name + ".capture")).unlink(missing_ok=True)
captured = set()
subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", f"--stdout={work / 'simulator.log'}", f"--stderr={work / 'simulator-errors.log'}", device, bundle], check=True)
# Includes cold simulator launch and the expanded asynchronous delivery scenarios.
for _ in range(300):
    for name in screens:
        marker = container / ("Documents/" + name + ".capture")
        if name not in captured and marker.exists():
            subprocess.run(["xcrun", "simctl", "io", device, "screenshot", str(work / (name + ".png"))], check=True, stdout=subprocess.DEVNULL)
            captured.add(name)
    if result.exists() and result.stat().st_mtime_ns != previous:
        data = json.loads(result.read_text())
        shutil.copy2(result, work / "result.json")
        shutil.copy2(container / ("Documents/" + mode + ".png"), work / (mode + ".png"))
        if mode == "parity":
            for name in ("parity-new", "parity-diff", "parity-skills", "parity-goal"):
                shutil.copy2(container / ("Documents/" + name + ".png"), work / (name + ".png"))
        if set(screens) != captured: raise SystemExit("Missing screenshots: " + str(set(screens) - captured))
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data["passed"] else 1)
    time.sleep(0.2)
raise SystemExit(f"{mode} regression did not produce a result within 60 seconds")
