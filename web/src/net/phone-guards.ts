// Narrowing `/api/phone` JSON to its types, or null when the shape is wrong.

import type { NotifyChoice, NotifyKind, PairingCode, PhoneConnection, PhoneView, TokenAnswer, TokenVerdict, VerifyAnswer } from "./phone-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isIn = <T extends string>(values: readonly T[], v: unknown): v is T => typeof v === "string" && (values as readonly string[]).includes(v);
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);

const CONNECTIONS: readonly PhoneConnection[] = ["off", "no_token", "connecting", "online", "offline", "refused"];
const VERDICTS: readonly TokenVerdict[] = ["accepted", "refused", "unreachable", "none"];
const CHOICES: readonly NotifyChoice[] = ["always", "away", "never"];
export const NOTIFY_KINDS: readonly NotifyKind[] = ["automations", "warnings", "approvals", "jobs", "assistant"];
const REASONS: readonly string[] = ["idle", "locked", "asleep"];

function presenceOk(v: unknown): boolean {
  return (
    isObj(v) &&
    isBool(v["away"]) &&
    isBool(v["known"]) &&
    (v["reason"] === null || isIn(REASONS, v["reason"])) &&
    isNum(v["since"]) &&
    isNum(v["away_after_s"])
  );
}

export function asPairingCode(v: unknown): PairingCode | null {
  return isObj(v) && isStr(v["code"]) && isNum(v["expires_at"]) ? (v as unknown as PairingCode) : null;
}

export function asPhoneView(v: unknown): PhoneView | null {
  if (!isObj(v)) return null;
  const token = v["token"];
  const bot = v["bot"];
  const notify = v["notify"];
  const voice = v["voice_notes"];
  const paired = v["paired"];
  const ok =
    v["service"] === "discord" &&
    isBool(v["enabled"]) &&
    isObj(token) &&
    isBool(token["stored"]) &&
    isObj(bot) &&
    (bot["name"] === null || isStr(bot["name"])) &&
    isIn(CONNECTIONS, v["connection"]) &&
    (v["detail"] === null || isStr(v["detail"])) &&
    (paired === null || (isObj(paired) && isStr(paired["name"]) && isNum(paired["since"]))) &&
    (v["pairing"] === null || asPairingCode(v["pairing"]) !== null) &&
    isObj(notify) &&
    NOTIFY_KINDS.every((k) => isIn(CHOICES, notify[k])) &&
    presenceOk(v["presence"]) &&
    isBool(v["speak_on_mac"]) &&
    isBool(v["voice_replies"]) &&
    Array.isArray(v["tools"]) &&
    v["tools"].every((t) => isObj(t) && isStr(t["id"]) && isStr(t["title"])) &&
    strings(v["phone_tools"]) &&
    strings(v["mac_only"]) &&
    isObj(voice) &&
    isBool(voice["models"]) &&
    (voice["decoder"] === null || isStr(voice["decoder"]));
  return ok ? (v as unknown as PhoneView) : null;
}

export function asTokenAnswer(v: unknown): TokenAnswer | null {
  return isObj(v) && isBool(v["stored"]) && isIn(VERDICTS, v["verdict"]) && (v["bot"] === null || isStr(v["bot"])) ? (v as unknown as TokenAnswer) : null;
}

export function asVerifyAnswer(v: unknown): VerifyAnswer | null {
  return isObj(v) && isIn(VERDICTS, v["verdict"]) && (v["bot"] === null || isStr(v["bot"])) ? (v as unknown as VerifyAnswer) : null;
}
