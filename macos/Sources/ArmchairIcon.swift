import AppKit

/// The menu bar icon: a monochrome armchair, drawn as a template image so macOS tints it.
enum ArmchairIcon {
    static func make() -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
            NSColor.black.setFill()
            // Back, with rounded shoulders.
            NSBezierPath(roundedRect: NSRect(x: 4.5, y: 7, width: 9, height: 9), xRadius: 2.5, yRadius: 2.5).fill()
            // Arms, standing a little proud of the back.
            NSBezierPath(roundedRect: NSRect(x: 1.5, y: 4, width: 3.5, height: 7.5), xRadius: 1.75, yRadius: 1.75).fill()
            NSBezierPath(roundedRect: NSRect(x: 13, y: 4, width: 3.5, height: 7.5), xRadius: 1.75, yRadius: 1.75).fill()
            // Seat cushion between the arms.
            NSBezierPath(roundedRect: NSRect(x: 4, y: 4, width: 10, height: 3.5), xRadius: 1, yRadius: 1).fill()
            // Short legs.
            NSBezierPath(rect: NSRect(x: 2.5, y: 1.5, width: 1.5, height: 3)).fill()
            NSBezierPath(rect: NSRect(x: 14, y: 1.5, width: 1.5, height: 3)).fill()
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Armchair"
        return image
    }
}
