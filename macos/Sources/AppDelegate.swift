import AppKit

/// Owns the daemon, the window and the menu bar item.
///
/// Closing the window leaves the app and the assistant running. Quit stops the
/// daemon only if this app started it.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let settings: Settings
    private let selfTest: SelfTest?
    private let supervisor: Supervisor
    private var window: MainWindow!
    private var menu: StatusMenu?

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
        if selfTest == nil {
            menu = StatusMenu(name: settings.name, open: #selector(openWindow), login: #selector(toggleLogin))
        }
        supervisor.onChange = { [weak self] phase in
            self?.window.render(phase)
            self?.menu?.show(phase)
        }
        supervisor.start()
        if !launchedHidden { openWindow() }
        selfTest?.run(window: window, supervisor: supervisor)
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
        supervisor.shutdown()
        return .terminateNow
    }

    func applicationWillTerminate(_ notification: Notification) {
        guard let selfTest else { return }
        selfTest.cleanUp()
        exit(selfTest.passed ? 0 : 1)
    }

    @objc func openWindow() {
        window.show()
        window.render(supervisor.phase)
    }

    @objc func closeWindow() { window.close() }

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
