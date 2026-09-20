import Network
import Observation

@MainActor @Observable final class ConnectivityMonitor {
    private(set) var available: Bool?
    private let monitor = NWPathMonitor()
    init() {
        monitor.pathUpdateHandler = { [weak self] path in
            let available = path.status == .satisfied
            Task { @MainActor [weak self] in self?.available = available }
        }
        monitor.start(queue: DispatchQueue(label: "carryon.connectivity"))
    }
    deinit { monitor.cancel() }
}
