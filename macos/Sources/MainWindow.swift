import AppKit

/// The one window: the status view until the daemon is ready, then the page.
///
/// Full screen here is a borderless window covering the screen with the
/// pointer, with the Dock and menu bar hidden while the app is in front. It is
/// not macOS's full-screen Space, so Escape stays with the page.
@MainActor
final class MainWindow: NSObject, NSWindowDelegate {
    /// Out of full screen: this size, or 85 percent of a smaller screen, centred.
    static let windowedSize = NSSize(width: 1440, height: 900)
    static let screenShare: CGFloat = 0.85
    /// The smallest the page's layout supports.
    static let minimumSize = NSSize(width: 1100, height: 700)

    private let settings: Settings
    private let supervisor: Supervisor
    private let window: ShellWindow
    private let status: StatusView
    private var page: PageView?
    private var pageToken: String?
    private(set) var isFullScreen: Bool
    var onRestart: () -> Void = {}
    /// Handed to the page's bridge, for the widget block in Settings.
    weak var shell: Background?

    var pageView: PageView? { page }

    init(settings: Settings, supervisor: Supervisor, fullScreen: Bool) {
        self.settings = settings
        self.supervisor = supervisor
        isFullScreen = fullScreen
        window = ShellWindow(
            contentRect: NSRect(origin: .zero, size: Self.windowedSize),
            styleMask: [], backing: .buffered, defer: false
        )
        var restart: () -> Void = {}
        status = StatusView(name: settings.name) { restart() }
        super.init()
        restart = { [weak self] in self?.onRestart() }
        window.title = settings.name
        window.backgroundColor = StatusView.ground
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenNone]
        window.delegate = self
        window.contentView = status
        applyMode()
    }

    func show() {
        if isFullScreen { applyMode() }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate()
        updatePresentation()
    }

    func close() { window.close() }

    func toggleFullScreen() {
        isFullScreen.toggle()
        applyMode()
        updatePresentation()
    }

    /// Shows what the supervisor reports: the page once ready, the status view otherwise.
    func render(_ phase: Phase) {
        switch phase {
        case .starting:
            showStatus("Waking up…", canRestart: false)
        case .stopped(let reason):
            showStatus(reason, canRestart: true)
        case .ready(let token, _):
            showPage(token: token)
        }
    }

    private func showStatus(_ text: String, canRestart: Bool) {
        status.show(text, canRestart: canRestart)
        if window.contentView !== status { window.contentView = status }
        dropPage()
    }

    private func showPage(token: String) {
        guard window.isVisible else { return }
        if let page, pageToken == token {
            if window.contentView !== page.webView { window.contentView = page.webView }
            return
        }
        let page = PageView(settings: settings, supervisor: supervisor, token: token, shell: shell)
        page.onLoadFailed = { [weak self] reason in
            self?.showStatus("The page did not load: \(reason)", canRestart: true)
        }
        self.page = page
        pageToken = token
        window.contentView = page.webView
        page.load()
    }

    /// The scene keeps the GPU busy, so it is torn down whenever it is not shown.
    private func dropPage() {
        page?.webView.stopLoading()
        page = nil
        pageToken = nil
    }

    private func applyMode() {
        let screen = Self.screenWithPointer()
        if isFullScreen {
            window.styleMask = [.borderless]
            window.setFrame(screen.frame, display: true)
            return
        }
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        let visible = screen.visibleFrame
        window.minSize = NSSize(
            width: min(Self.minimumSize.width, visible.width),
            height: min(Self.minimumSize.height, visible.height)
        )
        let size = NSSize(
            width: visible.width < Self.windowedSize.width ? visible.width * Self.screenShare : Self.windowedSize.width,
            height: visible.height < Self.windowedSize.height ? visible.height * Self.screenShare : Self.windowedSize.height
        )
        let origin = NSPoint(x: visible.midX - size.width / 2, y: visible.midY - size.height / 2)
        window.setFrame(NSRect(origin: origin, size: size), display: true)
    }

    private func updatePresentation() {
        NSApp.presentationOptions = isFullScreen && window.isVisible ? [.hideDock, .hideMenuBar] : []
    }

    private static func screenWithPointer() -> NSScreen {
        let pointer = NSEvent.mouseLocation
        return NSScreen.screens.first { NSMouseInRect(pointer, $0.frame, false) }
            ?? NSScreen.main ?? NSScreen.screens[0]
    }

    // MARK: NSWindowDelegate

    func windowWillClose(_ notification: Notification) {
        dropPage()
        window.contentView = status
        NSApp.presentationOptions = []
    }
}

/// A window that can take keys even when borderless, and does not beep at keys the page leaves alone.
final class ShellWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }

    override func noResponder(for eventSelector: Selector) {
        if eventSelector == #selector(NSResponder.keyDown(with:)) { return }
        super.noResponder(for: eventSelector)
    }
}
