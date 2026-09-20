/// Finish displaying the current snapshot, then catch up to the latest request.
/// New arrivals replace pending work, never invalidate work already in progress.
@MainActor public final class ConversationRefreshQueue {
    private var pending: (@MainActor () async -> Void)?
    private var running = false

    public init() {}

    public func request(_ refresh: @escaping @MainActor () async -> Void) {
        pending = refresh
        guard !running else { return }
        running = true
        Task { @MainActor in
            defer { running = false }
            while let refresh = pending {
                pending = nil
                await refresh()
            }
        }
    }
}
