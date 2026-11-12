import AVFoundation
import AppKit
import WebKit

/// `window.pywebview.api`: what the page can ask of the app.
///
/// The user script defines the API in the page; every method except `token()`
/// posts `{method, args}` to this handler and gets a promise back. Only the
/// main frame on the daemon's own origin is answered. The web view is held
/// weakly, so the page can be torn down while a call waits.
@MainActor
final class Bridge: NSObject, WKScriptMessageHandlerWithReply {
    static let handlerName = "visionBridge"

    private let settings: Settings
    private let supervisor: Supervisor
    weak var webView: WKWebView?

    init(settings: Settings, supervisor: Supervisor) {
        self.settings = settings
        self.supervisor = supervisor
    }

    /// The page-side API. `token()` answers from the script itself; the rest ask the app.
    static func script(token: String, origin: String) -> String {
        """
        (() => {
          if (location.origin !== \(json(origin))) return;
          const token = \(json(token));
          const handler = window.webkit.messageHandlers.\(handlerName);
          const call = (method, args = []) => handler.postMessage({ method, args });
          const api = Object.freeze({
            token: () => Promise.resolve(token),
            chooseFolder: () => call("chooseFolder").then((p) => (typeof p === "string" ? p : null)),
            micStatus: () => call("micStatus"),
            requestMic: () => call("requestMic"),
            openSystemSettings: (pane) => call("openSystemSettings", [String(pane)]),
            loginItemEnabled: () => call("loginItemEnabled"),
            setLoginItem: (enabled) => call("setLoginItem", [Boolean(enabled)]),
            restartDaemon: () => call("restartDaemon"),
            appInfo: () => call("appInfo"),
          });
          Object.defineProperty(window, "pywebview", { value: Object.freeze({ api }) });
        })();
        """
    }

    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
    ) async -> (Any?, String?) {
        let from = message.frameInfo.securityOrigin
        guard message.frameInfo.isMainFrame,
              "\(from.protocol)://\(from.host):\(from.port)" == settings.origin,
              let body = message.body as? [String: Any],
              let method = body["method"] as? String
        else { return (nil, "not available here") }
        let args = body["args"] as? [Any] ?? []
        do {
            return (try await answer(method, args), nil)
        } catch {
            return (nil, "\(error)")
        }
    }

    private func answer(_ method: String, _ args: [Any]) async throws -> Any? {
        switch method {
        case "chooseFolder":
            guard let webView, let window = webView.window else { return nil }
            let path = await FolderPicker.choose(in: window)
            window.makeKeyAndOrderFront(nil)
            window.makeFirstResponder(webView)
            return path
        case "micStatus":
            return Self.micStatus()
        case "requestMic":
            _ = await AVCaptureDevice.requestAccess(for: .audio)
            return Self.micStatus()
        case "openSystemSettings":
            return SystemSettings.open(args.first as? String ?? "")
        case "loginItemEnabled":
            return LoginItem.state == .enabled
        case "setLoginItem":
            try LoginItem.set(args.first as? Bool ?? false)
            return LoginItem.state == .enabled
        case "restartDaemon":
            return await supervisor.restartOwned()
        case "appInfo":
            let info = Bundle.main.infoDictionary ?? [:]
            return [
                "name": settings.name,
                "version": info["CFBundleShortVersionString"] as? String ?? "",
                "bundleId": Bundle.main.bundleIdentifier ?? "",
                "ownsDaemon": supervisor.startedDaemon,
            ]
        default:
            throw ShellError("unknown method \(method)")
        }
    }

    /// The app's microphone permission: granted, denied, restricted or undetermined.
    /// The daemon is this app's child, so this grant is the one that covers it.
    static func micStatus() -> String {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return "granted"
        case .denied: return "denied"
        case .restricted: return "restricted"
        default: return "undetermined"
        }
    }

    private static func json(_ text: String) -> String {
        let data = try! JSONSerialization.data(withJSONObject: [text])
        return String(String(data: data, encoding: .utf8)!.dropFirst().dropLast())
    }
}

/// Opening System Settings at a pane the page names.
@MainActor
enum SystemSettings {
    static let panes = [
        "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        "files-and-folders": "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders",
    ]

    /// True when the pane is known and was opened.
    static func open(_ pane: String) -> Bool {
        if pane == "login-items" {
            LoginItem.openSettings()
            return true
        }
        guard let link = panes[pane], let url = URL(string: link) else { return false }
        return NSWorkspace.shared.open(url)
    }
}
