import AppKit
import Carbon.HIToolbox

/// A global shortcut the owner can choose in Settings. There is no key
/// recorder: a short list of combinations that rarely clash is enough.
struct ShortcutChoice: Sendable, Equatable {
    let id: String
    let label: String
    let keyCode: UInt32
    /// Carbon modifier flags (`optionKey`, `controlKey`, ...), as `RegisterEventHotKey` takes them.
    let modifiers: UInt32
}

enum Shortcuts {
    static let off = "off"
    static let defaultSummon = "option-space"
    static let defaultTalk = "control-option-space"

    private static let option = UInt32(optionKey)
    private static let control = UInt32(controlKey)
    private static let shift = UInt32(shiftKey)
    private static let command = UInt32(cmdKey)
    private static let space = UInt32(kVK_Space)

    static let choices: [ShortcutChoice] = [
        ShortcutChoice(id: "option-space", label: "⌥ Space", keyCode: space, modifiers: option),
        ShortcutChoice(id: "control-option-space", label: "⌃⌥ Space", keyCode: space, modifiers: control | option),
        ShortcutChoice(id: "shift-option-space", label: "⇧⌥ Space", keyCode: space, modifiers: shift | option),
        ShortcutChoice(id: "control-shift-space", label: "⌃⇧ Space", keyCode: space, modifiers: control | shift),
        ShortcutChoice(id: "command-shift-space", label: "⇧⌘ Space", keyCode: space, modifiers: shift | command),
        ShortcutChoice(id: "control-option-v", label: "⌃⌥ V", keyCode: UInt32(kVK_ANSI_V), modifiers: control | option),
        ShortcutChoice(id: "control-option-t", label: "⌃⌥ T", keyCode: UInt32(kVK_ANSI_T), modifiers: control | option),
    ]

    static func choice(_ id: String) -> ShortcutChoice? {
        choices.first { $0.id == id }
    }

    /// A known choice or `off`; anything else falls back to `fallback`.
    static func known(_ id: String?, or fallback: String) -> String {
        guard let id else { return fallback }
        return id == off || choice(id) != nil ? id : fallback
    }
}

/// What the app shows when it opens.
enum OpenWith: String, Sendable {
    case house
    case widget
}

/// The shell's own preferences, set in Settings, This Mac, "Widget and shortcuts".
struct ShellPrefs: Equatable, Sendable {
    /// The widget shows by itself whenever the app runs. Off, it waits for a shortcut or the menu.
    var widget = true
    var summon = Shortcuts.defaultSummon
    var talk = Shortcuts.defaultTalk
    var openWith = OpenWith.house
}

/// Where the preferences and the widget's places are kept: the app's user
/// defaults, or, for the self-test, memory only, so a test never changes the
/// owner's choices.
@MainActor
final class PrefStore {
    private let defaults: UserDefaults?
    private var memory: [String: Any] = [:]

    init(defaults: UserDefaults?) {
        self.defaults = defaults
    }

    static func standard() -> PrefStore { PrefStore(defaults: .standard) }
    static func inMemory() -> PrefStore { PrefStore(defaults: nil) }

    private func value(_ key: String) -> Any? {
        defaults == nil ? memory[key] : defaults?.object(forKey: key)
    }

    private func set(_ value: Any, _ key: String) {
        if let defaults { defaults.set(value, forKey: key) } else { memory[key] = value }
    }

    func load() -> ShellPrefs {
        ShellPrefs(
            widget: value("widget.enabled") as? Bool ?? true,
            summon: Shortcuts.known(value("shortcut.summon") as? String, or: Shortcuts.defaultSummon),
            talk: Shortcuts.known(value("shortcut.talk") as? String, or: Shortcuts.defaultTalk),
            openWith: OpenWith(rawValue: value("open.with") as? String ?? "") ?? .house
        )
    }

    func save(_ prefs: ShellPrefs) {
        set(prefs.widget, "widget.enabled")
        set(prefs.summon, "shortcut.summon")
        set(prefs.talk, "shortcut.talk")
        set(prefs.openWith.rawValue, "open.with")
    }

    /// The widget's top-left corner for this arrangement of screens, if it was ever placed there.
    func place(for layout: String) -> NSPoint? {
        guard let pair = value("widget.place.\(layout)") as? [Double], pair.count == 2 else { return nil }
        return NSPoint(x: pair[0], y: pair[1])
    }

    func setPlace(_ point: NSPoint, for layout: String) {
        set([Double(point.x), Double(point.y)], "widget.place.\(layout)")
    }
}
