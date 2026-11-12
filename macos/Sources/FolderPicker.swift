import AppKit

/// A native open panel for one folder, as a sheet on the app's window, so it
/// shows over the borderless full-screen window too.
@MainActor
enum FolderPicker {
    static func choose(in window: NSWindow) async -> String? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = true
        panel.directoryURL = FileManager.default.homeDirectoryForCurrentUser
        panel.prompt = "Choose"
        panel.message = "Choose the project folder for this room."
        let response = await panel.beginSheetModal(for: window)
        return response == .OK ? panel.url?.path : nil
    }
}
