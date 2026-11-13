import AppKit

/// The menu bar icon: a monochrome armchair, drawn as a template image so macOS
/// tints it for a light or a dark menu bar. While a microphone stream is open a
/// small dot sits at its top right, cut clear of the chair so it reads apart.
enum ArmchairIcon {
    static func make(mic: Bool) -> NSImage {
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
            if mic {
                // A ring of clear space, then the dot.
                NSGraphicsContext.current?.compositingOperation = .clear
                NSBezierPath(ovalIn: NSRect(x: 11, y: 11, width: 7, height: 7)).fill()
                NSGraphicsContext.current?.compositingOperation = .sourceOver
                NSBezierPath(ovalIn: NSRect(x: 12.5, y: 12.5, width: 4.5, height: 4.5)).fill()
            }
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = mic ? "Armchair, microphone open" : "Armchair"
        return image
    }
}
