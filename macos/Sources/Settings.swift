import Foundation

/// Where the daemon lives, written into Info.plist by `vision app build`.
///
/// A thin app runs `<project>/.venv/bin/python`. A standalone app runs the
/// Python inside its own `Contents/Resources` and finds the house and the
/// window there too (`VISION_RESOURCES`).
struct Settings: Sendable {
    let name: String
    let python: URL
    let workingDirectory: URL
    /// The bundle's Resources folder in a standalone app; nil in a thin one.
    let resources: URL?
    let home: URL
    let port: Int
    /// The scripted brain, for the self-test only.
    let fakeBrain: Bool

    var token: URL { home.appendingPathComponent("token") }
    var log: URL { home.appendingPathComponent("logs/app-daemon.log") }
    var origin: String { "http://127.0.0.1:\(port)" }
    var page: URL { URL(string: origin + "/")! }

    /// What to do when the Python is missing.
    var missingPython: String {
        resources == nil
            ? "No Python at \(python.path). Run `uv sync --all-extras` in \(workingDirectory.path)."
            : "No Python at \(python.path). This copy of the app is incomplete; copy it again."
    }

    static func fromBundle() -> Settings {
        let info = Bundle.main.infoDictionary ?? [:]
        func path(_ key: String) -> URL {
            let raw = info[key] as? String ?? ""
            return URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
        }
        let home = path("VisionHome")
        let name = info["CFBundleDisplayName"] as? String ?? "Vision"
        let port = info["VisionPort"] as? Int ?? 7341
        if info["VisionStandalone"] as? Bool == true, let resources = Bundle.main.resourceURL {
            return Settings(
                name: name,
                python: resources.appendingPathComponent("python/bin/python3.12"),
                workingDirectory: home,
                resources: resources,
                home: home, port: port, fakeBrain: false
            )
        }
        let project = path("VisionProjectPath")
        return Settings(
            name: name,
            python: project.appendingPathComponent(".venv/bin/python"),
            workingDirectory: project,
            resources: nil,
            home: home, port: port, fakeBrain: false
        )
    }

    /// The same app pointed at a throwaway home and port, with the fake brain.
    func forSelfTest(home: URL, port: Int) -> Settings {
        Settings(
            name: name, python: python,
            workingDirectory: resources == nil ? workingDirectory : home,
            resources: resources, home: home, port: port, fakeBrain: true
        )
    }
}
