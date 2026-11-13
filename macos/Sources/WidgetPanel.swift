import AppKit
import WebKit

/// The small floating widget: the daemon's `/widget.html` in a panel that
/// floats above other windows on every Space, full-screen apps included.
///
/// It is a non-activating panel, so showing it, and even typing in it, leaves
/// the app in front where it was. It can be dragged by its top row (the page
/// says where that is) and remembers its place for each arrangement of
/// screens; when a screen goes away it comes back onto one that is there. The
/// page asks for its height; the panel keeps its top edge where it is.
@MainActor
final class WidgetPanel: NSObject, NSWindowDelegate {
    static let width: CGFloat = 380
    static let minHeight: CGFloat = 96
    static let maxHeight: CGFloat = 560
    static let margin: CGFloat = 24

    let panel: FloatingPanel
    private let settings: Settings
    private let supervisor: Supervisor
    private let store: PrefStore
    weak var shell: Background?
    private let placeholder = WidgetPlaceholder()
    private var page: PageView?
    private var pageToken: String?
    /// The page's drag handle, in its own coordinates (origin top left).
    private var handle: NSRect = .zero
    private var placing = false

    var pageView: PageView? { page }
    var isVisible: Bool { panel.isVisible }
    var isKey: Bool { panel.isKeyWindow }

    init(settings: Settings, supervisor: Supervisor, store: PrefStore) {
        self.settings = settings
        self.supervisor = supervisor
        self.store = store
        panel = FloatingPanel(
            contentRect: NSRect(x: 0, y: 0, width: Self.width, height: Self.minHeight),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        super.init()
        panel.title = "\(settings.name) widget"
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = false
        panel.isReleasedWhenClosed = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovable = true
        panel.delegate = self
        panel.contentView = placeholder
        placeholder.show("Waking up…")
        place()
        NotificationCenter.default.addObserver(
            self, selector: #selector(screensChanged),
            name: NSApplication.didChangeScreenParametersNotification, object: nil
        )
    }

    // MARK: Showing

    /// Brings the panel up; with `focus` it takes the keyboard, still without activating the app.
    func show(focus: Bool) {
        if !panel.isVisible { place() }
        if focus {
            panel.makeKeyAndOrderFront(nil)
            if let page { panel.makeFirstResponder(page.webView) }
        } else {
            panel.orderFrontRegardless()
        }
    }

    func hide() {
        panel.orderOut(nil)
    }

    /// Gives the keyboard back to the app in front, leaving the panel where it is.
    func resign() {
        guard panel.isKeyWindow else { return }
        panel.orderOut(nil)
        panel.orderFrontRegardless()
    }

    // MARK: The page

    /// The page while the daemon answers; a line saying why otherwise.
    func render(_ phase: Phase) {
        switch phase {
        case .starting:
            showPlaceholder("Waking up…")
        case .stopped(let reason):
            showPlaceholder(reason)
        case .ready(let token, _):
            showPage(token: token)
        }
    }

    private func showPlaceholder(_ text: String) {
        placeholder.show(text)
        if panel.contentView !== placeholder { panel.contentView = placeholder }
        page?.webView.stopLoading()
        page = nil
        pageToken = nil
        resize(to: placeholder.fittingHeight)
    }

    private func showPage(token: String) {
        if page != nil, pageToken == token { return }
        let page = PageView(
            settings: settings, supervisor: supervisor, token: token, path: "/widget.html", shell: shell
        ) { [weak self] config in
            let view = HandleWebView(frame: .zero, configuration: config)
            view.handle = { self?.handle ?? .zero }
            return view
        }
        page.onLoadFailed = { [weak self] reason in self?.showPlaceholder("The widget did not load: \(reason)") }
        self.page = page
        pageToken = token
        panel.contentView = page.webView
        page.load()
    }

    /// Runs `script` in the widget's page, if it is loaded.
    func evaluate(_ script: String) async -> String? {
        await page?.evaluate(script)
    }

    /// The page's size: `height` in points, `handle` the area it can be dragged by.
    func fit(height: CGFloat, handle: NSRect) {
        self.handle = handle
        resize(to: height)
    }

    private func resize(to height: CGFloat) {
        let h = min(max(height.rounded(.up), Self.minHeight), Self.maxHeight)
        var frame = panel.frame
        guard abs(frame.height - h) >= 1 || frame.width != Self.width else { return }
        frame.origin.y = frame.maxY - h
        frame.size = NSSize(width: Self.width, height: h)
        setFrame(onScreen(frame))
    }

    // MARK: Place

    /// The arrangement of screens, as a key for remembering where the widget was on it.
    static func layoutKey() -> String {
        NSScreen.screens
            .map { "\(Int($0.frame.minX)),\(Int($0.frame.minY)),\(Int($0.frame.width))x\(Int($0.frame.height))" }
            .sorted()
            .joined(separator: ";")
    }

    /// Where it was on this arrangement of screens, or the top right of the main screen.
    private func place() {
        let size = panel.frame.size
        let frame: NSRect
        if let topLeft = store.place(for: Self.layoutKey()) {
            frame = NSRect(x: topLeft.x, y: topLeft.y - size.height, width: size.width, height: size.height)
        } else {
            let visible = (NSScreen.main ?? NSScreen.screens.first)?.visibleFrame ?? .zero
            frame = NSRect(
                x: visible.maxX - size.width - Self.margin, y: visible.maxY - size.height - Self.margin,
                width: size.width, height: size.height
            )
        }
        setFrame(onScreen(frame))
    }

    /// `frame` moved, if need be, to lie whole on the screen it overlaps most.
    static func onScreen(_ frame: NSRect, screens: [NSRect]) -> NSRect {
        guard let first = screens.first else { return frame }
        let area = { (r: NSRect) -> CGFloat in
            let i = r.intersection(frame)
            return i.isNull ? 0 : i.width * i.height
        }
        let target = screens.max { area($0) < area($1) }.flatMap { area($0) > 0 ? $0 : nil } ?? first
        var out = frame
        out.origin.x = min(max(out.minX, target.minX), target.maxX - out.width)
        out.origin.y = min(max(out.minY, target.minY), target.maxY - out.height)
        return out
    }

    private func onScreen(_ frame: NSRect) -> NSRect {
        Self.onScreen(frame, screens: NSScreen.screens.map(\.visibleFrame))
    }

    private func setFrame(_ frame: NSRect) {
        placing = true
        panel.setFrame(frame, display: true)
        placing = false
    }

    @objc private func screensChanged() {
        place()
    }

    // MARK: NSWindowDelegate

    func windowDidMove(_ notification: Notification) {
        guard !placing else { return }
        store.setPlace(NSPoint(x: panel.frame.minX, y: panel.frame.maxY), for: Self.layoutKey())
    }
}

/// A borderless panel that can take the keyboard, and passes the edit shortcuts
/// to the page even though the app (and so its Edit menu) is not active.
final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        if mods == .command || mods == [.command, .shift] {
            let action: Selector? = switch event.charactersIgnoringModifiers?.lowercased() {
            case "x": #selector(NSText.cut(_:))
            case "c": #selector(NSText.copy(_:))
            case "v": #selector(NSText.paste(_:))
            case "a": #selector(NSText.selectAll(_:))
            case "z": mods.contains(.shift) ? Selector(("redo:")) : Selector(("undo:"))
            default: nil
            }
            if let action, NSApp.sendAction(action, to: nil, from: self) { return true }
        }
        return super.performKeyEquivalent(with: event)
    }

    override func noResponder(for eventSelector: Selector) {
        if eventSelector == #selector(NSResponder.keyDown(with:)) { return }
        super.noResponder(for: eventSelector)
    }
}

/// The widget's web view: a press in the page's drag handle moves the panel instead.
final class HandleWebView: KeyWebView {
    var handle: () -> NSRect = { .zero }

    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        let fromTop = isFlipped ? point.y : bounds.height - point.y
        if handle().contains(NSPoint(x: point.x, y: fromTop)), let window {
            window.performDrag(with: event)
            return
        }
        super.mouseDown(with: event)
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// What the widget shows while there is no page: waking up, or why the assistant stopped.
@MainActor
final class WidgetPlaceholder: NSView {
    private let label = NSTextField(wrappingLabelWithString: "")

    init() {
        super.init(frame: NSRect(x: 0, y: 0, width: WidgetPanel.width, height: WidgetPanel.minHeight))
        wantsLayer = true
        layer?.backgroundColor = StatusView.ground.cgColor
        layer?.borderColor = StatusView.text.withAlphaComponent(0.2).cgColor
        layer?.borderWidth = 1
        label.font = .systemFont(ofSize: 13)
        label.textColor = StatusView.text.withAlphaComponent(0.8)
        label.preferredMaxLayoutWidth = WidgetPanel.width - 40
        label.translatesAutoresizingMaskIntoConstraints = false
        addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 20),
            label.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -20),
            label.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("not used") }

    func show(_ text: String) { label.stringValue = text }

    var fittingHeight: CGFloat { max(WidgetPanel.minHeight, label.intrinsicContentSize.height + 40) }
}
