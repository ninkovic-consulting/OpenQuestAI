import Foundation

/// The daemon as this app's child: `<project>/.venv/bin/python -m vision run`.
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
            throw ShellError("No Python at \(settings.python.path). Run `uv sync --all-extras` in \(settings.project.path).")
        }
        try fm.createDirectory(at: settings.log.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !fm.fileExists(atPath: settings.log.path) {
            fm.createFile(atPath: settings.log.path, contents: nil)
        }
        let log = try FileHandle(forWritingTo: settings.log)
        log.seekToEndOfFile()

        var arguments = ["-m", "vision", "run", "--port", String(settings.port)]
        if settings.fakeBrain { arguments.append("--fake-brain") }
        var environment = ProcessInfo.processInfo.environment
        environment["VISION_HOME"] = settings.home.path
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")

        process.executableURL = settings.python
        process.arguments = arguments
        process.currentDirectoryURL = settings.project
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
