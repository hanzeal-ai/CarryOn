import Foundation

/// A single serial queue for one login/workspace. Only server-confirmed cursors are deduplicated.
@MainActor public final class ReadReceiptSync {
    private var pending: [String: Int] = [:]
    private var confirmed: [String: Int] = [:]
    private var worker: Task<Void, Never>?
    private var generation = UUID()
    private let sleep: @MainActor (Duration) async throws -> Void

    public init(sleep: @escaping @MainActor (Duration) async throws -> Void = { try await Task.sleep(for: $0) }) {
        self.sleep = sleep
    }
    public func reset() {
        generation = UUID(); worker?.cancel(); worker = nil
        pending = [:]; confirmed = [:]
    }
    public func enqueue(threadID: String, sequence: Int,
                        send: @escaping @MainActor (String, Int) async throws -> Void,
                        failure: @escaping @MainActor (Error, Bool) -> Void) {
        guard sequence > (confirmed[threadID] ?? 0) else { return }
        pending[threadID] = max(sequence, pending[threadID] ?? 0)
        guard worker == nil else { return }
        let version = generation
        worker = Task { [weak self] in
            guard let self else { return }
            defer { if self.generation == version { self.worker = nil } }
            var failures = 0
            var reported = false
            while !Task.isCancelled, self.generation == version, let thread = self.pending.keys.sorted().first {
                let sequence = self.pending[thread]!
                do {
                    try await send(thread, sequence)
                    guard !Task.isCancelled, self.generation == version else { return }
                    self.confirmed[thread] = sequence
                    if self.pending[thread] == sequence { self.pending.removeValue(forKey: thread) }
                    failures = 0; reported = false
                } catch {
                    guard !Task.isCancelled, self.generation == version else { return }
                    let native = error as NSError
                    if error is CancellationError || (native.domain == NSURLErrorDomain && native.code == NSURLErrorCancelled) { return }
                    let transient = [429, 503].contains((error as? APIError)?.status ?? 0) || native.domain == NSURLErrorDomain
                    guard transient else {
                        self.pending.removeValue(forKey: thread)
                        failure(error, false)
                        continue
                    }
                    failures += 1
                    if failures >= 4 && !reported { reported = true; failure(error, true) }
                    let delay: Duration = failures == 1 ? .milliseconds(500) : failures == 2 ? .seconds(1) : failures == 3 ? .seconds(2) : .seconds(30)
                    do { try await self.sleep(delay) } catch { return }
                }
            }
        }
    }
}
