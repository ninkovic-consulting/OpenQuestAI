// The Phone group's words and choices, kept free of the DOM so they can be tested.

import type { NotifyChoice, NotifyKind, PairingCode, PhoneView, TokenVerdict } from "../../net/phone-types";
import type { Presence } from "../../net/types";
import type { Tone } from "./fields";

export interface Line {
  tone: Tone;
  text: string;
}

export function connectionLine(v: PhoneView): Line {
  const bot = v.bot.name ? ` as ${v.bot.name}` : "";
  switch (v.connection) {
    case "off":
      return { tone: "idle", text: "Off. Nothing is sent to or read from Discord." };
    case "no_token":
      return { tone: "idle", text: "Not set up: store the bot token below." };
    case "connecting":
      return { tone: "warn", text: `Connecting to Discord${bot}…` };
    case "online":
      return { tone: "ok", text: `Connected to Discord${bot}.` };
    case "offline":
      return { tone: "warn", text: `Reconnecting to Discord${bot}; it keeps trying by itself.` };
    case "refused":
      return { tone: "bad", text: v.detail ?? "Discord refused the bot. Store a new token below." };
  }
}

export function pairedLine(v: PhoneView, when: (seconds: number) => string): Line {
  if (v.paired) return { tone: "ok", text: `Paired with ${v.paired.name} since ${when(v.paired.since)}. Only they are answered.` };
  return { tone: "idle", text: "Not paired. Until it is, the bot answers nobody." };
}

/** "Send it within 9 minutes", counting down; null once the code has expired. */
export function codeLine(code: PairingCode, now: number): string | null {
  const left = Math.floor(code.expires_at - now);
  if (left <= 0) return null;
  const minutes = Math.ceil(left / 60);
  const span = left < 60 ? `${left} ${left === 1 ? "second" : "seconds"}` : `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  return `Send this code to the bot in a direct message on Discord within ${span}. It works once.`;
}

/** The code as people read it: two groups of three. */
export function spacedCode(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}

export function verdictLine(verdict: TokenVerdict, bot: string | null): Line {
  switch (verdict) {
    case "accepted":
      return { tone: "ok", text: bot ? `Discord accepts the token: the bot is ${bot}.` : "Discord accepts the token." };
    case "refused":
      return { tone: "bad", text: "Discord refused the token. Reset it in the Developer Portal and store the new one." };
    case "unreachable":
      return { tone: "warn", text: "Stored, but Discord could not be reached to check it. It connects once Discord answers." };
    case "none":
      return { tone: "idle", text: "No token is stored." };
  }
}

export function voiceNotesLine(v: PhoneView): Line {
  if (!v.voice_notes.models) return { tone: "warn", text: "Voice notes need the speech models: download them in Voice. Text works now." };
  if (!v.voice_notes.decoder) return { tone: "warn", text: "Nothing on this Mac can open voice notes (no soundfile with Opus, afconvert or ffmpeg). Text works." };
  return { tone: "ok", text: `Voice notes are heard on this Mac (decoded with ${v.voice_notes.decoder}, transcribed locally).` };
}

/** The tool list after switching one tool on or off; tools only approved at the Mac never join. */
export function toggledTools(v: PhoneView, id: string): string[] {
  if (v.mac_only.includes(id)) return [...v.phone_tools];
  const on = v.phone_tools.includes(id);
  return v.tools.map((t) => t.id).filter((t) => (t === id ? !on : v.phone_tools.includes(t)));
}

/** Each kind of message the phone may get, in the order the group shows them, with a word on when. */
export const NOTIFY_ROWS: readonly { kind: NotifyKind; label: string; note: string }[] = [
  { kind: "automations", label: "Automation results", note: "What an automation did, each time it runs." },
  { kind: "warnings", label: "Warnings and errors", note: "Not notes about the phone channel itself; those stay here." },
  { kind: "approvals", label: "Requests that need your yes", note: "With Yes and Not now for the tools listed below." },
  { kind: "jobs", label: "Results of jobs", note: "Every job a resident finishes, wherever you handed it off. One handed off from the phone reports there unless this is never." },
  { kind: "assistant", label: "Messages from the assistant", note: "When it messages your phone on purpose, for example when you ask it to or an automation says to ping you." },
];

export const CHOICE_SEGMENTS: readonly { value: NotifyChoice; label: string }[] = [
  { value: "always", label: "Always" },
  { value: "away", label: "When away" },
  { value: "never", label: "Never" },
];

/** What the group says after a choice is saved. */
export function choiceSaid(label: string, choice: NotifyChoice): string {
  if (choice === "always") return `${label}: always sent to the phone.`;
  if (choice === "away") return `${label}: sent to the phone only while you are away from the Mac.`;
  return `${label}: never sent to the phone.`;
}

/** Whether the owner is at the Mac now, as the daemon reads it. */
export function presenceLine(p: Presence, when: (seconds: number) => string): Line {
  if (!p.known) return { tone: "warn", text: "This Mac does not say whether you are using it, so you count as here: only what is set to always is sent." };
  if (!p.away) return { tone: "ok", text: "You are at the Mac. Anything set to when away waits until you leave." };
  const why = p.reason === "locked" ? "the screen is locked" : p.reason === "asleep" ? "the display is asleep" : `no keyboard, mouse or voice for ${awayWords(p.away_after_s)}`;
  return { tone: "idle", text: `You are away (${why}) since ${when(p.since)}. Anything set to when away goes to the phone.` };
}

/** "5 minutes", "1 hour 30 minutes", "90 seconds". */
export function awayWords(seconds: number): string {
  if (seconds % 60 !== 0) return `${seconds} seconds`;
  const minutes = seconds / 60;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const m = rest === 0 ? "" : `${rest} ${rest === 1 ? "minute" : "minutes"}`;
  if (hours === 0) return m;
  return `${hours} ${hours === 1 ? "hour" : "hours"}${m ? ` ${m}` : ""}`;
}

/** The away time as typed, in minutes: a whole number from 1 to 120, or the reason it is not one. */
export function parseAwayMinutes(text: string): number | string {
  const n = Number(text.trim());
  if (!text.trim() || !Number.isInteger(n) || n < 1 || n > 120) return "Type a whole number of minutes from 1 to 120.";
  return n * 60;
}
