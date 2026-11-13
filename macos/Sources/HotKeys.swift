import Carbon.HIToolbox
import Foundation

/// The two global shortcuts: summon the widget, and push to talk while held.
///
/// They are Carbon hot keys (`RegisterEventHotKey`), which reach the app from
/// any other app without the Accessibility permission that an event monitor or
/// an event tap would need. Each is registered exclusively, so one another app
/// holds is refused and the reason shown in Settings. Combinations macOS keeps
/// for itself (System Settings, Keyboard, Keyboard Shortcuts) are found with
/// `CopySymbolicHotKeys` and reported, because the system takes them first.
@MainActor
final class HotKeys {
    enum Role: UInt32, CaseIterable, Sendable {
        case summon = 1
        case talk = 2

        var key: String { self == .summon ? "summon" : "talk" }
    }

    struct Status: Equatable, Sendable {
        var shortcut: String
        var registered: Bool
        /// Why it does not work, or may not, in the owner's words; nil when it is fine or off.
        var problem: String?
    }

    /// "VisN": tells this app's hot keys apart in the handler.
    nonisolated static let signature: OSType = 0x5669_734E

    var onPress: (Role) -> Void = { _ in }
    var onRelease: (Role) -> Void = { _ in }
    private var refs: [Role: EventHotKeyRef] = [:]
    private var handler: EventHandlerRef?
    private(set) var status: [Role: Status] = [:]

    init() {
        var specs = [
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased)),
        ]
        InstallEventHandler(
            GetApplicationEventTarget(), hotKeyHandler, specs.count, &specs,
            Unmanaged.passUnretained(self).toOpaque(), &handler
        )
    }

    /// Registers the two shortcuts afresh; `off` leaves one unregistered.
    func apply(summon: String, talk: String) {
        unregisterAll()
        status[.summon] = register(.summon, summon)
        status[.talk] = summon != Shortcuts.off && summon == talk
            ? Status(shortcut: talk, registered: false, problem: "It is the summon shortcut already; choose another.")
            : register(.talk, talk)
    }

    func unregisterAll() {
        for ref in refs.values { UnregisterEventHotKey(ref) }
        refs.removeAll()
    }

    private func register(_ role: Role, _ id: String) -> Status {
        guard id != Shortcuts.off else { return Status(shortcut: id, registered: false, problem: nil) }
        guard let choice = Shortcuts.choice(id) else {
            return Status(shortcut: id, registered: false, problem: "Unknown shortcut.")
        }
        var ref: EventHotKeyRef?
        let err = RegisterEventHotKey(
            choice.keyCode, choice.modifiers,
            EventHotKeyID(signature: Self.signature, id: role.rawValue),
            GetApplicationEventTarget(), OptionBits(kEventHotKeyExclusive), &ref
        )
        guard err == noErr, let ref else {
            return Status(shortcut: id, registered: false, problem: Self.refusal(err, choice))
        }
        refs[role] = ref
        if Self.systemUses(choice) {
            return Status(
                shortcut: id, registered: true,
                problem: "macOS uses \(choice.label) too, so it may not reach the app. Turn it off in System Settings, Keyboard, Keyboard Shortcuts, or choose another."
            )
        }
        return Status(shortcut: id, registered: true, problem: nil)
    }

    private static func refusal(_ err: OSStatus, _ choice: ShortcutChoice) -> String {
        if err == OSStatus(eventHotKeyExistsErr) {
            return "Another app already uses \(choice.label); choose another."
        }
        let optionOnly = choice.modifiers & ~UInt32(optionKey | shiftKey) == 0
        let hint = optionOnly ? " Recent macOS refuses shortcuts made of Option (and Shift) alone; choose one with Control or Command." : ""
        return "macOS refused \(choice.label) (error \(err)).\(hint)"
    }

    /// True when an enabled system shortcut (Spotlight, input sources, ...) has the same keys.
    static func systemUses(_ choice: ShortcutChoice) -> Bool {
        var unmanaged: Unmanaged<CFArray>?
        guard CopySymbolicHotKeys(&unmanaged) == noErr, let array = unmanaged?.takeRetainedValue() else { return false }
        let relevant = UInt32(cmdKey | optionKey | controlKey | shiftKey)
        for case let entry as [String: Any] in array as NSArray {
            guard entry["kHISymbolicHotKeyEnabled"] as? Bool == true,
                  let code = (entry["kHISymbolicHotKeyCode"] as? NSNumber)?.uint32Value,
                  let mods = (entry["kHISymbolicHotKeyModifiers"] as? NSNumber)?.uint32Value
            else { continue }
            if code == choice.keyCode, mods & relevant == choice.modifiers { return true }
        }
        return false
    }

    fileprivate func fire(_ id: UInt32, pressed: Bool) {
        guard let role = Role(rawValue: id) else { return }
        if pressed { onPress(role) } else { onRelease(role) }
    }
}

/// The Carbon handler: hot keys arrive on the main thread through the application's event target.
private func hotKeyHandler(
    _ next: EventHandlerCallRef?, _ event: EventRef?, _ userData: UnsafeMutableRawPointer?
) -> OSStatus {
    guard let event, let userData else { return OSStatus(eventNotHandledErr) }
    var id = EventHotKeyID()
    let err = GetEventParameter(
        event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
        nil, MemoryLayout<EventHotKeyID>.size, nil, &id
    )
    guard err == noErr, id.signature == HotKeys.signature else { return OSStatus(eventNotHandledErr) }
    let pressed = GetEventKind(event) == UInt32(kEventHotKeyPressed)
    let hotKeys = Unmanaged<HotKeys>.fromOpaque(userData).takeUnretainedValue()
    let hotKeyId = id.id
    MainActor.assumeIsolated { hotKeys.fire(hotKeyId, pressed: pressed) }
    return noErr
}
