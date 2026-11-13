import AppKit

/// The strip at the top of a screen that a camera notch hides, as the page needs it.
///
/// `NSScreen.safeAreaInsets` gives it per screen (macOS 12 and later): zero on
/// a display without a notch. The house window draws into that strip only in
/// full screen, where it covers the whole screen; windowed, the title bar and
/// the menu bar already keep it clear, so the page is told zero. The page
/// keeps its text and controls below the inset (`--safe-top`), and the scene
/// still draws behind it.
@MainActor
enum SafeArea {
    /// Points the page should leave clear at its top in `window`.
    static func top(of window: NSWindow) -> CGFloat {
        guard let screen = window.screen, window.frame == screen.frame else { return 0 }
        return screen.safeAreaInsets.top
    }

    /// Sets `--safe-top` on the page's document.
    static func script(_ top: CGFloat) -> String {
        "document.documentElement.style.setProperty('--safe-top', '\(Int(top.rounded()))px')"
    }
}
