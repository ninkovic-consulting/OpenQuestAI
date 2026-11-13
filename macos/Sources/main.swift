import AppKit

// <app>                          open the house, starting the daemon if needed
// <app> --login                  the same, hidden (used by the login fallback)
// <app> --login-item on|off|status
// <app> --self-test <result.json>

let arguments = CommandLine.arguments

if let index = arguments.firstIndex(of: "--login-item") {
    let verb = index + 1 < arguments.count ? arguments[index + 1] : ""
    exit(MainActor.assumeIsolated { LoginItem.command(verb) })
}

MainActor.assumeIsolated {
    var settings = Settings.fromBundle()
    var selfTest: SelfTest?
    if let index = arguments.firstIndex(of: SelfTest.flag) {
        guard index + 1 < arguments.count else {
            FileHandle.standardError.write(Data("usage: --self-test <result.json>\n".utf8))
            exit(2)
        }
        do {
            let test = try SelfTest(resultFile: URL(fileURLWithPath: arguments[index + 1]))
            settings = settings.forSelfTest(home: test.home, port: SelfTest.freePort())
            selfTest = test
        } catch {
            FileHandle.standardError.write(Data("self-test: \(error)\n".utf8))
            exit(1)
        }
    }
    let app = NSApplication.shared
    let delegate = AppDelegate(settings: settings, selfTest: selfTest)
    app.delegate = delegate
    // In the menu bar only until the house opens (`AppDelegate.openWindow`).
    app.setActivationPolicy(.accessory)
    withExtendedLifetime(delegate) { app.run() }
}
