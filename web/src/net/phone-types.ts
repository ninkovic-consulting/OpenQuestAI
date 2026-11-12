// The phone channel as `/api/phone` serves it. Mirrors vision/remote/;
// the daemon is the source of truth. The bot token never comes back.

export type PhoneConnection = "off" | "no_token" | "connecting" | "online" | "offline" | "refused";
export type TokenVerdict = "accepted" | "refused" | "unreachable" | "none";

export interface PhoneTool {
  id: string;
  title: string;
}

export interface PhoneNotify {
  automations: boolean;
  warnings: boolean;
  approvals: boolean;
}

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
}
