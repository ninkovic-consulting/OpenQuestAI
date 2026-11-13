// The phone channel as `/api/phone` serves it. Mirrors vision/remote/;
// the daemon is the source of truth. The bot token never comes back.

import type { Presence } from "./types";

export type PhoneConnection = "off" | "no_token" | "connecting" | "online" | "offline" | "refused";
export type TokenVerdict = "accepted" | "refused" | "unreachable" | "none";

export interface PhoneTool {
  id: string;
  title: string;
}

/** When a kind of message goes to the phone: always, only while the owner is away from the Mac, or never. */
export type NotifyChoice = "always" | "away" | "never";

export interface PhoneNotify {
  automations: NotifyChoice;
  warnings: NotifyChoice;
  approvals: NotifyChoice;
  /** What every reported job came to; one handed off from the phone goes there unless never. */
  jobs: NotifyChoice;
  /** `send_to_phone`: what the assistant sends on purpose. */
  assistant: NotifyChoice;
}

export type NotifyKind = keyof PhoneNotify;

export interface PhoneView {
  service: "discord";
  enabled: boolean;
  token: { stored: boolean };
  bot: { name: string | null };
  connection: PhoneConnection;
  /** Why the channel stopped, when it did. */
  detail: string | null;
  paired: { name: string; since: number } | null;
  /** The live one-time code, while there is one. */
  pairing: PairingCode | null;
  notify: PhoneNotify;
  /** Whether the owner is at the Mac now, with the away time. */
  presence: Presence;
  speak_on_mac: boolean;
  voice_replies: boolean;
  /** Every tool behind the gate. */
  tools: PhoneTool[];
  /** The tools that may be approved from the phone. */
  phone_tools: string[];
  /** Tools only ever approved at the Mac. */
  mac_only: string[];
  voice_notes: { models: boolean; decoder: string | null };
}

export interface PairingCode {
  code: string;
  /** Unix seconds. */
  expires_at: number;
}

export interface TokenAnswer {
  stored: boolean;
  verdict: TokenVerdict;
  bot: string | null;
}

export interface VerifyAnswer {
  verdict: TokenVerdict;
  bot: string | null;
}

/** The body of `PATCH /api/phone`: any part of it. */
export interface PhonePatch {
  enabled?: boolean;
  speak_on_mac?: boolean;
  voice_replies?: boolean;
  notify?: Partial<PhoneNotify>;
  phone_tools?: string[];
  /** Seconds without keyboard, mouse or voice at the Mac that count as away. */
  away_after_s?: number;
}
