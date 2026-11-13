// Which key does what, as a pure decision so it can be tested without a page.
//
// In the message field: Enter sends, Shift+Enter is a new line, Up in an
// empty field recalls the last message, Escape interrupts a speaking
// assistant or else leaves the field; everything else types.
// Elsewhere: another input, a form or a dialog keeps its keys. Escape
// interrupts or steps back. While nothing is open over the scene, `/`
// focuses the field, Space is push to talk when the field is empty (and
// types a space when it holds a draft), and any printable key goes into the
// field.

/** What has focus when the key is pressed. */
export type Focus = "field" | "editable" | "other";

export interface KeyPress {
  key: string;
  code: string;
  shift: boolean;
  ctrl: boolean;
  meta: boolean;
  alt: boolean;
  /** An input method is composing; its keys are not ours. */
  composing: boolean;
}

/**
 * Open over the scene and keeping the keyboard: Settings, the Jobs panel (and
 * its form), the first-start wizard, the build form. While one is open the
 * message field takes no keys typed elsewhere.
 */
export const OVERLAYS = ".settings:not([hidden]), .jobs:not([hidden]), .wizard-backdrop:not([hidden]), .build-form.is-open";

export interface KeyContext {
  focus: Focus;
  /** Settings, the Jobs panel, the wizard or the build form is open over the scene (see OVERLAYS). */
  overlay: boolean;
  fieldEmpty: boolean;
  speaking: boolean;
}

export type KeyAction =
  | { kind: "none" }
  | { kind: "send" }
  | { kind: "recall" }
  | { kind: "interrupt" }
  | { kind: "blur" }
  | { kind: "step-back" }
  | { kind: "focus" }
  | { kind: "type"; text: string }
  | { kind: "talk" };

const NONE: KeyAction = { kind: "none" };

/** One printable character with no shortcut modifier (Option still types on a Mac). */
export function printable(k: KeyPress): boolean {
  return !k.ctrl && !k.meta && [...k.key].length === 1;
}

function inField(k: KeyPress, c: KeyContext): KeyAction {
  if (k.composing) return NONE;
  if (k.key === "Escape") return c.speaking ? { kind: "interrupt" } : { kind: "blur" };
  const plain = !k.shift && !k.ctrl && !k.meta && !k.alt;
  if (k.key === "Enter" && plain) return { kind: "send" };
  if (k.key === "ArrowUp" && plain && c.fieldEmpty) return { kind: "recall" };
  return NONE;
}

export function routeKey(k: KeyPress, c: KeyContext): KeyAction {
  if (c.focus === "field") return inField(k, c);
  if (c.focus === "editable" || k.composing) return NONE;
  if (k.key === "Escape") return c.speaking ? { kind: "interrupt" } : { kind: "step-back" };
  if (c.overlay) return NONE;
  if (k.code === "Space" && !k.ctrl && !k.meta) return c.fieldEmpty ? { kind: "talk" } : { kind: "type", text: " " };
  if (k.key === "/" && !k.ctrl && !k.meta && !k.alt) return { kind: "focus" };
  if (printable(k)) return { kind: "type", text: k.key };
  return NONE;
}
