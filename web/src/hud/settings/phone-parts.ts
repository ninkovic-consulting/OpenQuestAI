// The Phone group's words and choices, kept free of the DOM so they can be tested.

import type { PairingCode, PhoneView, TokenVerdict } from "../../net/phone-types";
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
