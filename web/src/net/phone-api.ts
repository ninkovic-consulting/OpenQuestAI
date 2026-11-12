// What the Phone group asks of the daemon, and the HTTP client for it.
// Mock mode (mock-phone.ts) implements the same interface. The bot token
// travels once, in a POST body, and never comes back.

import type { Api } from "./api";
import { asPairingCode, asPhoneView, asTokenAnswer, asVerifyAnswer } from "./phone-guards";
import type { PairingCode, PhonePatch, PhoneView, TokenAnswer, VerifyAnswer } from "./phone-types";
import { ok, refused, type Result } from "./settings-api";

export interface PhoneApi {
  view(): Promise<Result<PhoneView>>;
  update(patch: PhonePatch): Promise<Result<PhoneView>>;
  /** Checks the token with Discord, then stores it in the Keychain. */
  storeToken(token: string): Promise<Result<TokenAnswer>>;
  verifyToken(): Promise<Result<VerifyAnswer>>;
  /** A new one-time code; refused while paired. */
  newCode(): Promise<Result<PairingCode>>;
  unpair(): Promise<Result<PhoneView>>;
}

const SHAPE = "The answer was not in the expected shape.";

export class HttpPhone implements PhoneApi {
  constructor(private readonly api: Api) {}

  private async ask<T>(method: string, path: string, narrow: (v: unknown) => T | null, body?: unknown): Promise<Result<T>> {
    const answer = await this.api.call(method, path, body);
    if (!answer.ok) return answer;
    const value = narrow(answer.value);
    return value === null ? refused(SHAPE) : ok(value);
  }

  view = () => this.ask("GET", "/api/phone", asPhoneView);
  update = (patch: PhonePatch) => this.ask("PATCH", "/api/phone", asPhoneView, patch);
  storeToken = (token: string) => this.ask("POST", "/api/phone/token", asTokenAnswer, { token });
  verifyToken = () => this.ask("POST", "/api/phone/token/verify", asVerifyAnswer);
  newCode = () => this.ask("POST", "/api/phone/pairing", asPairingCode);
  unpair = () => this.ask("DELETE", "/api/phone/pairing", asPhoneView);
}
