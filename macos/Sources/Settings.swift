import Foundation

/// Where the daemon lives, written into Info.plist by `vision app build`.
struct Settings: Sendable {
    let name: String
    let project: URL
    let home: URL
    let port: Int
    /// The scripted brain, for the self-test only.
    let fakeBrain: Bool

    var python: URL { project.appendingPathComponent(".venv/bin/python") }
    var token: URL { home.appendingPathComponent("token") }
    var log: URL { home.appendingPathComponent("logs/app-daemon.log") }
    var origin: String { "http://127.0.0.1:\(port)" }
    var page: URL { URL(string: origin + "/")! }

    static func fromBundle() -> Settings {
        let info = Bundle.main.infoDictionary ?? [:]
        func path(_ key: String) -> URL {
            let raw = info[key] as? String ?? ""
            return URL(fileURLWithPath: (raw as NSString).expandingTildeInPath)
        }
        return Settings(
            name: info["CFBundleDisplayName"] as? String ?? "Vision",
            project: path("VisionProjectPath"),
            home: path("VisionHome"),
            port: info["VisionPort"] as? Int ?? 7341,
            fakeBrain: false
        )
    }

    /// The same app pointed at a throwaway home and port, with the fake brain.
    func forSelfTest(home: URL, port: Int) -> Settings {
        Settings(name: name, project: project, home: home, port: port, fakeBrain: true)
    }
}
