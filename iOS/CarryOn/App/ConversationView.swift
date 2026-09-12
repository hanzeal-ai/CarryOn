import SwiftUI
import PhotosUI
import QuickLook
import CarryOnCore

struct ConversationView: View {
    @Environment(AppModel.self) private var model
    let thread: Record
    @State private var menu = false
    @State private var modelInfo = false
    @State private var visibleCount = 120
    @State private var bottomVisible = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var photos: [PhotosPickerItem] = []
    private var images: [String] {
        get { model.draftImages }
        nonmutating set { model.draftImages = newValue }
    }
    @State private var loadingImages = false
    @State private var selectionGeneration = UUID()
    var body: some View {
        @Bindable var model = model
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        if let failure = model.historyFailure, model.history == .null { BlankState(text: "加载失败", symbol: "wifi.exclamationmark", detail: failure, retry: { model.retryHistory() }) }
                        else if model.history == .null { BlankState(text: model.device?.value["online"].bool == false ? "工作区已离线" : "正在加载会话…", loading: model.device?.value["online"].bool != false, symbol: "wifi.slash") }
                        let timeline = groupedTimeline(model.history["timeline"].array)
                        if let failure = model.historyFailure, model.history != .null {
                            HStack { Text(failure).font(.caption).foregroundStyle(Design.secondary); Spacer(); Button("重试") { model.retryHistory() } }
                        }
                        if model.history["historyWindow"]["hasMore"].bool == true {
                            Button("加载更早记录") { visibleCount += 120; model.loadEarlierHistory() }.font(.caption).frame(minHeight: 44).disabled(!model.connected)
                        }
                        if model.historyFailure == nil && model.history["syncing"].bool == true && !timeline.isEmpty { Text("已显示本地记录，正在同步原生历史").font(.caption).foregroundStyle(Design.secondary) }
                        if timeline.count > visibleCount { Button("显示更早记录（还有 \(timeline.count - visibleCount) 条）") { visibleCount += 120 }.font(.caption).frame(minHeight: 44) }
                        ForEach(Array(timeline.suffix(visibleCount).enumerated()), id: \.element.stableID) { _, item in
                            if item["type"].text == "activityGroup" {
                                DisclosureGroup {
                                    ForEach(item["items"].array, id: \.stableID) { child in TimelineEntry(item: child, threadID: thread.id) }
                                } label: { Label("执行活动 · \(item["items"].array.count) 项", systemImage: "terminal") }.font(.caption).tint(Design.secondary).disclosureGroupStyle(CompactActivityStyle())
                            } else { TimelineEntry(item: item, threadID: thread.id) }
                        }
                        if model.historyFailure == nil && model.history != .null && timeline.isEmpty && model.visibleOutgoing.isEmpty { BlankState(text: model.history["syncing"].bool == true ? "正在同步会话…" : "暂无会话记录", loading: model.history["syncing"].bool == true, symbol: "bubble.left.and.bubble.right") }
                        ForEach(model.history["controls"]["requests"].array, id: \.requestKey) { request in
                            NativeRequestView(request: request).id(request.requestKey)
                        }
                        let unsupported = model.history["pendingRequests"].array.count - model.history["controls"]["requests"].array.count
                        if unsupported > 0 { Text("另有 \(unsupported) 项请求尚未适配，请在 Codex App 处理。").font(.caption).foregroundStyle(Design.secondary) }
                        if !model.history["queue"]["messages"].array.isEmpty {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("等待队列").font(.caption).fontWeight(.semibold)
                                ForEach(model.history["queue"]["messages"].array, id: \.stableID) { Text($0["text"].text).font(.caption).textSelection(.enabled) }
                            }.padding(13).frame(maxWidth: .infinity, alignment: .leading).background(Design.background, in: RoundedRectangle(cornerRadius: 12))
                        }
                        ForEach(model.visibleOutgoing, id: \.stableID) { item in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(item["prompt"].text.isEmpty ? "图片消息" : OutgoingMessageProjection.displayText(item["prompt"].text)).textSelection(.enabled)
                                let labels = ["sending": "发送中…", "preparing": "发送中…", "dispatching": "发送中…", "failed": "发送失败，请核对请求记录", "uncertain": "结果待核对，请勿重复发送"]
                                Text(labels[item["state"].text] ?? (item["kind"].text == "operation:queue-add" ? "已排队，等待同步" : "已接收，等待同步")).font(.caption).foregroundStyle(Design.secondary)
                                if item["state"].text == "failed" { Button("清除提示") { model.outgoing.removeValue(forKey: item["id"].text) }.font(.caption) }
                            }.padding(13).frame(maxWidth: .infinity, alignment: .leading).background(Design.background, in: RoundedRectangle(cornerRadius: 12))
                        }
                        if model.historyFailure == nil && model.state == "running" && !timeline.isEmpty && model.history["syncing"].bool != true { HStack { ProgressView().controlSize(.mini); Text("正在继续处理").font(.caption) }.foregroundStyle(Design.secondary) }
                        Color.clear.frame(height: 1).id("bottom")
                            .onAppear { bottomVisible = true; markRead() }.onDisappear { bottomVisible = false }
                    }.padding(.horizontal, 21).padding(.vertical, 20)
                }.scrollDismissesKeyboard(.interactively)
                    .overlay(alignment: .bottomTrailing) {
                        if !bottomVisible && !model.history["timeline"].array.isEmpty {
                            Button { withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) { proxy.scrollTo("bottom", anchor: .bottom) } } label: {
                                Image(systemName: "arrow.down").font(.system(size: 18, weight: .medium)).frame(width: 44, height: 44)
                            }.background(.regularMaterial, in: Circle()).overlay(Circle().stroke(Color.black.opacity(0.08)))
                                .accessibilityLabel("回到最新消息").padding(12)
                        }
                    }
                    .onChange(of: model.historyRevision) { old, _ in
                        if bottomVisible || old == 0 { proxy.scrollTo("bottom", anchor: .bottom); markRead() }
                    }
            }
            VStack(spacing: 5) {
                if !images.isEmpty {
                    HStack {
                        Text("已选择 \(images.count) 张图片").font(.caption)
                        Spacer(); Button("移除图片") { images = []; photos = [] }.font(.caption).frame(minHeight: 44)
                    }.padding(.horizontal, 14)
                }
                Composer(text: $model.draft, disabled: !model.canWrite || loadingImages || (model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && images.isEmpty && model.state != "running"),
                         stopping: model.state == "running" && model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && images.isEmpty,
                         modelInfo: { modelInfo = true }, send: {
                    Task {
                        if model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && images.isEmpty && model.state == "running" {
                            _ = await model.operation("interrupt", fields: ["expectedTurnId": model.history["controls"]["activeTurnId"]])
                        } else {
                            if !images.isEmpty && model.state != "idle" { model.error = "当前状态不支持附图，图片和草稿已保留"; return }
                            if await model.compose(images: images.map(JSONValue.string)) { photos = [] }
                        }
                    }
                }) {
                    PhotosPicker(selection: $photos, maxSelectionCount: 3, matching: .images) {
                        Image(systemName: "plus").font(.system(size: 21)).frame(width: 44, height: 44)
                    }.disabled(!model.canWrite || model.state != "idle" || loadingImages).accessibilityLabel("添加图片，仅空闲会话可用")
                }
            }.background(.white)
        }.background(.white)
            .navigationTitle(thread.title).navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) {
                Button { menu = true } label: { Image(systemName: "ellipsis") }.accessibilityLabel("会话操作")
            } }
            .safeAreaInset(edge: .top, spacing: 0) {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(model.connectionLabel + executionDuration(model.history["timeline"].array, earlier: model.history["earlierDurationMs"].int ?? 0, now: context.date))
                        .font(.caption2).foregroundStyle(Design.secondary).padding(5)
                }
            }
            .sheet(isPresented: $menu) { ConversationMenu() }
            .sheet(isPresented: $modelInfo) { ModelInformationView() }
            .onChange(of: photos) { _, selection in Task { await loadPhotos(selection) } }
            .onDisappear { selectionGeneration = UUID(); loadingImages = false }
    }
    private func markRead() {
        let sequence = model.readSequence
        Task { await model.markDisplayed(threadID: thread.id, sequence: sequence) }
    }
    private func loadPhotos(_ selection: [PhotosPickerItem]) async {
        guard !selection.isEmpty else { return }
        let generation = UUID(); selectionGeneration = generation
        loadingImages = true; defer { if selectionGeneration == generation { loadingImages = false } }
        do {
            var result: [String] = []
            for photo in selection {
                guard let data = try await photo.loadTransferable(type: Data.self), let image = UIImage(data: data) else { throw APIError("图片无法读取") }
                let scale = min(1, 1280 / max(image.size.width, image.size.height))
                let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
                let format = UIGraphicsImageRendererFormat(); format.scale = 1
                let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
                var encoded: Data?
                for quality in [0.75, 0.5, 0.3, 0.15] { if let bytes = resized.jpegData(compressionQuality: quality), bytes.count <= 200 * 1024 { encoded = bytes; break } }
                guard let encoded else { throw APIError("图片压缩后仍超过 200 KB，请选择更小的图片") }
                result.append("data:image/jpeg;base64," + encoded.base64EncodedString())
            }
            if selectionGeneration == generation { images = result }
        } catch { if selectionGeneration == generation { model.report(error) } }
    }
}
struct Composer<Attachment: View>: View {
    @Binding var text: String
    var disabled = false
    var stopping = false
    var modelInfo: (() -> Void)?
    let send: () -> Void
    @ViewBuilder var attachment: Attachment
    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            attachment.foregroundStyle(Design.secondary)
            TextField("继续对话…", text: $text, axis: .vertical).font(.system(size: 16)).lineLimit(1...5).padding(.vertical, 11).padding(.leading, 4)
            if let modelInfo { Button(action: modelInfo) { Image(systemName: "slider.horizontal.3").frame(width: 44, height: 44) }.foregroundStyle(Design.secondary).accessibilityLabel("模型与思考强度") }
            Button(action: send) {
                Image(systemName: stopping ? "stop.fill" : "arrow.up").font(.system(size: stopping ? 13 : 18, weight: .semibold)).foregroundStyle(.white).frame(width: 36, height: 36).background(Design.ink, in: Circle()).frame(width: 44, height: 44)
            }.disabled(disabled).opacity(disabled ? 0.4 : 1).accessibilityLabel(stopping ? "停止任务" : "发送")
        }.padding(.horizontal, 5).padding(.vertical, 3).background(Color(white: 0.985), in: RoundedRectangle(cornerRadius: 25)).overlay(RoundedRectangle(cornerRadius: 25).stroke(Color.black.opacity(0.11))).padding(.horizontal, 14).padding(.vertical, 10)
    }
}
extension JSONValue {
    var stableID: String { self["id"].string ?? formatted }
    var requestKey: String { self["id"].formatted + ":" + self["fingerprint"].text }
}
struct TimelineEntry: View {
    @Environment(AppModel.self) private var model
    let item: JSONValue
    let threadID: String
    var body: some View {
        let kind = item["type"].text
        if kind == "turn" {
            Text(item["title"].text + " · " + item["status"].text).font(.system(size: 10)).foregroundStyle(Design.secondary).frame(maxWidth: .infinity).padding(.vertical, 3)
        } else if ["userMessage", "steeringUserMessage", "agentMessage"].contains(kind) {
            let user = kind != "agentMessage"
            VStack(alignment: .leading, spacing: 11) {
                if !user { Label("Codex", systemImage: "asterisk.circle.fill").font(.system(size: 12, weight: .semibold)).padding(.top, 8) }
                let parts = item["data"]["content"].array + item["data"]["input"].array
                let nativePaths = Set(parts.filter { $0["type"].text == "localImage" }.map { $0["path"].text })
                let refs = item["artifacts"].array.filter { !nativePaths.contains($0["path"].text) }
                MessageThumbnails(parts: parts, refs: refs, threadID: threadID, alignTrailing: user)
                Text(user ? (item["displayText"].string ?? item["text"].text) : attachmentDisplayText(item)).font(.system(size: 15)).lineSpacing(user ? 5 : 7).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    .padding(user ? 13 : 0).background(user ? Design.background : .clear, in: RoundedRectangle(cornerRadius: 19))
                ForEach(item["asyncQuestions"].array, id: \.stableID) { question in AsyncQuestionView(question: question, threadID: threadID) }
                ForEach(refs.filter { $0["kind"].text != "image" }, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID) }
            }.padding(.leading, user ? 32 : 0)
                .contextMenu { Button("复制原文") { UIPasteboard.general.string = item["text"].text } }
        } else if !item["artifacts"].array.isEmpty {
            MessageThumbnails(parts: [], refs: item["artifacts"].array, threadID: threadID)
            ForEach(item["artifacts"].array.filter { $0["kind"].text != "image" }, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID) }
        } else {
            DisclosureGroup {
                if !(item["data"].object ?? [:]).isEmpty { Text(item["data"].formatted).font(.system(size: 11, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 2) }
                if item["supported"].bool == false { Text("此类型尚未适配，请在 Codex App 查看完整内容。").font(.caption) }
            } label: {
                Label(item["title"].string ?? kind, systemImage: kind == "fileChange" ? "doc.text" : "terminal").font(.system(size: 12)).foregroundStyle(Design.secondary)
            }.tint(Design.secondary).disclosureGroupStyle(CompactActivityStyle())
        }
    }
}
struct MessageImage: View {
    @Environment(AppModel.self) private var model
    let part: JSONValue
    let threadID: String
    @State private var image: UIImage?
    @State private var failure: String?
    @State private var showImage = false
    var body: some View {
        Group {
            if let image { Button { showImage = true } label: { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 88).clipped() }.buttonStyle(.plain).accessibilityLabel("打开原图") }
            else if let failure { Button { self.failure = nil } label: { Label("重试", systemImage: "arrow.clockwise").font(.caption) }.accessibilityHint(failure) }
            else { ProgressView().task { await load() } }
        }.frame(width: 88, height: 88).clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.black.opacity(0.12)))
            .background(ImageLightboxPresenter(image: image, isPresented: $showImage).frame(width: 0, height: 0))
            .onDisappear { if !showImage { image = nil } }
    }
    private func load() async {
        do {
            var url = part["url"].text
            if part["type"].text == "localImage" {
                let result = try await model.deviceRequest("/api/threads/\(ConsoleAddress.component(threadID))/images/\(ConsoleAddress.component(part["imageId"].text))")
                url = result["url"].text
            }
            guard url.hasPrefix("data:image/"), url.utf8.count < 12_000_000, let comma = url.firstIndex(of: ","),
                  let data = Data(base64Encoded: String(url[url.index(after: comma)...])), let decoded = UIImage(data: data) else { throw APIError("图片格式不受支持") }
            try Task.checkCancellation()
            image = decoded
        } catch { failure = error.localizedDescription }
    }
}
struct ModelInformationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 15) {
                Paper {
                    SettingRow(icon: "sparkles", title: "当前模型", value: model.history["controls"]["settings"]["model"].string ?? model.history["metadata"]["latestModel"].string ?? "未提供")
                    SettingRow(icon: "slider.horizontal.3", title: "思考强度", value: model.history["controls"]["settings"]["effort"].string ?? model.history["metadata"]["latestReasoningEffort"].string ?? "未提供")
                }
                Text("服务端尚未提供可用模型目录，请在 Codex App 中调整。").font(.caption).foregroundStyle(Design.secondary)
                Spacer()
            }.padding(20).background(Design.background).navigationTitle("模型与思考强度").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }.presentationDetents([.medium])
    }
}

private func groupedTimeline(_ items: [JSONValue]) -> [JSONValue] {
    var result: [JSONValue] = [], pending: [JSONValue] = []
    func flush() {
        if let first = pending.first {
            result.append(.object(["id": .string(first.stableID + ":group"), "type": .string("activityGroup"), "items": .array(pending)]))
            pending = []
        }
    }
    for item in items {
        if !["turn", "userMessage", "steeringUserMessage", "agentMessage", "error"].contains(item["type"].text) && item["artifacts"].array.isEmpty { pending.append(item) }
        else { flush(); result.append(item) }
    }
    flush(); return result
}
private func executionDuration(_ items: [JSONValue], earlier: Int = 0, now: Date) -> String {
    var elapsed = Double(earlier)
    for item in items where item["type"].text == "turn" {
        if case .number(let duration) = item["data"]["durationMs"] { elapsed += duration }
        else if item["status"].text == "inProgress", case .number(let start) = item["data"]["turnStartedAtMs"] { elapsed += max(0, now.timeIntervalSince1970 * 1000 - start) }
    }
    guard elapsed > 0 else { return "" }
    let seconds = Int(elapsed / 1000)
    return " · 已执行 \(seconds / 60)分\(seconds % 60)秒"
}

struct ArtifactView: View {
    @Environment(AppModel.self) private var model
    let ref: JSONValue
    let threadID: String
    @State private var image: UIImage?
    @State private var preview: URL?
    @State private var showImage = false
    @State private var localFile: URL?
    @State private var failure: String?
    @State private var loading = false
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if ref["kind"].text != "image" { Button(ref["name"].text) { Task { await load(); preview = localFile } }
                .font(.caption).bold().disabled(loading).accessibilityHint("预览文件") }
            if let image { Button { showImage = true } label: { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 88).clipped().clipShape(RoundedRectangle(cornerRadius: 12)) }.buttonStyle(.plain).accessibilityLabel("打开原图") }
            if loading { ProgressView() }
            if let failure { Text(failure).font(.caption).foregroundStyle(.red) }
            HStack {
                if ref["kind"].text != "image", let localFile { ShareLink(item: localFile) { Label("分享文件", systemImage: "square.and.arrow.up") } }
            }.font(.caption)
        }
        .frame(width: ref["kind"].text == "image" ? 88 : nil, height: ref["kind"].text == "image" ? 88 : nil)
        .task(id: ref.stableID) { if ref["kind"].text == "image" { await load() } }
        .quickLookPreview($preview)
        .background(ImageLightboxPresenter(image: image, isPresented: $showImage).frame(width: 0, height: 0))
        .onDisappear { if let localFile { try? FileManager.default.removeItem(at: localFile.deletingLastPathComponent()) }; localFile = nil; if !showImage { image = nil } }
    }
    private func load() async {
        guard localFile == nil, !loading else { return }
        loading = true; defer { loading = false }
        do {
            if let url = ref["url"].string, url.hasPrefix("data:image/"), let comma = url.firstIndex(of: ","),
               let data = Data(base64Encoded: String(url[url.index(after: comma)...])), data.count <= 8 * 1024 * 1024,
               let decoded = UIImage(data: data) {
                image = decoded
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let mime = String(url.prefix(while: { $0 != ";" })).replacingOccurrences(of: "data:image/", with: "")
                let file = folder.appendingPathComponent("image." + (["png", "jpeg", "gif", "webp"].contains(mime) ? mime : "png"))
                try data.write(to: file, options: .atomic)
                localFile = file
                return
            }
            let result = try await model.deviceRequest("/api/threads/\(ConsoleAddress.component(threadID))/artifacts/\(ConsoleAddress.component(ref["id"].text))")
            guard let data = Data(base64Encoded: result["base64"].text), data.count <= 8 * 1024 * 1024 else { throw APIError("附件内容无效") }
            try Task.checkCancellation()
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let name = (ref["name"].text as NSString).lastPathComponent
            let file = folder.appendingPathComponent(name.isEmpty || name == "." || name == ".." ? "attachment" : name)
            try data.write(to: file, options: .atomic)
            localFile = file; image = UIImage(data: data); failure = nil
        } catch { failure = error.localizedDescription }
    }
}

private func attachmentDisplayText(_ item: JSONValue) -> String {
    let text = item["text"].text
    guard let regex = try? NSRegularExpression(pattern: #"!?\[([^\]\n]*)\]\((<[^>\n]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)"#) else { return text }
    var output = text
    for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
        guard let full = Range(match.range, in: output), let labelRange = Range(match.range(at: 1), in: text), let targetRange = Range(match.range(at: 2), in: text) else { continue }
        let target = String(text[targetRange]).trimmingCharacters(in: CharacterSet(charactersIn: "<>"))
        let path = (target.removingPercentEncoding ?? target).replacingOccurrences(of: #":\d+(?::\d+)?$"#, with: "", options: .regularExpression)
        if item["artifacts"].array.contains(where: { $0["path"].text == path }) { output.replaceSubrange(full, with: text[labelRange]) }
    }
    return output
}

private struct CompactActivityStyle: DisclosureGroupStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Button { configuration.isExpanded.toggle() } label: {
                HStack(spacing: 6) {
                    configuration.label
                    Image(systemName: "chevron.down").font(.system(size: 9))
                    Spacer(minLength: 0)
                }.contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityValue(configuration.isExpanded ? "已展开" : "已收起")
            if configuration.isExpanded { VStack(alignment: .leading, spacing: 0) { configuration.content } }
        }
    }
}

struct AsyncQuestionView: View {
    @Environment(AppModel.self) private var model
    let question: JSONValue
    let threadID: String
    @State private var expanded = false
    @State private var initialized = false
    @State private var touched = false
    @State private var selected = ""
    @State private var custom = ""
    @State private var useCustom = false
    @State private var submitting = false
    @State private var submitted = false
    @State private var lastSubmission: String?
    private var answer: String { (useCustom ? custom : selected).trimmingCharacters(in: .whitespacesAndNewlines) }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if expanded {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Label("问题", systemImage: "questionmark.bubble").font(.caption).foregroundStyle(Design.secondary)
                        Spacer()
                        Button { touched = true; expanded = false } label: { Image(systemName: "xmark") }.accessibilityLabel("收起问题")
                    }
                    Text(question["title"].text).font(.system(size: 14)).fixedSize(horizontal: false, vertical: true)
                    ForEach(Array(question["options"].array.enumerated()), id: \.offset) { index, option in
                        Button { touched = true; selected = option.text; useCustom = false } label: {
                            HStack(spacing: 10) {
                                Text("\(index + 1)").font(.caption).frame(width: 28, height: 28)
                                    .background(!useCustom && selected == option.text ? Design.ink : Color.black.opacity(0.05), in: Circle())
                                    .foregroundStyle(!useCustom && selected == option.text ? .white : Design.secondary)
                                Text(option.text).font(.system(size: 14)).multilineTextAlignment(.leading)
                                Spacer(minLength: 0)
                            }.frame(minHeight: 40).contentShape(Rectangle())
                        }.buttonStyle(.plain).accessibilityAddTraits(!useCustom && selected == option.text ? .isSelected : [])
                    }
                    TextField("或输入你的回答", text: $custom, axis: .vertical).font(.system(size: 14)).lineLimit(1...4)
                        .onTapGesture { touched = true; useCustom = true }
                        .onChange(of: custom) { _, _ in touched = true; useCustom = true }
                    HStack {
                        Spacer()
                        Button("跳过") { touched = true; expanded = false }
                        Button("发送") { Task { await send() } }.buttonStyle(.borderedProminent)
                            .disabled(answer.isEmpty || answer == lastSubmission || !model.canWrite || submitting)
                    }.font(.caption)
                }.padding(16).background(Design.background, in: RoundedRectangle(cornerRadius: 18)).disabled(submitting)
            } else {
                Button { touched = true; expanded = true } label: {
                    Label(question["answer"] != .null ? "回答已同步" : submitted ? "回答已发送，等待同步" : "回答问题", systemImage: "questionmark.bubble")
                        .font(.caption).padding(.horizontal, 12).padding(.vertical, 8)
                        .overlay(Capsule().stroke(Color.black.opacity(0.12)))
                }.buttonStyle(.plain)
            }
        }
        .task(id: question.stableID) {
            if !initialized {
                initialized = true; selected = question["answer"].string ?? question["options"].array.first?.text ?? ""
                lastSubmission = question["answer"].string
                if let previous = lastSubmission, !question["options"].array.contains(.string(previous)) { custom = previous; useCustom = true }
                expanded = question["active"].bool == true && question["answer"] == .null
            }
            do { try await Task.sleep(for: .seconds(30)); if !touched { expanded = false } } catch {}
        }
        .onChange(of: question["answer"]) { _, value in if value != .null { submitted = true; lastSubmission = value.string; expanded = false } }
        .onChange(of: question["active"]) { _, value in if value.bool != true && !touched { expanded = false } }
    }
    private func send() async {
        guard !submitting, !answer.isEmpty, answer != lastSubmission, model.canWrite, model.selectedThread?.id == threadID else { return }
        touched = true; submitting = true; defer { submitting = false }
        let sent = answer
        if await model.answerQuestion(question, answer: sent, threadID: threadID) { submitted = true; lastSubmission = sent; expanded = false }
    }
}

private struct MessageThumbnails: View {
    let parts: [JSONValue]
    let refs: [JSONValue]
    let threadID: String
    var alignTrailing = false
    var body: some View {
        let images = parts.filter { ["image", "localImage"].contains($0["type"].text) }
        let artifacts = refs.filter { $0["kind"].text == "image" }
        if !images.isEmpty || !artifacts.isEmpty {
            GeometryReader { geometry in
              ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Array(images.enumerated()), id: \.offset) { _, part in MessageImage(part: part, threadID: threadID) }
                    ForEach(artifacts, id: \.stableID) { ref in ArtifactView(ref: ref, threadID: threadID) }
                }.frame(minWidth: geometry.size.width, alignment: alignTrailing ? .trailing : .leading)
              }
            }.frame(height: 88)
        }
    }
}
