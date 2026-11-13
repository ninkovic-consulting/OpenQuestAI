import Foundation

/// How the assistant listens, as `listen` in `/api/state` says: the mode
/// (`hold`, `wake`, `always`), whether a microphone stream is open, and
/// whether voice runs at all.
struct Listen: Equatable, Sendable {
    static let modes = ["hold", "wake", "always"]

    let mode: String
    let micOpen: Bool
    let voice: Bool

    init(mode: String, micOpen: Bool, voice: Bool) {
        self.mode = mode
        self.micOpen = micOpen
        self.voice = voice
    }

    /// From the JSON object; nil when it is not one (an older daemon).
    init?(_ raw: Any?) {
        guard let d = raw as? [String: Any], let mode = d["mode"] as? String, Self.modes.contains(mode),
              let mic = d["mic"] as? String, let voice = d["voice"] as? Bool
        else { return nil }
        self.init(mode: mode, micOpen: voice && mic != "closed", voice: voice)
    }

    /// The menu's words for a mode.
    static func title(_ mode: String) -> String {
        switch mode {
        case "hold": return "Hold to talk"
        case "wake": return "Listen for its name"
        default: return "Listen always"
        }
    }
}
