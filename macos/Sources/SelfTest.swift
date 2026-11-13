import AppKit

/// `<app> --self-test <result.json>`: a check for automation.
///
/// Runs the daemon in a throwaway home with voice off and the fake brain, on a
/// free port, opens a window (not full screen), waits until the page reports that it is
/// connected, then does the same for the widget, shows and hides it, minimizes the app to the
/// menu bar and opens the house again (recording the activation policy and the window
/// each time), reads whether the two shortcuts registered and the notch inset of the
/// screen, writes the result and quits. Never touches the real home,
/// and keeps the shell's preferences in memory.
@MainActor
final class SelfTest {
    static let flag = "--self-test"
    static let timeout: TimeInterval = 30

    /// Every bridge method; the probes look for each and call none.
    static let bridgeMethods = """
    ["token", "chooseFolder", "micStatus", "requestMic", "openSystemSettings",
     "loginItemEnabled", "setLoginItem", "restartDaemon", "appInfo", "quit", "finishDeleteAll",
     "widgetPrefs", "setWidgetPrefs", "showWidget", "dismissWidget", "openHouse", "fitWidget",
     "goToBackground", "safeAreaTop"]
    """

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
        bridge: \(bridgeMethods).filter((m) => typeof window.pywebview?.api?.[m] !== "function"),
      });
    })()
    """

    /// What the widget shows: connected once its state is neither offline nor connecting and it
    /// names the assistant; `hooks` is true when the shell's summon and talk can reach it.
    static let widgetProbe = """
    (() => {
      const root = document.querySelector(".widget");
      const name = document.querySelector(".widget .w-name");
      const state = root ? root.dataset.state : null;
      return JSON.stringify({
        state,
        offline: state === null || state === "offline" || state === "connecting",
        name: name ? name.textContent : "",
        height: root ? Math.round(root.getBoundingClientRect().height) : 0,
        hooks: typeof window.visionWidget?.summon === "function" && typeof window.visionWidget?.talk === "function",
        bridge: \(bridgeMethods).filter((m) => typeof window.pywebview?.api?.[m] !== "function"),
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

    /// Polls the house until it is connected, then the widget; shows and hides the widget;
    /// reads the shortcuts; then quits.
    func run(window: MainWindow, background: Background, supervisor: Supervisor) {
        Task {
            var report: [String: Any] = [:]
            let house = await poll(supervisor: supervisor) { await window.pageView?.evaluate(Self.probe) } ready: { page in
                page["offline"] as? Bool == false && !(page["wordmark"] as? String ?? "").isEmpty
                    && (page["bridge"] as? [Any])?.isEmpty == true
            }
            report["page"] = house.page
            guard house.ok else {
                return finish(ok: false, report: report, background: background, supervisor: supervisor, error: house.error)
            }
            let widget = await poll(supervisor: supervisor) { await background.widget.evaluate(Self.widgetProbe) } ready: { page in
                page["offline"] as? Bool == false && !(page["name"] as? String ?? "").isEmpty
                    && page["hooks"] as? Bool == true && (page["bridge"] as? [Any])?.isEmpty == true
            }
            background.setWidgetShown(true)
            let shown = background.widget.isVisible
            background.setWidgetShown(false)
            let hidden = !background.widget.isVisible
            background.setWidgetShown(true)
            report["widget"] = [
                "page": widget.page,
                "connected": widget.ok,
                "shown_after_show": shown,
                "hidden_after_hide": hidden,
                "frame": Self.describe(background.widget.panel.frame),
            ]
            report["shortcuts"] = Self.shortcuts(background)
            let away = await Self.background(window: window, background: background)
            report["menu_bar"] = away.report
            report["safe_area"] = [
                "window_top": Double(window.safeTop),
                "screen_top": Double(NSScreen.main?.safeAreaInsets.top ?? 0),
                "screens": NSScreen.screens.map { ["name": $0.localizedName, "top": Double($0.safeAreaInsets.top)] },
            ]
            let ok = widget.ok && shown && hidden && away.ok
            let why = away.ok ? "the widget did not show and hide" : "Minimize (to the menu bar) did not work"
            finish(ok: ok, report: report, background: background, supervisor: supervisor,
                   error: ok ? nil : widget.error ?? why)
        }
    }

    private struct Poll {
        var ok: Bool
        var page: [String: Any]
        var error: String?
    }

    /// Runs `probe` every half second until `ready` says yes, the daemon stops, or the time is up.
    private func poll(
        supervisor: Supervisor, probe: () async -> String?, ready: ([String: Any]) -> Bool
    ) async -> Poll {
        var last: [String: Any] = [:]
        while Date().timeIntervalSince(started) < Self.timeout {
            if let json = await probe(),
               let page = try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any] {
                last = page
                if ready(page) { return Poll(ok: true, page: page) }
            }
            if case .stopped(let reason) = supervisor.phase { return Poll(ok: false, page: last, error: reason) }
            try? await Task.sleep(for: .milliseconds(500))
        }
        return Poll(ok: false, page: last, error: "not connected within \(Int(Self.timeout)) s")
    }

    /// Minimize (to the menu bar) and back: the window closes and the app leaves the Dock, the widget stays;
    /// opening the house brings the window and the Dock icon back.
    private static func background(window: MainWindow, background: Background) async -> (ok: Bool, report: [String: Any]) {
        func policy() -> String {
            switch NSApp.activationPolicy() {
            case .regular: return "regular"
            case .accessory: return "accessory"
            default: return "prohibited"
            }
        }
        let before = policy()
        background.goToBackground()
        try? await Task.sleep(for: .milliseconds(300))
        let away = ["policy": policy(), "window_open": window.isVisible, "widget_shown": background.widget.isVisible] as [String: Any]
        background.openHouse()
        try? await Task.sleep(for: .milliseconds(300))
        let back = ["policy": policy(), "window_open": window.isVisible] as [String: Any]
        let ok = away["policy"] as? String == "accessory" && away["window_open"] as? Bool == false
            && away["widget_shown"] as? Bool == true
            && back["policy"] as? String == "regular" && back["window_open"] as? Bool == true
        return (ok, ["before": before, "in_menu_bar": away, "house_again": back])
    }

    private static func shortcuts(_ background: Background) -> [String: Any] {
        var out: [String: Any] = [:]
        for role in HotKeys.Role.allCases {
            let s = background.hotKeys.status[role]
            out[role.key] = [
                "shortcut": s?.shortcut ?? "",
                "registered": s?.registered ?? false,
                "problem": s?.problem ?? NSNull(),
            ]
        }
        return out
    }

    private static func describe(_ r: NSRect) -> [String: Int] {
        ["x": Int(r.minX), "y": Int(r.minY), "width": Int(r.width), "height": Int(r.height)]
    }

    private func finish(
        ok: Bool, report: [String: Any], background: Background, supervisor: Supervisor, error: String?
    ) {
        guard !finished else { return }
        finished = true
        passed = ok
        // The shortcuts are let go at once, so the test holds them no longer than it must.
        background.stop()
        var result = report
        result["ok"] = ok
        result["seconds"] = (Date().timeIntervalSince(started) * 10).rounded() / 10
        result["daemon_started_by_app"] = supervisor.startedDaemon
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
