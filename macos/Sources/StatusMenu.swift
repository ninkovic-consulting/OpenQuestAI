import AppKit

/// The menu bar item. Its menu: the assistant's name and state, Open the house,
/// Show or Hide widget, the three listening modes with a check on the current
/// one, Start at login and Quit. The icon carries a small dot while a
/// microphone stream is open.
@MainActor
final class StatusMenu: NSObject, NSMenuDelegate {
    private let name: String
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let stateLine = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private let loginToggle: NSMenuItem
    private let widgetToggle: NSMenuItem
    private let widgetShown: () -> Bool
    private var modeItems: [NSMenuItem] = []
    private var listen: Listen?

    init(name: String, open: Selector, widget: Selector, widgetShown: @escaping () -> Bool, listen: Selector, login: Selector) {
        self.name = name
        self.widgetShown = widgetShown
        loginToggle = NSMenuItem(title: "Start at login", action: login, keyEquivalent: "")
        widgetToggle = NSMenuItem(title: "Show widget", action: widget, keyEquivalent: "")
        super.init()
        item.button?.image = ArmchairIcon.make(mic: false)
        item.button?.toolTip = name

        let menu = NSMenu()
        menu.autoenablesItems = false
        menu.delegate = self
        stateLine.isEnabled = false
        menu.addItem(stateLine)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Open the house", action: open, keyEquivalent: ""))
        menu.addItem(widgetToggle)
        menu.addItem(.separator())
        for mode in Listen.modes {
            let entry = NSMenuItem(title: Listen.title(mode), action: listen, keyEquivalent: "")
            entry.representedObject = mode
            modeItems.append(entry)
            menu.addItem(entry)
        }
        menu.addItem(.separator())
        menu.addItem(loginToggle)
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Quit \(name)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        item.menu = menu
        show(.starting)
        show(listen: nil)
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

    /// The listening modes' checks, and the dot on the icon while the microphone is open.
    func show(listen: Listen?) {
        self.listen = listen
        item.button?.image = ArmchairIcon.make(mic: listen?.micOpen == true)
        item.button?.toolTip = listen?.micOpen == true ? "\(name): the microphone is open" : name
        for entry in modeItems {
            entry.state = entry.representedObject as? String == listen?.mode ? .on : .off
            entry.isEnabled = listen?.voice == true
        }
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
        widgetToggle.title = widgetShown() ? "Hide widget" : "Show widget"
        show(listen: listen)
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
