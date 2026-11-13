// Mock mode's phone channel: checked the way the daemon checks it. A code
// that is shown pairs by itself a few seconds later, as if the owner sent it.
// It also keeps the owner's presence, which mock mode's away scene changes.

import { DEFAULT_TIERS } from "./mock-settings-data";
import type { PhoneApi } from "./phone-api";
import { NOTIFY_KINDS } from "./phone-guards";
import type { NotifyChoice, PairingCode, PhonePatch, PhoneView, TokenAnswer, VerifyAnswer } from "./phone-types";
import { ok, refused, type Result } from "./settings-api";
import type { Presence } from "./types";

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{20,}$/;
const CODE_TTL_S = 600;
const MAC_ONLY = ["shell"];
const BOT = "Vision Bot";
const CHOICES: readonly NotifyChoice[] = ["always", "away", "never"];
const MIN_AWAY_S = 60;
const MAX_AWAY_S = 7200;

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const now = (): number => Date.now() / 1000;
const title = (id: string): string => {
  const t = id.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

function fresh(): PhoneView {
  const tools = Object.keys(DEFAULT_TIERS).map((id) => ({ id, title: title(id) }));
  return {
    service: "discord",
    enabled: true,
    token: { stored: false },
    bot: { name: null },
    connection: "no_token",
    detail: null,
    paired: null,
    pairing: null,
    notify: { automations: "always", warnings: "always", approvals: "always", jobs: "always", assistant: "always" },
    presence: { away: false, known: true, reason: null, since: now(), away_after_s: 300 },
    speak_on_mac: false,
    voice_replies: false,
    tools,
    phone_tools: tools.map((t) => t.id).filter((id) => !MAC_ONLY.includes(id)),
    mac_only: [...MAC_ONLY],
    voice_notes: { models: true, decoder: "afconvert" },
  };
}

export class MockPhone implements PhoneApi {
  private state = fresh();

  /** `pairAfterMs` plays the owner sending the code; 0 never does. */
  constructor(private readonly pairAfterMs = 6000) {}

  view(): Promise<Result<PhoneView>> {
    const code = this.state.pairing;
    if (code && code.expires_at <= now()) this.state.pairing = null;
    return Promise.resolve(ok(structuredClone(this.state)));
  }

  update(patch: PhonePatch): Promise<Result<PhoneView>> {
    const s = this.state;
    if (patch.phone_tools) {
      const never = patch.phone_tools.find((t) => MAC_ONLY.includes(t));
      if (never) return no(`${never} is only ever approved at the Mac.`);
      const strange = patch.phone_tools.find((t) => !s.tools.some((x) => x.id === t));
      if (strange) return no(`There is no tool called '${strange}'.`);
      s.phone_tools = s.tools.map((t) => t.id).filter((id) => patch.phone_tools?.includes(id));
    }
    if (patch.notify) {
      const strange = Object.entries(patch.notify).find(([k, v]) => !NOTIFY_KINDS.includes(k as never) || !CHOICES.includes(v));
      if (strange) return no(`Send ${strange[0]} as one of ${CHOICES.join(", ")}.`);
      s.notify = { ...s.notify, ...patch.notify };
    }
    if (patch.away_after_s !== undefined) {
      const t = patch.away_after_s;
      if (!Number.isFinite(t) || t < MIN_AWAY_S || t > MAX_AWAY_S) return no(`The away time is a number of seconds from ${MIN_AWAY_S} to ${MAX_AWAY_S}.`);
      s.presence = { ...s.presence, away_after_s: t };
    }
    if (patch.speak_on_mac !== undefined) s.speak_on_mac = patch.speak_on_mac;
    if (patch.voice_replies !== undefined) s.voice_replies = patch.voice_replies;
    if (patch.enabled !== undefined) {
      s.enabled = patch.enabled;
      s.connection = !s.enabled ? "off" : s.token.stored ? "online" : "no_token";
    }
    return this.view();
  }

  storeToken(token: string): Promise<Result<TokenAnswer>> {
    if (!TOKEN_SHAPE.test(token.trim()))
      return no("That does not look like a Discord bot token. Copy it again from the Developer Portal: your application, Bot, Reset Token.");
    const s = this.state;
    s.token = { stored: true };
    s.bot = { name: BOT };
    s.connection = s.enabled ? "online" : "off";
    return wait(600).then(() => ok({ stored: true, verdict: "accepted", bot: BOT }));
  }

  verifyToken(): Promise<Result<VerifyAnswer>> {
    const stored = this.state.token.stored;
    return wait(400).then(() => ok({ verdict: stored ? "accepted" : "none", bot: stored ? BOT : null }));
  }

  newCode(): Promise<Result<PairingCode>> {
    if (this.state.paired) return no("The phone is already paired. Unpair it first to pair another.");
    const code = { code: String(Math.floor(100_000 + Math.random() * 900_000)), expires_at: now() + CODE_TTL_S };
    this.state.pairing = code;
    if (this.pairAfterMs > 0) {
      setTimeout(() => {
        if (this.state.pairing?.code !== code.code || !this.state.token.stored) return;
        this.state.pairing = null;
        this.state.paired = { name: "Owner", since: now() };
      }, this.pairAfterMs);
    }
    return Promise.resolve(ok({ ...code }));
  }

  unpair(): Promise<Result<PhoneView>> {
    this.state.paired = null;
    this.state.pairing = null;
    return this.view();
  }

  /** The owner as mock mode has them now. */
  presence(): Presence {
    return { ...this.state.presence };
  }

  /** The owner locks the Mac, or comes back to it; answers the `presence` event's data. */
  setAway(away: boolean): Presence {
    this.state.presence = { ...this.state.presence, away, reason: away ? "locked" : null, since: now() };
    return this.presence();
  }

  /** Start over: unpaired, defaults; the token goes only when asked. */
  reset(removeToken: boolean): void {
    const token = this.state.token.stored && !removeToken;
    const away = this.state.presence.away;
    this.state = fresh();
    this.state.presence = { ...this.state.presence, away, reason: away ? "locked" : null };
    if (token) {
      this.state.token = { stored: true };
      this.state.bot = { name: BOT };
      this.state.connection = "online";
    }
  }
}

const no = <T>(message: string): Promise<Result<T>> => Promise.resolve(refused(message));
