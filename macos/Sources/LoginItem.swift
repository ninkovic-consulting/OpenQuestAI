import Foundation
import ServiceManagement

/// Opening the app at login, hidden, so the assistant is running after you log in.
///
/// The supported route is `SMAppService.mainApp` (macOS 13 and later). If the
/// system refuses to register this ad-hoc signed app, a per-user LaunchAgent
/// that runs `open -g -j -a <app> --args --login` is written instead.
@MainActor
enum LoginItem {
    enum State: String {
        case enabled
        case requiresApproval = "requires-approval"
        case off
    }

    static let fallbackLabel = "org.openquestai.vision.login"
    static let loginArgument = "--login"

    static var fallbackPlist: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/\(fallbackLabel).plist")
    }

    static var state: State {
        switch SMAppService.mainApp.status {
        case .enabled: return .enabled
        case .requiresApproval: return .requiresApproval
        default: return FileManager.default.fileExists(atPath: fallbackPlist.path) ? .enabled : .off
        }
    }

    static func enable() throws {
        do {
            try SMAppService.mainApp.register()
        } catch {
            guard state == .off else { return }
            try writeFallback()
        }
    }

    static func disable() throws {
        if SMAppService.mainApp.status != .notRegistered, SMAppService.mainApp.status != .notFound {
            try SMAppService.mainApp.unregister()
        }
        if FileManager.default.fileExists(atPath: fallbackPlist.path) {
            try FileManager.default.removeItem(at: fallbackPlist)
        }
    }

    /// Turns it on or off; the menu toggle and the page's settings both come here.
    static func set(_ enabled: Bool) throws {
        if enabled { try enable() } else { try disable() }
    }

    static func openSettings() {
        SMAppService.openSystemSettingsLoginItems()
    }

    private static func writeFallback() throws {
        let plist: [String: Any] = [
            "Label": fallbackLabel,
            "ProgramArguments": ["/usr/bin/open", "-g", "-j", "-a", Bundle.main.bundlePath, "--args", loginArgument],
            "RunAtLoad": true,
            "LimitLoadToSessionType": "Aqua",
        ]
        let data = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try FileManager.default.createDirectory(
            at: fallbackPlist.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try data.write(to: fallbackPlist, options: .atomic)
    }

    /// `<app> --login-item on|off|status`, for `vision setup` and `vision doctor`.
    /// Prints the resulting state (enabled, requires-approval or off).
    static func command(_ verb: String) -> Int32 {
        do {
            switch verb {
            case "on": try enable()
            case "off": try disable()
            case "status": break
            default:
                FileHandle.standardError.write(Data("usage: --login-item on|off|status\n".utf8))
                return 2
            }
        } catch {
            FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
            return 1
        }
        print(state.rawValue)
        return 0
    }
}
