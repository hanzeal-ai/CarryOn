"""Run conversation navigation, alignment or root tab checks in an isolated app."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

if len(sys.argv) not in (2, 3):
    raise SystemExit("Usage: python3 tests/run_ios_navigation_regression.py <booted-simulator-id> [navigation|alignment|tabs|statuses|activity|parity|home|fork|composer|visual|creationrefs|conversationvisual|timeline|archives|rename|search|sections|terminals|skillmanagement|plugins|projectfiles|timelineperformance|timelineboundary|liststates|uploads]")
repo = Path(__file__).resolve().parents[1]
build_configuration = os.environ.get("CARRYON_IOS_CONFIGURATION", "Debug")
if build_configuration not in ("Debug", "Release"):
    raise SystemExit("CARRYON_IOS_CONFIGURATION must be Debug or Release")
mode = sys.argv[2] if len(sys.argv) == 3 else "navigation"
if mode not in ("navigation", "alignment", "tabs", "statuses", "activity", "parity", "home", "fork", "composer", "visual", "creationrefs", "conversationvisual", "timeline", "archives", "rename", "search", "sections", "terminals", "skillmanagement", "plugins", "projectfiles", "timelineperformance", "timelineboundary", "liststates", "uploads"): raise SystemExit("Unknown regression")
work = repo / (".runtime/" + mode + "-regression")
source = work / "source"
source.mkdir(parents=True, exist_ok=True)
for directory in ("CarryOn", "CarryOn.xcodeproj", "Tests"):
    if (source / directory).exists(): shutil.rmtree(source / directory)
    shutil.copytree(repo / "iOS" / directory, source / directory)
shutil.copy2(repo / "iOS/Package.swift", source / "Package.swift")
fixtures = {"navigation": "ios_navigation_regression.swift", "alignment": "ios_codex_alignment.swift", "tabs": "ios_tabs_regression.swift", "statuses": "ios_list_status_regression.swift", "activity": "ios_activity_regression.swift", "parity": "ios_parity_regression.swift", "home": "ios_home_regression.swift", "fork": "ios_fork_regression.swift", "composer": "ios_composer_regression.swift", "visual": "ios_visual_regression.swift", "creationrefs": "ios_creationrefs_regression.swift", "conversationvisual": "ios_conversationvisual_regression.swift", "timeline": "ios_timeline_regression.swift", "archives": "ios_archives_regression.swift", "rename": "ios_rename_regression.swift", "search": "ios_search_regression.swift", "sections": "ios_sections_regression.swift", "terminals": "ios_terminals_regression.swift", "skillmanagement": "ios_skillmanagement_regression.swift", "plugins": "ios_plugins_regression.swift", "projectfiles": "ios_projectfiles_regression.swift", "timelineperformance": "ios_timeline_regression.swift", "timelineboundary": "ios_timeline_regression.swift", "liststates": "ios_conversation_list_states.swift", "uploads": "ios_uploads_regression.swift"}
shutil.copy2(repo / "tests/fixtures" / fixtures[mode], source / "CarryOn/App/CarryOnApp.swift")
if mode == "uploads":
    for filename, event, anchor, key in (
        ("ConversationView.swift", "fixture.uploads.conversation", "        conversationPresentation\n", "uploadKey"),
        ("ConversationActions.swift", "fixture.uploads.creation", "            .carryOnChatAppearance()\n", "draftKey"),
    ):
        view = source / "CarryOn/App" / filename
        original = view.read_text()
        if anchor not in original: raise SystemExit("Uploads fixture injection point is missing")
        hook = '        .onReceive(NotificationCenter.default.publisher(for: Notification.Name("' + event + '"))) { note in if let kind = (note.object as? String).flatMap(UploadKind.init(rawValue:)) { uploadPicker.open(kind, model: model, key: ' + key + ', target: uploadTarget) } else { uploadPicker.showing = false } }\n'
        view.write_text(original.replace(anchor, anchor + hook, 1))
if mode == "liststates":
    import runpy
    runpy.run_path(str(repo / "tests/fixtures/ios_conversation_list_states.py"), init_globals={"source": source})

if mode == "timelineperformance":
    fixture = source / "CarryOn/App/CarryOnApp.swift"
    fixture.write_text(fixture.read_text().replace('let performanceOnly = false', 'let performanceOnly = true').replace('timeline-result.json', 'timelineperformance-result.json').replace('timeline.png', 'timelineperformance.png'))
if mode == "timelineboundary":
    fixture = source / "CarryOn/App/CarryOnApp.swift"
    fixture.write_text(fixture.read_text().replace('let boundaryOnly = false', 'let boundaryOnly = true').replace('timeline-result.json', 'timelineboundary-result.json').replace('timeline.png', 'timelineboundary.png'))
if mode in ("timeline", "timelineperformance", "timelineboundary", "liststates"):
    # Observe the production projection without changing messages or table behavior.
    view = source / "CarryOn/App/ConversationView.swift"
    text = view.read_text()
    text = text.replace('            let (next, updateRows) = await projectedMessages(supplemental: supplemental)', '            let fixtureProjectionStart = CACurrentMediaTime()\n            let (next, updateRows) = await projectedMessages(supplemental: supplemental)\n            let fixtureProjectionEnd = CACurrentMediaTime()', 1)
    text = text.replace('            if let tableUpdates {', r'''
            let fixtureComparisonStart = CACurrentMediaTime()
            let fixturePrevious = Dictionary(chatMessages.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            let fixtureRetained = next.filter { fixturePrevious[$0.id] != nil && $0.id != "carryon:status" }
            let fixtureChanged = fixtureRetained.filter { fixturePrevious[$0.id] != $0 }
            NotificationCenter.default.post(name: Notification.Name("fixture.projection"), object: [
                "retained": fixtureRetained.count, "changed": fixtureChanged.count,
                "projectionMs": (fixtureProjectionEnd - fixtureProjectionStart) * 1000, "comparisonMs": (CACurrentMediaTime() - fixtureComparisonStart) * 1000])
            if let tableUpdates {
''', 1)
    text = text.replace('                await tableUpdates {', '                NotificationCenter.default.post(name: Notification.Name("fixture.beforeTransaction"), object: nil)\n                let fixtureTableStart = CACurrentMediaTime()\n                await tableUpdates {', 1)
    text = text.replace('            } else { updateRows.forEach { $0() }; chatMessages = next }', '                NotificationCenter.default.post(name: Notification.Name("fixture.timing"), object: ["stage": "tableTransaction", "wallMs": (CACurrentMediaTime() - fixtureTableStart) * 1000])\n            } else { updateRows.forEach { $0() }; chatMessages = next }', 1)
    text = text.replace('.onChange(of: visibleCount)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.earlier"))) { _ in Task { await loadEarlierMessages() } }\n        .onChange(of: visibleCount)', 1)
    text = text.replace('        let kind = item["type"].text', '        let _ = NotificationCenter.default.post(name: Notification.Name("fixture.entryRender"), object: item.stableID)\n        let kind = item["type"].text', 1)
    text = text.replace('.onChange(of: visibleCount)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.latest"))) { _ in returnToLatest() }\n        .onChange(of: visibleCount)', 1)
    text = text.replace('.onChange(of: visibleCount)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.readingLayout"))) { _ in navigationTracker.didLayout() }\n        .onChange(of: visibleCount)', 1)
    text = text.replace('readingAnchor = navigationTracker.captureReadingAnchor(in: readingCandidates)', 'readingAnchor = navigationTracker.captureReadingAnchor(in: readingCandidates)\n                            NotificationCenter.default.post(name: .init("fixture.readingAnchor"), object: ["phase": "capture", "growing": Array(growing), "text": readingAnchor?.text ?? "", "paragraph": readingAnchor?.paragraph ?? -1, "y": readingAnchor?.screenY ?? -1, "offset": navigationTracker.contentOffset ?? -1])', 1)
    navigation = source / "CarryOn/App/ConversationNavigation.swift"
    navigation_text = navigation.read_text()
    navigation_text = navigation_text.replace('        guard anchor.intent == readingIntent, let table, observedTable === table,', '        NotificationCenter.default.post(name: .init("fixture.readingAnchor"), object: ["phase": "restore", "id": anchor.id, "hasCell": cell(for: anchor.id) != nil, "sameTable": observedTable === table, "sameIntent": anchor.intent == readingIntent, "viewport": NSCoder.string(for: anchor.viewport), "currentViewport": table.map { NSCoder.string(for: $0.convert($0.bounds, to: nil)) } ?? "nil", "offset": contentOffset ?? -1])\n        guard anchor.intent == readingIntent, let table, observedTable === table,', 1)
    navigation_text = navigation_text.replace('        let delta = anchor.screenY - screenY', '        let delta = anchor.screenY - screenY\n        NotificationCenter.default.post(name: .init("fixture.readingAnchor"), object: ["phase": "correction", "delta": delta, "before": anchor.screenY, "after": screenY])', 1)
    navigation.write_text(navigation_text)
    view.write_text(text)
    queue_view = source / "CarryOn/App/ConversationQueueView.swift"
    queue_text = queue_view.read_text()
    queue_anchor = '}.font(.caption).padding(.horizontal, 16).frame(minHeight: 40)'
    if queue_anchor not in queue_text:
        raise SystemExit("Timeline queue observation point is missing")
    queue_view.write_text(queue_text.replace(queue_anchor, queue_anchor + '\n                .onChange(of: count, initial: true) { _, value in NotificationCenter.default.post(name: Notification.Name("fixture.queueCount"), object: value) }', 1))
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
if mode in ("alignment", "activity", "parity", "home", "fork", "visual", "creationrefs", "conversationvisual", "archives", "rename", "search", "sections", "terminals", "skillmanagement", "plugins", "projectfiles", "timelineperformance", "timelineboundary", "liststates"):
    with (source / "CarryOn/App/AppModel.swift").open("a") as handle:
        handle.write("\nextension AppModel { func fixtureClient(_ client: ConsoleAPI) { api = client } }\n")
if mode == "projectfiles":
    view = source / "CarryOn/App/ProjectFilesPicker.swift"
    text = view.read_text().replace('.onChange(of: current)', r''' .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.files.search"))) { note in search = note.object as? String ?? ""; Task { await load() } }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.files.toggle"))) { _ in if let file = results.first { toggle(file) } }
                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.files.inspect"))) { _ in NotificationCenter.default.post(name: .init("fixture.files.snapshot"), object: ["loaded": loaded, "busy": busy, "count": results.count, "selected": selected.count, "current": current]) }
                .onChange(of: current)''', 1)
    view.write_text(text)
if mode == "search":
    conversation = source / "CarryOn/App/ConversationView.swift"
    conversation.write_text(conversation.read_text().replace('.onChange(of: model.historyRevision, initial: true)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.offsetburst"))) { _ in for _ in 0..<12 { updateContentOffset(readingState?.offset ?? 0) } }\n        .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.render"))) { _ in NotificationCenter.default.post(name: Notification.Name("fixture.search.rendered"), object: ["ids": chatMessages.map(\\.id), "visibleCount": visibleCount, "repairs": navigationRepairs, "pinned": navigationPinned, "bounds": NSCoder.string(for: navigationBounds), "layout": navigationRepairLayout.map { NSCoder.string(for: $0) } ?? "", "measured": navigationTracker.measuredLayout.map { NSCoder.string(for: $0) } ?? "", "pending": pendingNavigation ?? "", "navigation": navigationAnchor ?? ""]) }\n        .onChange(of: model.historyRevision, initial: true)', 1))
    view = source / "CarryOn/App/ConversationSearchView.swift"
    text = view.read_text().replace('.task(id: identity)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.query"))) { query = $0.object as! String }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.more"))) { _ in Task { await load(more: true) } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.select"))) { _ in if let row = rows.first { thread = try? Record(row) } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.search.inspect"))) { _ in NotificationCenter.default.post(name: Notification.Name("fixture.search.snapshot"), object: ["rows": rows, "highlighted": rows.first.map { highlighted($0).runs.contains { $0.backgroundColor != nil } } ?? false]) }\n            .task(id: identity)', 1)
    view.write_text(text)
if mode == "plugins":
    view = source / "CarryOn/App/PluginManagementView.swift"
    text = view.read_text().replace('}.interactiveDismissDisabled(busy)', '}.interactiveDismissDisabled(busy)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.inspect"))) { _ in NotificationCenter.default.post(name: Notification.Name("fixture.plugins.snapshot"), object: ["loaded": loaded, "busy": busy, "rows": rows.count, "filteredRows": filteredRows.count, "nextCursor": nextCursor ?? "", "detail": detail != nil, "current": current, "requestId": requestID ?? "", "failure": failure ?? "", "readFailure": readFailure ?? ""]) }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.mode"))) { note in searchMode = note.object as? String ?? "directory" }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.nativeSearch"))) { note in Task { await load(more: note.object as? Bool == true) } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.search"))) { note in search = note.object as? String ?? "" }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.stop"))) { _ in Task { await submit() } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.detail"))) { note in if let plugin = rows.first(where: { note.object as? String == nil || $0["id"].text == note.object as? String }) { Task { await loadDetail(plugin) } } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.plugins.check"))) { _ in Task { await check() } }', 1)
    text = text.replace('if !value { rows = []; detail = nil; dismiss() }', 'if !value { rows = []; detail = nil; NotificationCenter.default.post(name: Notification.Name("fixture.plugins.snapshot"), object: ["rows": rows.count, "current": current]); dismiss() }')
    view.write_text(text)
if mode == "skillmanagement":
    view = source / "CarryOn/App/SkillManagementView.swift"
    text = view.read_text().replace('}.interactiveDismissDisabled(busy)', '}.interactiveDismissDisabled(busy)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.skills.inspect"))) { _ in NotificationCenter.default.post(name: Notification.Name("fixture.skills.snapshot"), object: ["loaded": loaded, "busy": busy, "rows": rows.count, "current": current, "requestId": requestID ?? "", "failure": failure ?? "", "readFailure": readFailure ?? ""]) }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.skills.stop"))) { note in if let row = rows.first(where: { $0["path"].text == note.object as? String }) { Task { await submit(row) } } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.skills.check"))) { _ in Task { await check() } }', 1)
    text = text.replace('if !value { rows = []; dismiss() }', 'if !value { rows = []; NotificationCenter.default.post(name: Notification.Name("fixture.skills.snapshot"), object: ["rows": rows.count, "current": current]); dismiss() }')
    view.write_text(text)
if mode == "terminals":
    view = source / "CarryOn/App/BackgroundTerminalsView.swift"
    text = view.read_text().replace('}.interactiveDismissDisabled(busy)', '}.interactiveDismissDisabled(busy)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.terminals.inspect"))) { _ in NotificationCenter.default.post(name: Notification.Name("fixture.terminals.snapshot"), object: ["loaded": loaded, "busy": busy, "rows": rows.count, "current": current, "scope": scope, "modelScope": model.scope, "selected": model.selectedThread?.id ?? "", "requestId": requestID ?? "", "failure": failure ?? "", "readFailure": readFailure ?? ""]) }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.terminals.stop"))) { note in Task { await stop(.object(["action": .string("terminate"), "processId": .string(note.object as? String ?? "")])) } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.terminals.check"))) { _ in Task { await check() } }', 1)
    text = text.replace('if !value { rows = []; dismiss() }', 'if !value { rows = []; NotificationCenter.default.post(name: Notification.Name("fixture.terminals.snapshot"), object: ["rows": rows.count, "current": current]); dismiss() }')
    view.write_text(text)
if mode == "sections":
    view = source / "CarryOn/App/SectionConversationView.swift"
    text = view.read_text().replace('}.interactiveDismissDisabled(busy)', '}.interactiveDismissDisabled(busy)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sections.inspect"))) { _ in NotificationCenter.default.post(name: Notification.Name("fixture.sections.snapshot"), object: ["loaded": loaded, "busy": busy, "failure": failure ?? "", "destination": destination ?? "", "requestId": requestID ?? "", "sections": sections.count]) }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sections.destination"))) { destination = $0.object as? String }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sections.save"))) { _ in Task { await save() } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sections.restore"))) { _ in Task { await restore() } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sections.query"))) { _ in Task { await check() } }', 1)
    view.write_text(text)
    view = source / "CarryOn/App/NativeSectionsView.swift"
    text = view.read_text().replace('.navigationTitle("分组").toolbar', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sections.browse.inspect"))) { _ in NotificationCenter.default.post(name: Notification.Name("fixture.sections.browse.snapshot"), object: ["rows": page.rows.count, "busy": page.busy, "scope": openingScope ?? ""]) }.navigationTitle("分组").toolbar', 1)
    view.write_text(text)
    view = source / "CarryOn/App/SectionManagementView.swift"
    text = view.read_text().replace('.interactiveDismissDisabled(busy)', '.interactiveDismissDisabled(busy)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sectionManagement.name"))) { name = $0.object as! String }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sectionManagement.before"))) { beforeThread = $0.object as? String }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sectionManagement.save"))) { _ in Task { await submit(delete: false) } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sectionManagement.delete"))) { _ in Task { await submit(delete: true) } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.sectionManagement.query"))) { _ in Task { await check() } }', 1)
    view.write_text(text)
if mode == "rename":
    view = source / "CarryOn/App/RenameConversationView.swift"
    text = view.read_text().replace('}.interactiveDismissDisabled(busy)', '}.interactiveDismissDisabled(busy)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.rename.name"))) { name = $0.object as! String }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.rename.save"))) { _ in Task { await save() } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.rename.restore"))) { _ in Task { await restore() } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.rename.query"))) { _ in Task { await check() } }', 1)
    view.write_text(text)
if mode == "archives":
    view = source / "CarryOn/App/ArchivedThreadsView.swift"
    text = view.read_text().replace('        }.interactiveDismissDisabled(busy)', '        }.interactiveDismissDisabled(busy)\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.archive.submit"))) { _ in Task { await submit() } }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.archive.query"))) { _ in Task { await check() } }', 1)
    view.write_text(text)
if mode == "conversationvisual":
    conversation = source / "CarryOn/App/ConversationView.swift"
    text = conversation.read_text()
    anchor = '.sheet(item: $sideLaunch)'
    if anchor not in text: raise SystemExit("Command fixture hook missing")
    conversation.write_text(text.replace(anchor, '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.command.submit"))) { _ in submitMessage() }\n        ' + anchor, 1))
if mode == "creationrefs":
    creation = source / "CarryOn/App/ConversationActions.swift"
    text = creation.read_text()
    anchor = '.sheet(isPresented: $choosingWorkspace)'
    if anchor not in text: raise SystemExit("Creation fixture hook missing")
    text = text.replace(anchor, '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.creationrefs.submit"))) { _ in Task { await create() } }\n                ' + anchor, 1)
    text = text.replace(anchor, '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.creationrefs.models"))) { _ in Task { await loadCreationModels() } }\n                ' + anchor, 1)
    creation.write_text(text)
if mode in ("fork", "creationrefs", "conversationvisual", "archives", "rename", "search", "sections", "terminals", "skillmanagement", "plugins", "projectfiles", "timelineperformance", "timelineboundary", "liststates"):
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
if mode == "fork":
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
    configuration = source / "CarryOn/App/CreationConfigurationView.swift"
    text = configuration.read_text()
    save = text.split('Button("完成") {', 1)[1].split('}.disabled', 1)[0]
    text = text.replace('    var body: some View {', '    private func fixtureSave() {' + save + '}\n    var body: some View {', 1)
    text = text.replace('}.presentationDetents([.medium])', '}.presentationDetents([.medium])\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.configuration.choose"))) { _ in mode = "plan"; approval = "never" }\n            .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.configuration.save"))) { _ in fixtureSave() }\n', 1)
    configuration.write_text(text)
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
    creation = source / "CarryOn/App/ConversationActions.swift"
    text = creation.read_text().replace('.task(id: model.scope) { projects', '.onChange(of: creationModels) { _, value in NotificationCenter.default.post(name: Notification.Name("fixture.creation.modelsReady"), object: value != nil) }\n                .onChange(of: projects) { _, value in NotificationCenter.default.post(name: Notification.Name("fixture.creation.projectsReady"), object: !value.isEmpty) }\n                .task(id: model.scope) { projects', 1)
    creation.write_text(text)
    review = source / "CarryOn/App/ConversationChangesView.swift"
    text = review.read_text().replace('.sheet(item: $commentLine)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.comment"))) { _ in\n                    commentScope = model.scope; commentPath = "src/example.swift"; commentText = "请检查这里的边界"\n                    commentSourceID = "change"; commentPatch = history["timeline"].array.first?["data"]["changes"].array.first?["diff"].text ?? ""\n                    commentLine = UnifiedDiff.lines(commentPatch).first { $0.location == "R2" }\n                }\n                .onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.submitComment"))) { _ in\n                    if let line = commentLine { addComment(line) }\n                }\n                .sheet(item: $commentLine)', 1)
    text = text.replace('.sheet(item: $commentLine)', '.onReceive(NotificationCenter.default.publisher(for: Notification.Name("fixture.wrapDiff"))) { _ in wrapLines.toggle() }\n                .sheet(item: $commentLine)', 1)
    review.write_text(text)
    diff = source / "CarryOn/App/UnifiedDiffView.swift"
    diff_text = diff.read_text().replace('.contextMenu {', '.background(DiffFixtureMarker(id: line.id))\n                        .contextMenu {', 1)
    diff_text += """
private struct DiffFixtureMarker: UIViewRepresentable {
    let id: Int
    func makeUIView(context: Context) -> UIView { let view = UIView(); view.isUserInteractionEnabled = false; return view }
    func updateUIView(_ view: UIView, context: Context) { view.accessibilityIdentifier = "fixture-diff-line-" + String(id) }
}
"""
    diff.write_text(diff_text)
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
if mode == "conversationvisual":
    import runpy
    runpy.run_path(str(repo / "tests/fixtures/ios_side_message_actions.py"), init_globals={"source": source})
if mode in ("timelineboundary", "timelineperformance"):
    import runpy
if mode == "timelineperformance":
    runpy.run_path(str(repo / "tests/fixtures/ios_timeline_stream_observation.py"), init_globals={"source": source})
if mode == "timelineboundary":
    runpy.run_path(str(repo / "tests/fixtures/ios_timeline_row_operations.py"), init_globals={"source": source})
    runpy.run_path(str(repo / "tests/fixtures/ios_paragraph_sizing.py"), init_globals={"source": source})
if mode == "timelineboundary":
    runpy.run_path(str(repo / "tests/fixtures/ios_conversation_list_guards.py"), init_globals={"source": source})
if mode in ("composer", "conversationvisual", "timelineboundary"):
    import runpy
    runpy.run_path(str(repo / "tests/fixtures/ios_clipboard_isolation.py"), init_globals={"source": source})
project = source / "CarryOn.xcodeproj/project.pbxproj"
project.write_text(project.read_text().replace("com.hanzeal.carryon", "com.hanzeal.carryon." + mode + "regression"))
# The project bundles its product configuration from the adjacent package.
(work / "carryon").mkdir(exist_ok=True)
shutil.copy2(repo / "carryon/product.json", work / "carryon/product.json")
device = sys.argv[1]
with (work / "build.log").open("w") as log:
    subprocess.run(["xcodebuild", "-project", str(source / "CarryOn.xcodeproj"), "-scheme", "CarryOn",
                    "-configuration", build_configuration, "-sdk", "iphonesimulator", "-destination", f"id={device}",
                    "-derivedDataPath", str(work / "build"), "-clonedSourcePackagesDirPath", os.environ.get("CARRYON_SWIFT_PACKAGES", str(repo / "iOS/.build/SourcePackages")),
                    "-skipPackageUpdates", "ARCHS=arm64", "CODE_SIGN_IDENTITY=-", "build"], stdout=log, stderr=subprocess.STDOUT, check=True)
app = work / f"build/Build/Products/{build_configuration}-iphonesimulator/CarryOn.app"
subprocess.run(["xcrun", "simctl", "install", device, str(app)], check=True)
bundle = "com.hanzeal.carryon." + mode + "regression"
container = Path(subprocess.check_output(["xcrun", "simctl", "get_app_container", device, bundle, "data"], text=True).strip())
result = container / ("Documents/" + mode + "-result.json")
# A previous test result must not satisfy this run.
previous = result.stat().st_mtime_ns if result.exists() else None
screens = ("parity-new-single", "parity-new-multiline", "parity-new-image") if mode == "parity" else ("uploads-menu", "uploads-picker") if mode == "uploads" else ("tabs-top",) if mode == "tabs" else ("official-composer-keyboard",) if mode == "conversationvisual" else ()
for name in screens:
    (container / ("Documents/" + name + ".capture")).unlink(missing_ok=True)
    (container / ("Documents/" + name + ".captured")).unlink(missing_ok=True)
captured = set()
launch_started = time.time_ns()
subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", f"--stdout={work / 'simulator.log'}", f"--stderr={work / 'simulator-errors.log'}", device, bundle], check=True)
# Includes cold simulator launch and the expanded asynchronous delivery scenarios.
for _ in range(450 if mode == "liststates" else 300):
    for name in screens:
        marker = container / ("Documents/" + name + ".capture")
        if name not in captured and marker.exists():
            subprocess.run(["xcrun", "simctl", "io", device, "screenshot", str(work / (name + ".png"))], check=True, stdout=subprocess.DEVNULL)
            (container / ("Documents/" + name + ".captured")).touch()
            captured.add(name)
    if result.exists() and result.stat().st_mtime_ns != previous and (container / ("Documents/" + mode + ".png")).exists() and (container / ("Documents/" + mode + ".png")).stat().st_mtime_ns >= launch_started:
        data = json.loads(result.read_text())
        shutil.copy2(result, work / "result.json")
        shutil.copy2(container / ("Documents/" + mode + ".png"), work / (mode + ".png"))
        if mode == "liststates":
            for image in (container / "Documents").glob("liststates-*.png"):
                shutil.copy2(image, work / image.name)
        if mode == "sections":
            shutil.copy2(container / "Documents/section-management.png", work / "section-management.png")
            shutil.copy2(container / "Documents/section-order.png", work / "section-order.png")
        if mode == "archives":
            for name in ("archive-unknown", "archive-restore"):
                shutil.copy2(container / ("Documents/" + name + ".png"), work / (name + ".png"))
        if mode in ("timeline", "timelineperformance"):
            shutil.copy2(container / "Documents/samples.json", work / "samples.json")
        if mode == "conversationvisual":
            shutil.copy2(container / "Documents/side-model-long.png", work / "side-model-long.png")
            shutil.copy2(container / "Documents/official-composer-comparison.png", work / "official-composer-comparison.png")
        if mode == "parity":
            for name in ("parity-new", "parity-diff", "parity-diff-wrap", "parity-diff-large", "parity-local-comment", "parity-skills", "parity-goal"):
                shutil.copy2(container / ("Documents/" + name + ".png"), work / (name + ".png"))
        if set(screens) != captured: raise SystemExit("Missing screenshots: " + str(set(screens) - captured))
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0 if data["passed"] else 1)
    time.sleep(0.2)
raise SystemExit(f"{mode} regression did not produce a result within 60 seconds")
