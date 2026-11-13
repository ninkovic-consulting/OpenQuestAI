import Foundation

/// Where the daemon is, as the window and the menu bar item show it.
enum Phase: Equatable {
    case starting
    /// Answering with this home's token; `state` is the assistant's (idle, listening, ...).
    case ready(token: String, state: String)
    case stopped(String)
}

/// Finds or starts the daemon, waits for it, and watches it.
///
/// A daemon already answering on the port is used as it is (for example one
/// started by `vision run` or the LaunchAgent). Otherwise the app starts its
/// own as a child, and only that one is stopped on Quit. After Delete all
/// data (`end()`) it never starts or restarts one again, since a new daemon
/// would make the data folder again.
@MainActor
final class Supervisor {
    static let startTimeout: TimeInterval = 90
    static let pollInterval: Duration = .seconds(2)

    private let settings: Settings
    private let client: DaemonClient
    private var child: DaemonProcess?
    private var watcher: Task<Void, Never>?
    /// Set by `end()`: nothing is started again.
    private(set) var ended = false
    private(set) var phase: Phase = .starting { didSet { if phase != oldValue { onChange(phase) } } }
    var onChange: (Phase) -> Void = { _ in }
    /// How the assistant listens, from the last poll; nil while it does not answer.
    private(set) var listen: Listen? { didSet { if listen != oldValue { onListen(listen) } } }
    var onListen: (Listen?) -> Void = { _ in }

    /// The daemon's token while it answers.
    var token: String? {
        if case .ready(let token, _) = phase { return token }
        return nil
    }

    /// Asks the daemon to listen in `mode`; nil when it did, else why not.
    func setListen(_ mode: String) async -> String? {
        guard let token else { return "\(settings.name) is not running." }
        let refused = await client.setListen(mode, token: token)
        if refused == nil { await refresh(token: token) }
        return refused
    }

    /// Reads the state now rather than at the next poll.
    func refresh() async {
        if let token { await refresh(token: token) }
    }

    private func refresh(token: String) async {
        guard let now = await client.assistantState(token: token) else { return }
        phase = .ready(token: token, state: now.state)
        listen = now.listen
    }

    var startedDaemon: Bool { child != nil }

    init(settings: Settings) {
        self.settings = settings
        self.client = DaemonClient(settings: settings)
    }

    /// Starts (or restarts) watching; starts a daemon if none answers.
    func start() {
        guard !ended else { return }
        watcher?.cancel()
        phase = .starting
        watcher = Task { [weak self] in await self?.run() }
    }

    /// For good, after Delete all data: stop watching, stop the daemon if this app started it,
    /// and never start one again. Phase changes are no longer reported.
    func end() {
        ended = true
        onChange = { _ in }
        onListen = { _ in }
        shutdown()
    }

    /// Stops the daemon if this app started it.
    func shutdown() {
        watcher?.cancel()
        child?.stop()
        child = nil
    }

    /// Stops the daemon this app started and starts it again, keeping the page up.
    /// Returns true once it answers again; false if the app did not start it.
    func restartOwned() async -> Bool {
        guard !ended, let old = child else { return false }
        watcher?.cancel()
        old.stop()
        child = nil
        guard let token = await launch() else { return false }
        phase = .ready(token: token, state: "idle")
        watcher = Task { [weak self] in await self?.watch(token: token) }
        return true
    }

    private func run() async {
        guard let token = await launch() else { return }
        phase = .ready(token: token, state: "idle")
        await watch(token: token)
    }

    /// Starts a daemon unless one answers, then waits for it; nil when it fails.
    private func launch() async -> String? {
        if child?.isRunning != true, await client.status("/api/health", token: nil) == nil {
            do {
                child = try DaemonProcess(settings: settings) { [weak self] status in
                    self?.childExited(status)
                }
            } catch {
                phase = .stopped("\(settings.name) could not start: \(error)")
                return nil
            }
        }
        return await waitUntilReady()
    }

    private func waitUntilReady() async -> String? {
        let deadline = Date().addingTimeInterval(Self.startTimeout)
        while Date() < deadline, !Task.isCancelled {
            if case .stopped = phase { return nil }
            if let token = client.readToken() {
                switch await client.status("/api/health", token: token) {
                case 200:
                    return token
                case 401 where child == nil:
                    phase = .stopped("Something else on port \(settings.port) refuses this home's token (\(settings.home.path)).")
                    return nil
                default:
                    break
                }
            }
            try? await Task.sleep(for: .milliseconds(400))
        }
        if !Task.isCancelled {
            phase = .stopped("\(settings.name) did not answer within \(Int(Self.startTimeout)) seconds. Its log is \(settings.log.path).")
        }
        return nil
    }

    private func watch(token: String) async {
        var misses = 0
        while !Task.isCancelled {
            try? await Task.sleep(for: Self.pollInterval)
            if Task.isCancelled { return }
            if let now = await client.assistantState(token: token) {
                misses = 0
                phase = .ready(token: token, state: now.state)
                listen = now.listen
            } else {
                misses += 1
                if misses >= 2 {
                    listen = nil
                    phase = .stopped("\(settings.name) stopped answering.")
                    return
                }
            }
        }
    }

    private func childExited(_ status: Int32) {
        child = nil
        listen = nil
        watcher?.cancel()
        phase = .stopped("\(settings.name) stopped (exit status \(status)). Its log is \(settings.log.path).")
    }
}
