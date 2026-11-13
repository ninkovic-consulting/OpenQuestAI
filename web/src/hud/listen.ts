// When voice listens, in words, as pure functions of the listen view: the
// key hint, the hold-to-talk control, the field's prompt, and the quick
// control in the left panel and the widget that switches between hold to
// talk and listening in one press.

import type { Listening, ListenMode, ListenView } from "../net/types";

/** The sentence the owner confirms before `always` and a free shell are both on. */
export const ROOM_RUNS_COMMANDS =
  "With Always on and shell commands Free, anything said in the room can run commands on this Mac without a card.";

/** What each mode does to the microphone, in one line, for Settings. */
export const MODE_LINES: Record<ListenMode, string> = {
  hold: "The microphone is closed until you hold Space or the talk control, and closes again when you let go.",
  wake: "The microphone stays open; only what starts with the assistant's name is taken, and a short follow-up after each answer.",
  always: "The microphone stays open and everything you say is taken, except the assistant's own voice and short noises.",
};

export const MODE_NAMES: Record<ListenMode, string> = { hold: "Hold to talk", wake: "Wake word", always: "Always" };

/** The key hint for Space, by mode: "Hold Space to talk", "Say Vision, or hold Space", "Listening". */
export function talkHint(mode: ListenMode, name: string): string {
  switch (mode) {
    case "hold":
      return "Hold Space to talk";
    case "wake":
      return `Say ${name || "its name"}, or hold Space`;
    case "always":
      return "Listening";
  }
}

/** The mode the window shows: hold to talk until the daemon says otherwise. */
export const modeOf = (view: ListenView | null): ListenMode => view?.mode ?? "hold";

/**
 * The hold-to-talk control's words. While held: "Opening the microphone"
 * until the stream delivers audio, then "Listening". Otherwise what the mode
 * asks of the owner; `compact` (the widget) leaves the name to the field's prompt.
 */
export function talkLabel(view: ListenView | null, held: boolean, name: string, compact = false): string {
  if (held) return view?.mic === "opening" ? (compact ? "Opening" : "Opening the microphone") : "Listening";
  switch (modeOf(view)) {
    case "hold":
      return "Hold to talk";
    case "wake":
      return compact ? "Hold to talk" : `Say ${name || "its name"} or hold`;
    case "always":
      return "Listening";
  }
}

/** The field's prompt: how else the owner can reach the assistant in this mode; `compact` for the widget. */
export function fieldPrompt(view: ListenView | null, name: string, compact = false): string {
  const to = name ? `Write to ${name}` : "Write a message";
  if (compact) return modeOf(view) === "wake" ? `Write, or say ${name || "its name"}` : to;
  switch (modeOf(view)) {
    case "hold":
      return `${to}, or hold Space to talk`;
    case "wake":
      return `${to}, or say ${name || "its name"}`;
    case "always":
      return `${to}, or just talk`;
  }
}

export interface QuickControl {
  /** Hidden until the daemon says how it listens. */
  shown: boolean;
  /** Voice is off, so there is nothing to switch. */
  disabled: boolean;
  /** The current mode, in words. */
  label: string;
  /** What a press does. */
  title: string;
  /** The mode a press switches to. */
  next: ListenMode;
  /** A microphone stream is open (or opening) now. */
  mic: boolean;
  /** The mode listens (`wake` or `always`). */
  listening: boolean;
}

/** The quick control: shows the mode, and switches between hold to talk and the listening mode last chosen. */
export function quickControl(view: ListenView | null, name: string): QuickControl {
  const mode = modeOf(view);
  const back: Listening = view?.listening ?? "wake";
  const next: ListenMode = mode === "hold" ? back : "hold";
  const voice = view?.voice ?? false;
  const title = !voice
    ? "Voice is off. Turn it on in Settings, Voice."
    : next === "hold"
      ? "Close the microphone: listen only while you hold to talk"
      : next === "wake"
        ? `Keep the microphone open and answer to “${name || "its name"}”`
        : "Keep the microphone open and take everything you say";
  return {
    shown: view !== null,
    disabled: !voice,
    label: voice ? MODE_NAMES[mode] : "Voice off",
    title,
    next,
    mic: voice && view?.mic !== "closed",
    listening: mode !== "hold",
  };
}

/** True when switching to `next` should first ask: `always` with a free shell. */
export function needsConfirm(next: ListenMode, shellFree: boolean): boolean {
  return next === "always" && shellFree;
}

/** Said in Settings, Voice, when one Bluetooth headset is both microphone and speakers in a listening mode. */
export const HEADSET_LINE =
  "These are one Bluetooth headset: while its own microphone is open it plays in its low-quality call mode, so replies sound thin and choppy. Hold to talk, or another microphone, avoids it.";

interface Device {
  name: string;
  default: boolean;
  bluetooth?: boolean;
}

/** The device a choice means: the one named, or the system default for "". */
const chosen = (list: readonly Device[], name: string): Device | undefined => (name === "" ? list.find((d) => d.default) : list.find((d) => d.name === name));

/** True when the chosen microphone and speakers are one Bluetooth headset and the mode keeps the microphone open. */
export function headsetWarning(mode: ListenMode, inputs: readonly Device[], outputs: readonly Device[], input: string, output: string): boolean {
  if (mode === "hold") return false;
  const mic = chosen(inputs, input);
  const speakers = chosen(outputs, output);
  return mic !== undefined && speakers !== undefined && mic.name === speakers.name && mic.bluetooth === true;
}

/** The line beside the mark while a stream is open. */
export function micTitle(view: ListenView | null): string {
  return view?.mic === "opening" ? "Opening the microphone" : "The microphone is open";
}
