import AppKit

/// The menu bar item: Open, the assistant's state, Start at login, Quit.
@MainActor
final class StatusMenu: NSObject, NSMenuDelegate {
    private let name: String
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let stateLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let loginToggle: NSMenuItem

    init(name: String, open: Selector, login: Selector) {
        self.name = name
        loginToggle = NSMenuItem(title: "Start at login", action: login, keyEquivalent: "")
        super.init()
        item.button?.image = ArmchairIcon.make()
        item.button?.toolTip = name

        let menu = NSMenu()
        menu.autoenablesItems = false
        menu.delegate = self
        menu.addItem(NSMenuItem(title: "Open \(name)", action: open, keyEquivalent: ""))
        stateLine.isEnabled = false
        menu.addItem(stateLine)
        menu.addItem(.separator())
        menu.addItem(loginToggle)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit \(name)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        item.menu = menu
        show(.starting)
    }

    func show(_ phase: Phase) {
        let word: String
        switch phase {
        case .starting: word = "starting"
        case .stopped: word = "not running"
        case .ready(_, let state): word = Self.word(for: state)
        }
        stateLine.title = "\(name) is \(word)"
    }

    /// The state line in the user's words: idle, listening, thinking or speaking.
    static func word(for state: String) -> String {
        switch state {
        case "listening", "transcribing": return "listening"
        case "thinking": return "thinking"
        case "speaking": return "speaking"
        default: return "idle"
        }
    }

    func menuWillOpen(_ menu: NSMenu) {
        switch LoginItem.state {
        case .enabled:
            loginToggle.title = "Start at login"
            loginToggle.state = .on
        case .requiresApproval:
            loginToggle.title = "Start at login (approve in System Settings)"
            loginToggle.state = .mixed
        case .off:
            loginToggle.title = "Start at login"
            loginToggle.state = .off
        }
    }
}
