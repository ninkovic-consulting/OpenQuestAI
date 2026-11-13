// Narrowing the settings routes' JSON to their types, or null when the shape
// is wrong. Like plan.ts: check what the screen relies on, nothing more.

import type {
  AudioDevice,
  Backup,
  Doctor,
  DoctorCheck,
  Download,
  Downloads,
  FieldError,
  FixAnswer,
  FolderSuggestion,
  KeyAnswer,
  ModelInfo,
  ModelListing,
  PatchAnswer,
  ResetAnswer,
  RestoreAnswer,
  Settings,
  SpeakTest,
  Verdict,
  VoiceDevices,
  VoiceState,
  VoiceTest,
} from "./settings-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const orNull =
  <T>(is: (v: unknown) => v is T) =>
  (v: unknown): v is T | null =>
    v === null || is(v);
const listOf =
  <T>(is: (v: unknown) => v is T) =>
  (v: unknown): v is T[] =>
    Array.isArray(v) && v.every(is);
const oneOf =
  <T extends string>(...values: T[]) =>
  (v: unknown): v is T =>
    typeof v === "string" && (values as string[]).includes(v);

const isStrList = listOf(isStr);
const isVerdict = oneOf<Verdict>("accepted", "refused", "unreachable", "none");
const isKeySource = orNull(oneOf("keychain", "env_file", "environment"));

function isAgent(v: unknown): boolean {
  return isObj(v) && isStr(v["id"]) && isStr(v["name"]) && isStr(v["model"]) && orNull(isStr)(v["heavy_model"]) && isStr(v["effort"]) && isStr(v["heavy_effort"]) && isBool(v["is_host"]);
}

function isVoiceState(v: unknown): v is VoiceState {
  return (
    isObj(v) &&
    isBool(v["installed"]) &&
    isBool(v["enabled"]) &&
    isBool(v["running"]) &&
    oneOf("granted", "denied", "silent", "unknown")(v["mic"]) &&
    orNull(isStr)(v["mic_detail"]) &&
    isStr(v["input_device"]) &&
    isStr(v["output_device"]) &&
    isStr(v["tts_voice"]) &&
    isNum(v["followup_s"]) &&
    oneOf("hold", "wake", "always")(v["listen"]) &&
    oneOf("wake", "always")(v["listening"]) &&
    isBool(v["models_downloaded"]) &&
    orNull(isNum)(v["models_size_bytes"])
  );
}

export function asVoiceState(v: unknown): VoiceState | null {
  return isVoiceState(v) ? v : null;
}

function isGate(v: unknown): boolean {
  if (!isObj(v) || !isStrList(v["never_free"]) || !isStrList(v["free_at_the_mac_only"]) || !isStrList(v["free_for_jobs_from_the_mac"]) || !isObj(v["tiers"])) return false;
  const tools = v["tools"];
  const tiers = Object.values(v["tiers"]);
  return (
    Array.isArray(tools) &&
    tools.every((t) => isObj(t) && isStr(t["id"]) && isStr(t["title"]) && isStr(t["description"])) &&
    tiers.every(oneOf("free", "ask", "never"))
  );
}

export function asSettings(v: unknown): Settings | null {
  if (!isObj(v)) return null;
  const { assistant, owner, models, budget, agents, voice, gate, projects, key, setup } = v;
  const local = isObj(models) ? models["local"] : null;
  const ok =
    isObj(assistant) &&
    isStr(assistant["name"]) &&
    isObj(owner) &&
    isStr(owner["name"]) &&
    isStr(owner["business"]) &&
    isStr(owner["notes"]) &&
    isObj(models) &&
    isStr(models["talk"]) &&
    isStr(models["heavy"]) &&
    isStr(models["talk_effort"]) &&
    isStr(models["heavy_effort"]) &&
    isObj(local) &&
    isStr(local["backend"]) &&
    isStr(local["model"]) &&
    isBool(local["downloaded"]) &&
    orNull(isNum)(local["size_bytes"]) &&
    isStr(local["server"]) &&
    orNull(isBool)(local["tools"]) &&
    isBool(local["offline"]) &&
    (local["keep"] === "idle" || local["keep"] === "always") &&
    isNum(local["idle_s"]) &&
    isObj(budget) &&
    isStr(budget["month"]) &&
    isNum(budget["spent_usd"]) &&
    isNum(budget["cap_usd"]) &&
    isNum(budget["warn_fraction"]) &&
    Array.isArray(agents) &&
    agents.every(isAgent) &&
    isVoiceState(voice) &&
    isGate(gate) &&
    isObj(projects) &&
    isStr(projects["root"]) &&
    isObj(key) &&
    isBool(key["stored"]) &&
    isKeySource(key["source"]) &&
    isObj(setup) &&
    isBool(setup["completed"]) &&
    isBool(setup["first_run"]) &&
    isStrList(v["restart_pending"]);
  return ok ? (v as unknown as Settings) : null;
}

export function asPatchAnswer(v: unknown): PatchAnswer | null {
  if (!isObj(v) || !isStrList(v["changed"]) || !isStrList(v["applied"]) || !isStrList(v["restart"])) return null;
  const settings = asSettings(v["settings"]);
  return settings ? { changed: v["changed"], applied: v["applied"], restart: v["restart"], settings } : null;
}

/** The `detail.errors` of a 400, or null when the refusal is a plain message. */
export function asFieldErrors(detail: unknown): FieldError[] | null {
  if (!isObj(detail)) return null;
  const errors = detail["errors"];
  return listOf((e): e is FieldError => isObj(e) && isStr(e["field"]) && isStr(e["message"]))(errors) ? errors : null;
}

function isModel(v: unknown): v is ModelInfo {
  if (!isObj(v)) return false;
  const price = v["price"];
  return (
    isStr(v["id"]) &&
    isStr(v["display_name"]) &&
    orNull(isNum)(v["max_input_tokens"] ?? null) &&
    orNull(isNum)(v["max_tokens"] ?? null) &&
    orNull(isStr)(v["retires_at"] ?? null) &&
    isStrList(v["efforts"] ?? []) &&
    (price === null || price === undefined || (isObj(price) && isNum(price["input_per_mtok"]) && isNum(price["output_per_mtok"])))
  );
}

export function asModelListing(v: unknown): ModelListing | null {
  if (!isObj(v) || !oneOf("api", "cache", "built_in")(v["source"]) || !orNull(isNum)(v["fetched_at"] ?? null)) return null;
  const models = v["models"];
  if (!listOf(isModel)(models)) return null;
  return {
    source: v["source"],
    fetched_at: (v["fetched_at"] as number | null | undefined) ?? null,
    models: models.map((m) => ({
      id: m.id,
      display_name: m.display_name,
      max_input_tokens: m.max_input_tokens ?? null,
      max_tokens: m.max_tokens ?? null,
      retires_at: m.retires_at ?? null,
      price: m.price ?? null,
      efforts: m.efforts ?? [],
    })),
  };
}

export function asKeyAnswer(v: unknown): KeyAnswer | null {
  return isObj(v) && isBool(v["stored"]) && isKeySource(v["source"]) && isVerdict(v["verdict"]) ? (v as unknown as KeyAnswer) : null;
}

export function asVerdict(v: unknown): Verdict | null {
  return isObj(v) && isVerdict(v["verdict"]) ? v["verdict"] : null;
}

const isDevice = (v: unknown): v is AudioDevice => isObj(v) && isStr(v["name"]) && isBool(v["default"]);

export function asVoiceDevices(v: unknown): VoiceDevices | null {
  return isObj(v) && isBool(v["installed"]) && listOf(isDevice)(v["inputs"]) && listOf(isDevice)(v["outputs"]) && isStrList(v["voices"])
    ? (v as unknown as VoiceDevices)
    : null;
}

export function asVoiceTest(v: unknown): VoiceTest | null {
  return isObj(v) && isBool(v["ok"]) && isStr(v["heard"]) && isStr(v["message"]) ? (v as unknown as VoiceTest) : null;
}

export function asSpeakTest(v: unknown): SpeakTest | null {
  return isObj(v) && isBool(v["ok"]) && isStr(v["message"]) ? { ok: v["ok"], message: v["message"] } : null;
}

function isDownload(v: unknown): v is Download {
  return (
    isObj(v) &&
    oneOf("idle", "running", "done", "failed")(v["state"]) &&
    isNum(v["done_bytes"]) &&
    orNull(isNum)(v["total_bytes"]) &&
    orNull(isStr)(v["message"])
  );
}

export function asDownloads(v: unknown): Downloads | null {
  return isObj(v) && isDownload(v["local_model"]) && isDownload(v["speech_models"]) ? (v as unknown as Downloads) : null;
}

export function asFolders(v: unknown): FolderSuggestion[] | null {
  if (!isObj(v)) return null;
  const dirs = v["dirs"];
  return listOf((d): d is FolderSuggestion => isObj(d) && isStr(d["name"]) && isStr(d["path"]))(dirs) ? dirs : null;
}

function isCheck(v: unknown): v is DoctorCheck {
  return (
    isObj(v) &&
    isStr(v["id"]) &&
    isStr(v["title"]) &&
    isStr(v["needed_for"]) &&
    isBool(v["needed"]) &&
    oneOf("ok", "missing", "optional")(v["status"]) &&
    isStr(v["detail"]) &&
    isStr(v["fix"])
  );
}

export function asDoctor(v: unknown): Doctor | null {
  if (!isObj(v) || !isBool(v["ok"]) || !listOf(isCheck)(v["checks"])) return null;
  const fixable = v["fixable"];
  return { ok: v["ok"], checks: v["checks"], fixable: isStrList(fixable) ? fixable : [] };
}

export function asFixAnswer(v: unknown): FixAnswer | null {
  return isObj(v) && isBool(v["started"]) && isStr(v["message"]) ? (v as unknown as FixAnswer) : null;
}

const isBackup = (v: unknown): v is Backup =>
  isObj(v) && isStr(v["id"]) && isNum(v["created_at"]) && isStr(v["level"]) && isStrList(v["files"]);

export function asBackups(v: unknown): Backup[] | null {
  if (!isObj(v)) return null;
  const list = v["backups"];
  return listOf(isBackup)(list) ? list : null;
}

export function asResetAnswer(v: unknown): ResetAnswer | null {
  return isObj(v) && isBackup(v["backup"]) && isBool(v["restart"]) && isStr(v["message"]) ? (v as unknown as ResetAnswer) : null;
}

export function asRestoreAnswer(v: unknown): RestoreAnswer | null {
  return isObj(v) && isStrList(v["restored"]) && isBackup(v["backup"]) && isBool(v["restart"]) ? (v as unknown as RestoreAnswer) : null;
}
