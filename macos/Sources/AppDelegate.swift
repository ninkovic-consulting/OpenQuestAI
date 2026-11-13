import AppKit

/// Owns the daemon, the window, the widget with its shortcuts, and the menu bar item.
///
/// Closing the window or hiding the widget leaves the app and the assistant
/// running. While the house window is closed the app lives in the menu bar
/// only: its activation policy is `.accessory`, so it has no Dock icon and is
/// not in the app switcher; opening the house makes it `.regular` again. The
/// widget is a non-activating panel and the shortcuts are Carbon hot keys, so
/// both work under either policy. Quit stops the daemon only if this app
/// started it.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let settings: Settings
    private let selfTest: SelfTest?
    private let supervisor: Supervisor
    private var window: MainWindow!
    private var menu: StatusMenu?
    private var background: Background!

    init(settings: Settings, selfTest: SelfTest?) {
        self.settings = settings
        self.selfTest = selfTest
        supervisor = Supervisor(settings: settings)
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = MainMenu.make(
            name: settings.name,
            closeWindow: #selector(closeWindow),
            toggleFullScreen: #selector(toggleFullScreen)
        )
        window = MainWindow(settings: settings, supervisor: supervisor, fullScreen: selfTest == nil)
        window.onRestart = { [weak self] in self?.supervisor.start() }
        window.onClosed = { NSApp.setActivationPolicy(.accessory) }
        // The self-test keeps its preferences in memory, so it never changes the owner's.
        background = Background(
            settings: settings, supervisor: supervisor, store: selfTest == nil ? .standard() : .inMemory()
        )
        background.openHouse = { [weak self] in self?.openWindow() }
        background.goToBackground = { [weak self] in self?.closeWindow() }
        window.shell = background
        if selfTest == nil {
            menu = StatusMenu(
                name: settings.name, open: #selector(openWindow), widget: #selector(toggleWidget),
                widgetShown: { [weak self] in self?.background.widget.isVisible ?? false },
                listen: #selector(chooseListen(_:)),
                login: #selector(toggleLogin)
            )
        }
        supervisor.onChange = { [weak self] phase in
            self?.window.render(phase)
            self?.background.render(phase)
            self?.menu?.show(phase)
        }
        supervisor.onListen = { [weak self] listen in self?.menu?.show(listen: listen) }
        supervisor.start()
        background.render(supervisor.phase)
        background.start()
        if selfTest != nil || (!launchedHidden && background.opensHouse) { openWindow() }
        selfTest?.run(window: window, background: background, supervisor: supervisor)
    }

    /// At login the app starts hidden: the assistant runs, the window waits to be opened.
    private var launchedHidden: Bool {
        if CommandLine.arguments.contains(LoginItem.loginArgument) { return true }
        guard let event = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return event.eventID == kAEOpenApplication
            && event.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openWindow()
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        background.stop()
        supervisor.shutdown()
        return .terminateNow
    }

    func applicationWillTerminate(_ notification: Notification) {
        guard let selfTest else { return }
        selfTest.cleanUp()
        exit(selfTest.passed ? 0 : 1)
    }

    @objc func openWindow() {
        NSApp.setActivationPolicy(.regular)
        window.show()
        window.render(supervisor.phase)
    }

    /// A listening mode chosen in the menu bar item's menu, through the daemon's settings.
    @objc func chooseListen(_ sender: NSMenuItem) {
        guard let mode = sender.representedObject as? String else { return }
        Task {
            guard let refused = await supervisor.setListen(mode) else { return }
            let alert = NSAlert()
            alert.messageText = "\(settings.name) cannot listen that way now"
            alert.informativeText = refused
            alert.runModal()
        }
    }

    @objc func closeWindow() { window.close() }

    @objc func toggleWidget() { background.setWidgetShown(!background.widget.isVisible) }

    @objc func toggleFullScreen() { window.toggleFullScreen() }

    @objc func toggleLogin() {
        do {
            switch LoginItem.state {
            case .off: try LoginItem.set(true)
            case .enabled: try LoginItem.set(false)
            case .requiresApproval: LoginItem.openSettings()
            }
            if LoginItem.state == .requiresApproval { LoginItem.openSettings() }
        } catch {
            let alert = NSAlert()
            alert.messageText = "Start at login could not be changed"
            alert.informativeText = error.localizedDescription
            alert.runModal()
        }
    }
}
