import AppKit

/// `<app> --self-test <result.json>`: a check for automation.
///
/// Runs the daemon in a throwaway home with voice off and the fake brain, on a
/// free port, opens a window (not full screen), waits until the page reports that it is
/// connected, writes the result and quits. Never touches the real home.
@MainActor
final class SelfTest {
    static let flag = "--self-test"
    static let timeout: TimeInterval = 20

    /// What the page shows: connected once the state is not offline and the plan has named
    /// the assistant. The bridge's methods are only looked for, never called: no panel,
    /// no permission prompt, no login item change. `bridge` lists any that are missing.
    static let probe = """
    (() => {
      const state = document.querySelector(".panel .state");
      const wordmark = document.querySelector(".panel .wordmark");
      return JSON.stringify({
        state: state ? state.textContent : null,
        offline: state ? state.classList.contains("is-offline") : true,
        wordmark: wordmark ? wordmark.textContent : "",
        bridge: ["token", "chooseFolder", "micStatus", "requestMic", "openSystemSettings",
                 "loginItemEnabled", "setLoginItem", "restartDaemon", "appInfo"]
          .filter((m) => typeof window.pywebview?.api?.[m] !== "function"),
      });
    })()
    """

    let home: URL
    private let resultFile: URL
    private let started = Date()
    private var finished = false
    private(set) var passed = false

    init(resultFile: URL) throws {
        self.resultFile = resultFile
        home = FileManager.default.temporaryDirectory
            .appendingPathComponent("vision-self-test-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        try Data("[voice]\nenabled = false\n".utf8).write(to: home.appendingPathComponent("config.toml"))
    }

    /// Polls the page until it is connected or the time is up, then quits.
    func run(window: MainWindow, supervisor: Supervisor) {
        Task {
            var last: [String: Any] = [:]
            while Date().timeIntervalSince(started) < Self.timeout {
                if let json = await window.pageView?.evaluate(Self.probe),
                   let page = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any] {
                    last = page
                    let connected = page["offline"] as? Bool == false && !(page["wordmark"] as? String ?? "").isEmpty
                    let bridged = (page["bridge"] as? [Any])?.isEmpty == true
                    if connected && bridged {
                        finish(ok: true, page: page, supervisor: supervisor, error: nil)
                        return
                    }
                }
                if case .stopped(let reason) = supervisor.phase {
                    finish(ok: false, page: last, supervisor: supervisor, error: reason)
                    return
                }
                try? await Task.sleep(for: .milliseconds(500))
            }
            finish(ok: false, page: last, supervisor: supervisor, error: "not connected within \(Int(Self.timeout)) s")
        }
    }

    private func finish(ok: Bool, page: [String: Any], supervisor: Supervisor, error: String?) {
        guard !finished else { return }
        finished = true
        passed = ok
        var result: [String: Any] = [
            "ok": ok,
            "seconds": (Date().timeIntervalSince(started) * 10).rounded() / 10,
            "daemon_started_by_app": supervisor.startedDaemon,
            "page": page,
        ]
        if let error { result["error"] = error }
        if let data = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: resultFile)
        }
        // Through the run loop, not this task: quitting from inside main-queue work stalls.
        NSApp.perform(#selector(NSApplication.terminate(_:)), with: nil, afterDelay: 0)
    }

    func cleanUp() {
        try? FileManager.default.removeItem(at: home)
    }

    /// A port nothing is listening on, so the test never meets the real daemon.
    static func freePort() -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_port = 0
        var size = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, size) }
        }
        _ = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &size) }
        }
        return Int(UInt16(bigEndian: addr.sin_port))
    }
}
