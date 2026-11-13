import AppKit

/// Running in the background: the floating widget, the two global shortcuts,
/// and the shell's own preferences for them, which the page reads and writes
/// through the bridge. Hiding the widget, like closing the house, never stops
/// the assistant.
@MainActor
final class Background {
    let widget: WidgetPanel
    let hotKeys = HotKeys()
    private let store: PrefStore
    private(set) var prefs: ShellPrefs
    /// Opens the house window; the app delegate sets it.
    var openHouse: () -> Void = {}
    /// Closes the house window and leaves the app in the menu bar; the app delegate sets it.
    var goToBackground: () -> Void = {}
    /// The app's last step after Delete all data, given what to tell the owner; the app delegate sets it.
    var finishDeleteAll: (String) async -> Void = { _ in }

    init(settings: Settings, supervisor: Supervisor, store: PrefStore) {
        self.store = store
        prefs = store.load()
        widget = WidgetPanel(settings: settings, supervisor: supervisor, store: store)
        widget.shell = self
        hotKeys.onPress = { [weak self] role in
            switch role {
            case .summon: self?.summon()
            case .talk: self?.talk(true)
            }
        }
        hotKeys.onRelease = { [weak self] role in
            if role == .talk { self?.talk(false) }
        }
        hotKeys.apply(summon: prefs.summon, talk: prefs.talk)
    }

    /// At start: the house opens only with "When the app opens: the house"; the widget shows
    /// when it is on, or when the app opens with the widget only.
    var opensHouse: Bool { prefs.openWith == .house }

    func start() {
        if prefs.widget || prefs.openWith == .widget { widget.show(focus: false) }
    }

    func render(_ phase: Phase) {
        widget.render(phase)
    }

    func stop() {
        hotKeys.unregisterAll()
    }

    // MARK: Showing

    func setWidgetShown(_ shown: Bool) {
        if shown { widget.show(focus: false) } else { widget.hide() }
    }

    /// The summon shortcut: up with the cursor in the chat field, or, pressed again, away.
    func summon() {
        if widget.isVisible && widget.isKey {
            dismiss()
            return
        }
        widget.show(focus: true)
        Task { _ = await widget.evaluate("window.visionWidget && window.visionWidget.summon()") }
    }

    /// Escape in the widget, or the summon shortcut again: the keyboard goes back to the app
    /// in front; the widget stays if it is on, and goes if it was only called up.
    func dismiss() {
        if prefs.widget { widget.resign() } else { widget.hide() }
    }

    /// Push to talk: key down starts listening, key up stops. The widget's page sends
    /// `input.ptt`, as the house's hold-to-talk does, and shows that it listens. The page
    /// is loaded whenever the daemon answers, shown or not, so this works with the widget
    /// hidden and the house closed: in `hold` the daemon opens the microphone on the press
    /// and closes it after the release (and on its own if the page goes away meanwhile).
    func talk(_ down: Bool) {
        if down && !widget.isVisible { widget.show(focus: false) }
        Task { _ = await widget.evaluate("window.visionWidget && window.visionWidget.talk(\(down))") }
    }

    // MARK: Preferences, for the bridge

    /// `{widget, openWith, summon, talk, shown, shortcuts: [{id, label}], status: {summon, talk}}`.
    func prefsAnswer() -> [String: Any] {
        func state(_ role: HotKeys.Role) -> [String: Any] {
            let s = hotKeys.status[role]
            return ["registered": s?.registered ?? false, "problem": s?.problem ?? NSNull()]
        }
        return [
            "widget": prefs.widget,
            "openWith": prefs.openWith.rawValue,
            "summon": prefs.summon,
            "talk": prefs.talk,
            "shown": widget.isVisible,
            "shortcuts": Shortcuts.choices.map { ["id": $0.id, "label": $0.label] },
            "status": ["summon": state(.summon), "talk": state(.talk)],
        ]
    }

    /// Applies the changes the page sends (any of `widget`, `openWith`, `summon`, `talk`) and answers as `prefsAnswer`.
    func update(_ changes: [String: Any]) throws -> [String: Any] {
        var next = prefs
        if let on = changes["widget"] as? Bool { next.widget = on }
        if let raw = changes["openWith"] as? String {
            guard let value = OpenWith(rawValue: raw) else { throw ShellError("unknown openWith \(raw)") }
            next.openWith = value
        }
        for (key, path) in [("summon", \ShellPrefs.summon), ("talk", \ShellPrefs.talk)] {
            guard let id = changes[key] as? String else { continue }
            guard id == Shortcuts.off || Shortcuts.choice(id) != nil else { throw ShellError("unknown shortcut \(id)") }
            next[keyPath: path] = id
        }
        let before = prefs
        prefs = next
        store.save(next)
        if next.summon != before.summon || next.talk != before.talk {
            hotKeys.apply(summon: next.summon, talk: next.talk)
        }
        if next.widget != before.widget { setWidgetShown(next.widget) }
        return prefsAnswer()
    }

    /// The page's height and drag handle, `[x, y, width, height]` from its top left.
    func fit(height: Double, handle: [Double]) {
        let rect = handle.count == 4 ? NSRect(x: handle[0], y: handle[1], width: handle[2], height: handle[3]) : .zero
        widget.fit(height: CGFloat(height), handle: rect)
    }
}
