import Foundation

/// The daemon as this app's child: `<python> -m vision run`, with the project's
/// `.venv` Python in a thin app and the bundled one in a standalone app.
///
/// Because the app starts it, macOS treats the app as the responsible process,
/// so the microphone and folder prompts name the app.
@MainActor
final class DaemonProcess {
    private let process = Process()
    private var stopping = false

    var isRunning: Bool { process.isRunning }

    /// Starts the daemon; `onExit` gets the exit status unless `stop()` caused it.
    init(settings: Settings, onExit: @escaping @MainActor (Int32) -> Void) throws {
        let fm = FileManager.default
        guard fm.isExecutableFile(atPath: settings.python.path) else {
            throw ShellError(settings.missingPython)
        }
        try fm.createDirectory(
            at: settings.home, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]
        )
        try fm.createDirectory(at: settings.log.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !fm.fileExists(atPath: settings.log.path) {
            fm.createFile(atPath: settings.log.path, contents: nil)
        }
        let log = try FileHandle(forWritingTo: settings.log)
        log.seekToEndOfFile()

        var arguments = ["-m", "vision", "run", "--port", String(settings.port)]
        if settings.fakeBrain { arguments.append("--fake-brain") }
        var environment = ProcessInfo.processInfo.environment
        if settings.fakeBrain {
            // The self-test runs on a scratch home: it must not read the owner's keys from the
            // Keychain, or the bot token there would connect the owner's real bot for the test.
            environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
        }
        // Nothing from the launching shell may point Python somewhere else.
        for name in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "VISION_ENV_FILE", "VISION_RESOURCES"] {
            environment.removeValue(forKey: name)
        }
        if let resources = settings.resources {
            environment["VISION_RESOURCES"] = resources.path
            // The bundle is signed and may be read-only: never write bytecode into it.
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
        }
        environment["VISION_HOME"] = settings.home.path
        // The daemon names the app, not a Python path, when it asks for the microphone permission.
        environment["VISION_APP"] = Bundle.main.object(forInfoDictionaryKey: "CFBundleName") as? String ?? "Vision"
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")

        process.executableURL = settings.python
        process.arguments = arguments
        process.currentDirectoryURL = settings.workingDirectory
        process.environment = environment
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = log
        process.standardError = log
        process.terminationHandler = { [weak self] child in
            let status = child.terminationStatus
            Task { @MainActor in
                guard let self, !self.stopping else { return }
                onExit(status)
            }
        }
        try process.run()
    }

    /// SIGTERM, then SIGKILL if it is still running after `grace` seconds.
    ///
    /// Blocks: it runs while the app quits, when queued main-actor work may never run.
    func stop(grace: TimeInterval = 5) {
        stopping = true
        guard process.isRunning else { return }
        process.terminate()
        let deadline = Date().addingTimeInterval(grace)
        while process.isRunning, Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
    }
}

struct ShellError: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}
