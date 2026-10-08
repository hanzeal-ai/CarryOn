import SwiftUI
import AVFoundation
import CarryOnCore

/// Conversion runs only on the engine's serial input tap; UI receives owned PCM bytes.
private final class VoicePCMEncoder: @unchecked Sendable {
    let converter: AVAudioConverter
    let output: AVAudioFormat
    init?(input: AVAudioFormat) {
        guard let output = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1),
              let converter = AVAudioConverter(from: input, to: output) else { return nil }
        self.output = output; self.converter = converter
    }
    func encode(_ input: AVAudioPCMBuffer) -> Data? {
        let count = AVAudioFrameCount(ceil(Double(input.frameLength) * 24_000 / input.format.sampleRate)) + 16
        guard let buffer = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: count) else { return nil }
        final class Input: @unchecked Sendable {
            var supplied = false
            let buffer: AVAudioPCMBuffer
            init(_ buffer: AVAudioPCMBuffer) { self.buffer = buffer }
        }
        let source = Input(input)
        var failure: NSError?
        converter.convert(to: buffer, error: &failure) { _, status in
            if source.supplied { status.pointee = .noDataNow; return nil }
            source.supplied = true; status.pointee = .haveData; return source.buffer
        }
        guard failure == nil, let samples = buffer.floatChannelData?[0] else { return nil }
        var bytes = Data(capacity: Int(buffer.frameLength) * 2)
        for index in 0..<Int(buffer.frameLength) {
            let value = max(-1, min(1, samples[index]))
            var sample = Int16((value * (value < 0 ? 32768 : 32767)).rounded()).littleEndian
            withUnsafeBytes(of: &sample) { bytes.append(contentsOf: $0) }
        }
        return bytes
    }
}

@MainActor @Observable private final class VoiceConversation {
    var status = "正在准备麦克风…"
    var transcript = ""
    var muted = false
    var finished = false
    var stopping = false
    private let model: AppModel
    private let target: ConversationActionTarget
    private let epoch: UUID
    private var voiceID: String?
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var tapInstalled = false
    private var sequence = 0
    private var inputSequence = 0
    private var queuedPlayback = 0
    private var pendingPCM = Data()
    private var queue: [Data] = []
    private var uploading = false
    private var polling: Task<Void, Never>?
    private var mediaClosed = false
    private var current: Bool { model.scope == target.scope && model.epoch == epoch && model.selectedThread?.id == target.threadID }
    init(model: AppModel, target: ConversationActionTarget) { self.model = model; self.target = target; self.epoch = model.epoch }
    private func request(_ suffix: String, body: JSONValue? = nil) async throws -> JSONValue {
        guard current, model.allowsRequest("/api/threads/" + target.threadID + suffix, body: body) else { throw APIError("会话或语音权限已改变") }
        let result = try await model.deviceRequest("/api/threads/" + ConsoleAddress.component(target.threadID) + suffix, body: body)
        guard current else { throw APIError("会话已改变") }
        return result
    }
    func start() async {
        do {
            let previous = try await request("/voice?after=0")
            if ["starting", "active", "stopping", "unknown"].contains(previous["voice"]["state"].text) {
                voiceID = previous["voice"]["id"].string
                status = "已有语音会话，结束后可重新启动"; return
            }
            guard await AVAudioApplication.requestRecordPermission() else { throw APIError("请在系统设置中允许麦克风") }
            guard current, !mediaClosed else { return }
            let audio = AVAudioSession.sharedInstance()
            try audio.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
            try audio.setActive(true)
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1))
            try engine.start(); player.play()
            let ok = await model.write(path: target.path("operations"), target: target.threadID, body: .object(["action": .string("voice-start")])) { job in
                if self.current { self.voiceID = job["result"]["voiceId"].string }
            }
            guard current else { closeMedia(); return }
            guard ok, voiceID != nil else { throw APIError(model.error ?? "语音启动结果待核对") }
            if mediaClosed { stopping = false; await stop(); return }
            polling = Task { await poll() }
        } catch {
            closeMedia(); status = error.localizedDescription
            if current, let result = try? await request("/voice?after=0"), ["starting", "active", "stopping", "unknown"].contains(result["voice"]["state"].text) { voiceID = result["voice"]["id"].string; stopping = false; await stop() }
        }
    }
    private func capture() throws {
        guard !tapInstalled else { return }
        let input = engine.inputNode, format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, let encoder = VoicePCMEncoder(input: format) else { throw APIError("无法初始化麦克风音频格式") }
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            guard let data = encoder.encode(buffer) else { return }
            Task { @MainActor [weak self] in self?.receive(data) }
        }
        tapInstalled = true
    }
    private func receive(_ data: Data) {
        guard !mediaClosed, !muted, current else { return }
        pendingPCM.append(data)
        while pendingPCM.count >= 4800 {
            guard queue.count < 10 else { status = "音频上传积压，已停止"; Task { await stop() }; return }
            queue.append(Data(pendingPCM.prefix(4800))); pendingPCM.removeFirst(4800)
        }
        if !uploading, !queue.isEmpty { uploading = true; Task { await upload() } }
    }
    private func upload() async {
        defer { uploading = false }
        do {
            while !queue.isEmpty, !mediaClosed {
                guard let voiceID else { throw APIError("语音身份未确认") }
                let data = queue.removeFirst(); inputSequence += 1
                _ = try await request("/voice/audio", body: .object(["voiceId": .string(voiceID), "sequence": .number(Double(inputSequence)), "audio": .object([
                    "data": .string(data.base64EncodedString()), "sampleRate": .number(24000), "numChannels": .number(1), "samplesPerChannel": .number(Double(data.count / 2))])]))
            }
        } catch { status = error.localizedDescription; await stop() }
    }
    private func play(_ audio: JSONValue) throws {
        guard audio["sampleRate"].int == 24000, audio["numChannels"].int == 1,
              let encoded = audio["data"].string, let data = Data(base64Encoded: encoded), data.count % 2 == 0, data.count <= 480000,
              let format = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(data.count / 2)), let samples = buffer.floatChannelData?[0] else { throw APIError("收到不支持的音频格式") }
        guard queuedPlayback + data.count <= 240000 else { throw APIError("音频播放积压，请结束后重试") }
        buffer.frameLength = buffer.frameCapacity
        for index in 0..<Int(buffer.frameLength) { samples[index] = Float(Int16(bitPattern: UInt16(data[index * 2]) | UInt16(data[index * 2 + 1]) << 8)) / 32768 }
        queuedPlayback += data.count
        let count = data.count
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in Task { @MainActor [weak self] in self?.queuedPlayback = max(0, (self?.queuedPlayback ?? 0) - count) } }
    }
    private func poll() async {
        do {
            while !Task.isCancelled, current {
                let result = try await request("/voice?after=" + String(sequence))
                guard result["voice"]["id"].string == voiceID else { throw APIError("语音会话已改变") }
                let state = result["voice"]["state"].text
                status = result["voice"]["error"].string ?? ["starting": "正在连接…", "active": muted ? "已静音" : "正在聆听", "stopping": "正在结束…", "unknown": "语音状态待核对", "closed": "语音已结束"][state] ?? state
                if result["dropped"].bool == true { player.stop(); queuedPlayback = 0; player.play() }
                for event in result["events"].array {
                    if event["type"].text == "outputAudio/delta", !mediaClosed { try play(event["audio"]) }
                    if event["type"].text == "transcript/delta" { transcript = String((transcript + event["delta"].text).suffix(16000)) }
                    if event["type"].text == "transcript/done" { transcript += "\n" }
                }
                sequence = result["sequence"].int ?? 0
                if state == "closed" { closeMedia(); finished = true; return }
                if state == "active", !mediaClosed { try capture() }
                try await Task.sleep(for: .milliseconds(150))
            }
            closeMedia()
        } catch { if !Task.isCancelled { status = error.localizedDescription; await stop() } }
    }
    func audioRouteChanged() { if tapInstalled { Task { await stop() } } }
    func toggleMute() { muted.toggle(); pendingPCM.removeAll(); queue.removeAll() }
    private func closeMedia() {
        mediaClosed = true
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        player.stop(); engine.stop(); queue.removeAll(); pendingPCM.removeAll(); queuedPlayback = 0
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
    func stop() async {
        guard !stopping else { return }; stopping = true; closeMedia(); polling?.cancel(); polling = nil
        guard current, let voiceID, model.allows(.stop) else { stopping = false; return }
        let ok = await model.write(path: target.path("operations"), target: target.threadID, body: .object(["action": .string("voice-stop"), "voiceId": .string(voiceID)]))
        guard current else { return }
        if !ok { status = model.error ?? "结束结果待核对"; stopping = false; return }
        status = "结束请求已提交，等待原生关闭"
        for _ in 0..<30 {
            guard current else { return }
            if let result = try? await request("/voice?after=" + String(sequence)), result["voice"]["id"].string == voiceID, result["voice"]["state"].text == "closed" { status = "语音已结束"; finished = true; return }
            try? await Task.sleep(for: .milliseconds(300))
        }
        status = "原生关闭尚未确认，请核对语音状态"; stopping = false
    }
}

struct VoiceConversationView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let target: ConversationActionTarget
    @State private var session: VoiceConversation?
    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Image(systemName: "waveform").font(.system(size: 54)).padding(.top, 32)
                Text(session?.status ?? "正在准备…").foregroundStyle(Design.secondary)
                ScrollView { Text(session?.transcript ?? "").frame(maxWidth: .infinity, alignment: .leading).padding() }
                HStack(spacing: 24) {
                    Button { session?.toggleMute() } label: { Label(session?.muted == true ? "取消静音" : "静音", systemImage: session?.muted == true ? "mic.slash" : "mic") }.disabled(session?.finished == true)
                    Button("结束语音", role: .destructive) { Task { await session?.stop(); dismiss() } }.disabled(session?.stopping == true)
                }.padding(.bottom, 24)
            }
            .navigationTitle("语音聊天").navigationBarTitleDisplayMode(.inline)
            .task { let value = VoiceConversation(model: model, target: target); session = value; await value.start() }
            .onDisappear { Task { await session?.stop() } }
            .onChange(of: model.scope) { _, _ in Task { await session?.stop(); dismiss() } }
            .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)) { note in
                if note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt == AVAudioSession.InterruptionType.began.rawValue { Task { await session?.stop() } }
            }
            .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification)) { _ in session?.audioRouteChanged() }
            .onReceive(NotificationCenter.default.publisher(for: UIApplication.didEnterBackgroundNotification)) { _ in Task { await session?.stop() } }
        }
    }
}
