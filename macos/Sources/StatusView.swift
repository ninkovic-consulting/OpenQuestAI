import AppKit

/// The plain view shown while the daemon starts, or after it stops, in the project's colours.
@MainActor
final class StatusView: NSView {
    static let ground = NSColor(srgbRed: 0x1C / 255, green: 0x0E / 255, blue: 0x0B / 255, alpha: 1)
    static let text = NSColor(srgbRed: 0xED / 255, green: 0xE4 / 255, blue: 0xD0 / 255, alpha: 1)
    static let accent = NSColor(srgbRed: 0xE2 / 255, green: 0xA6 / 255, blue: 0x2B / 255, alpha: 1)

    private let message = NSTextField(wrappingLabelWithString: "")
    private let button: NSButton

    init(name: String, onRestart: @escaping () -> Void) {
        button = ActionButton(title: "Restart \(name)", action: onRestart)
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = Self.ground.cgColor

        let title = NSTextField(labelWithString: name)
        title.font = Self.serif(size: 34)
        title.textColor = Self.text

        let rule = NSView()
        rule.wantsLayer = true
        rule.layer?.backgroundColor = Self.accent.cgColor
        rule.widthAnchor.constraint(equalToConstant: 48).isActive = true
        rule.heightAnchor.constraint(equalToConstant: 2).isActive = true

        message.font = .systemFont(ofSize: 15)
        message.textColor = Self.text.withAlphaComponent(0.75)
        message.alignment = .center
        message.preferredMaxLayoutWidth = 460

        button.bezelColor = Self.accent
        button.contentTintColor = Self.ground
        button.controlSize = .large

        let stack = NSStackView(views: [title, rule, message, button])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualToConstant: 480),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("not used") }

    func show(_ text: String, canRestart: Bool) {
        message.stringValue = text
        button.isHidden = !canRestart
    }

    private static func serif(size: CGFloat) -> NSFont {
        let base = NSFont.systemFont(ofSize: size, weight: .regular)
        guard let descriptor = base.fontDescriptor.withDesign(.serif) else { return base }
        return NSFont(descriptor: descriptor, size: size) ?? base
    }
}

/// An NSButton that runs a closure.
@MainActor
final class ActionButton: NSButton {
    private let run: () -> Void

    init(title: String, action: @escaping () -> Void) {
        run = action
        super.init(frame: .zero)
        self.title = title
        bezelStyle = .push
        target = self
        self.action = #selector(fire)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("not used") }

    @objc private func fire() { run() }
}
