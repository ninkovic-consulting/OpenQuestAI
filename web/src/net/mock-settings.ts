// Mock mode's settings routes: believable answers, validated the way the
// daemon validates them, so the whole settings screen and wizard work
// without a daemon. Rooms and agents change the mock house through `MockHouse`.

import { hostAgentId } from "./plan";
import {
  DEFAULT_TIERS,
  DEFAULT_VOICE,
  doctorChecks,
  FOLDERS,
  HAIKU,
  INPUTS,
  LOCAL_BYTES,
  LOCAL_MODEL,
  MOCK_MODELS,
  OLD_BACKUPS,
  OPUS,
  OUTPUTS,
  SPEECH_BYTES,
  TOOL_TEXT,
  VOICES,
} from "./mock-settings-data";
import { ok, refused, type Result, type SettingsApi } from "./settings-api";
import type {
  Backup,
  Doctor,
  Download,
  Downloads,
  DownloadWhat,
  FixAnswer,
  FolderSuggestion,
  Json,
  KeyAnswer,
  ModelListing,
  PatchAnswer,
  ResetAnswer,
  ResetLevel,
  RestoreAnswer,
  RoomPatch,
  Settings,
  SettingsPatch,
  Tier,
  Verdict,
  VoiceDevices,
  VoiceState,
  VoiceTest,
} from "./settings-types";
import type { Plan, ToolRef } from "./types";

/** What the mock settings may do to the mock house. */
export interface MockHouse {
  plan(): Plan;
  /** Announce a change made to `plan()`. */
  changed(): void;
  /** Back to the sample house. */
  reset(): void;
  /** The tools a room gets: these ids from the catalog, or its agent's own for null. */
  tools(ids: readonly string[] | null, agent: string): ToolRef[];
  /** Starting over: no automations either. */
  forgetAutomations(): void;
}

const DOWNLOAD_MS = 15_000;
const TEST_MS = 3000;
const RESTART_FIELDS = new Set(["models.talk", "models.heavy", "models.local"]);
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$/;
const HF_REPO = /^[A-Za-z0-9][\w.-]{0,95}\/[\w.-]{1,95}$/;
const KEY_SHAPE = /^sk-ant-[A-Za-z0-9_-]{20,300}$/;

interface Config {
  name: string;
  talk: string;
  heavy: string;
  local: string;
  cap: number;
  voice: VoiceState;
  tiers: Record<string, Tier>;
  completed: boolean;
}

const defaults = (): Config => ({
  name: "Vision",
  talk: HAIKU,
  heavy: OPUS,
  local: LOCAL_MODEL,
  cap: 150,
  voice: { ...DEFAULT_VOICE },
  tiers: { ...DEFAULT_TIERS },
  completed: false,
});

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const isNum = (v: Json): v is number => typeof v === "number" && Number.isFinite(v);
const plainName = (v: Json): boolean => typeof v === "string" && v.trim().length > 0 && v.trim().length <= 40 && !/[\u0000-\u001f]/.test(v);

export class MockSettings implements SettingsApi {
  private config = defaults();
  /** What the pretend daemon started with; differences in models wait for a restart. */
  private running = { talk: HAIKU, heavy: OPUS, local: LOCAL_MODEL };
  private key: { stored: boolean; replaced: boolean } = { stored: false, replaced: false };
  private spent = 18.42;
  private localStarted: number | null = null;
  private speechStarted: number | null = null;
  private localDone = false;
  private backupList: Backup[] = OLD_BACKUPS.map((b) => ({ ...b, files: [...b.files] }));

  constructor(private readonly house: MockHouse) {}

  // ------------------------------------------------------------ settings

  settings(): Promise<Result<Settings>> {
    return Promise.resolve(ok(this.snapshot()));
  }

  private snapshot(): Settings {
    const c = this.config;
    this.tickDownloads();
    const host = hostAgentId(this.house.plan());
    const pending = (["talk", "heavy", "local"] as const).filter((k) => c[k] !== this.running[k]).map((k) => `models.${k}`);
    return structuredClone({
      assistant: { name: c.name },
      models: { talk: c.talk, heavy: c.heavy, local: { backend: "mlx", model: c.local, downloaded: this.localDone, size_bytes: this.localDone ? LOCAL_BYTES : null } },
      budget: { month: "2026-11", spent_usd: this.spent, cap_usd: c.cap, warn_fraction: 0.8 },
      agents: this.house.plan().agents.map((a) => ({ id: a.id, name: a.name, model: a.model, heavy_model: a.heavy_model ?? null, is_host: a.id === host })),
      voice: c.voice,
      gate: {
        tools: Object.keys(DEFAULT_TIERS).map((id) => ({ id, title: titleOf(id), description: TOOL_TEXT[id] ?? "" })),
        tiers: c.tiers,
        never_free: ["shell"],
      },
      key: { stored: this.key.stored, source: this.key.stored ? "keychain" : null },
      setup: { completed: c.completed, first_run: !this.key.stored || !c.completed },
      restart_pending: this.key.replaced ? [...pending, "key"] : pending,
    });
  }

  patchSettings(patch: SettingsPatch): Promise<Result<PatchAnswer>> {
    const fields = flatten(patch);
    const errors = fields.flatMap(([field, value]) => {
      const message = this.problem(field, value);
      return message ? [{ field, message }] : [];
    });
    if (errors.length > 0) return Promise.resolve(refused(errors.map((e) => e.message).join(" "), errors));
    const changed = fields.filter(([field, value]) => this.apply(field, value)).map(([field]) => field);
    return Promise.resolve(
      ok({
        changed,
        applied: changed.filter((f) => !RESTART_FIELDS.has(f)),
        restart: changed.filter((f) => RESTART_FIELDS.has(f)),
        settings: this.snapshot(),
      }),
    );
  }

  /** Why a value is refused, in the daemon's words; null when it is fine. */
  private problem(field: string, value: Json): string | null {
    const [section, key, rest] = field.split(".");
    if (section === "agents") {
      const agent = this.house.plan().agents.find((a) => a.id === key);
      if (!agent) return `There is no agent with the id '${key ?? ""}'.`;
      if (agent.id === hostAgentId(this.house.plan())) return `The host's ${rest ?? "setting"} follows ${rest === "name" ? "the assistant's name" : "the talk model"}; change that.`;
      if (rest === "name") return plainName(value) ? null : "An agent's name must be 1 to 40 characters of plain text.";
      if (rest === "model") return typeof value === "string" && MODEL_ID.test(value) ? null : "Choose a model from the list; a model id looks like claude-opus-5-5.";
      return "An agent has a name and a model.";
    }
    if (section === "gate") {
      if (key !== "tiers" || rest === undefined || !(rest in DEFAULT_TIERS)) return `There is no tool called '${rest ?? key ?? ""}'.`;
      if (rest === "shell" && value === "free") return "shell always asks first, so it can be ask or never, but never free.";
      return value === "free" || value === "ask" || value === "never" ? null : "A tier is free, ask or never.";
    }
    switch (field) {
      case "assistant.name":
        return plainName(value) ? null : "The assistant's name must be 1 to 40 characters of plain text.";
      case "models.talk":
      case "models.heavy":
        return typeof value === "string" && MODEL_ID.test(value) ? null : "Choose a model from the list; a model id looks like claude-opus-5-5.";
      case "models.local":
        return typeof value === "string" && HF_REPO.test(value) ? null : "The local model must be a Hugging Face repo, like mlx-community/Qwen3-4B-Instruct-2507-4bit.";
      case "budget.cap_usd":
        return isNum(value) && value >= 0 && value <= 1_000_000 ? null : "The monthly cap must be a number of dollars, 0 or more.";
      case "voice.input_device":
      case "voice.output_device":
        return typeof value === "string" ? null : "Choose a device by its name, or leave it empty for the system default.";
      case "voice.tts_voice":
        return typeof value === "string" && VOICES.includes(value) ? null : `The voice must be one of: ${VOICES.join(", ")}.`;
      case "voice.followup_s":
        return isNum(value) && value >= 0 && value <= 300 ? null : "The follow-up window must be a number of seconds from 0 to 300.";
      case "setup.completed":
        return typeof value === "boolean" ? null : "Send true or false.";
      default:
        return "There is no such setting.";
    }
  }

  /** Set one checked value; true when it changed something. */
  private apply(field: string, value: Json): boolean {
    const c = this.config;
    const [section, key, rest] = field.split(".");
    const set = <T>(now: T, next: T, write: (v: T) => void): boolean => {
      if (now === next) return false;
      write(next);
      return true;
    };
    if (section === "agents" && key && rest) {
      const plan = this.house.plan();
      const agent = plan.agents.find((a) => a.id === key);
      if (!agent || (rest !== "name" && rest !== "model")) return false;
      const changed = set(agent[rest], String(value), (v) => (agent[rest] = v));
      if (changed) this.house.changed();
      return changed;
    }
    if (section === "gate" && rest) return set<Tier | undefined>(c.tiers[rest], value as Tier, (v) => (c.tiers[rest] = v ?? "ask"));
    switch (field) {
      case "assistant.name":
        return set(c.name, String(value).trim(), (v) => this.rename(v));
      case "models.talk":
        return set(c.talk, String(value), (v) => (c.talk = v));
      case "models.heavy":
        return set(c.heavy, String(value), (v) => (c.heavy = v));
      case "models.local":
        return set(c.local, String(value), (v) => (c.local = v));
      case "budget.cap_usd":
        return set(c.cap, Number(value), (v) => (c.cap = v));
      case "voice.input_device":
        return set(c.voice.input_device, String(value), (v) => (c.voice.input_device = v));
      case "voice.output_device":
        return set(c.voice.output_device, String(value), (v) => (c.voice.output_device = v));
      case "voice.tts_voice":
        return set(c.voice.tts_voice, String(value), (v) => (c.voice.tts_voice = v));
      case "voice.followup_s":
        return set(c.voice.followup_s, Number(value), (v) => (c.voice.followup_s = v));
      case "setup.completed":
        return set(c.completed, value === true, (v) => (c.completed = v));
      default:
        return false;
    }
  }

  private rename(name: string): void {
    this.config.name = name;
    const plan = this.house.plan();
    plan.assistant.name = name;
    const host = plan.agents.find((a) => a.id === hostAgentId(plan));
    if (host) host.name = name;
    this.house.changed();
  }

  // ------------------------------------------------------------ key and models

  storeKey(key: string): Promise<Result<KeyAnswer>> {
    if (!KEY_SHAPE.test(key.trim()))
      return Promise.resolve(refused("That does not look like an Anthropic API key. Keys start with sk-ant-; copy it again from console.anthropic.com, Settings, API keys."));
    this.key = { stored: true, replaced: this.key.replaced || this.key.stored };
    return wait(700).then(() => ok({ stored: true, source: "keychain", verdict: "accepted" }));
  }

  verifyKey(): Promise<Result<Verdict>> {
    return wait(500).then(() => ok(this.key.stored ? "accepted" : "none"));
  }

  models(): Promise<Result<ModelListing>> {
    return Promise.resolve(ok({ source: "api", fetched_at: Date.now() / 1000, models: MOCK_MODELS.map((m) => ({ ...m })) }));
  }

  // ------------------------------------------------------------ voice

  voiceDevices(): Promise<Result<VoiceDevices>> {
    return Promise.resolve(ok({ installed: true, inputs: INPUTS.map((d) => ({ ...d })), outputs: OUTPUTS.map((d) => ({ ...d })), voices: [...VOICES] }));
  }

  setVoice(enabled: boolean): Promise<Result<VoiceState>> {
    const v = this.config.voice;
    v.enabled = enabled;
    v.running = enabled;
    if (enabled) v.mic = "granted";
    return wait(400).then(() => ok({ ...v }));
  }

  voiceTest(): Promise<Result<VoiceTest>> {
    this.config.voice.mic = "granted";
    if (!this.config.voice.models_downloaded)
      return Promise.resolve(ok({ ok: false, heard: "", message: "The speech models are not downloaded yet. Download them first (about 2 GB)." }));
    const heard = "Testing one two three, can you hear me?";
    return wait(TEST_MS).then(() => ok({ ok: true, heard, message: `Heard: ${heard}` }));
  }

  // ------------------------------------------------------------ downloads

  downloads(): Promise<Result<Downloads>> {
    return Promise.resolve(ok(this.downloadState()));
  }

  startDownload(what: DownloadWhat): Promise<Result<Downloads>> {
    if (what === "local_model" && !this.localDone && this.localStarted === null) this.localStarted = Date.now();
    if (what === "speech_models" && !this.config.voice.models_downloaded && this.speechStarted === null) this.speechStarted = Date.now();
    return this.downloads();
  }

  private tickDownloads(): void {
    const now = Date.now();
    if (this.localStarted !== null && now - this.localStarted >= DOWNLOAD_MS) {
      this.localStarted = null;
      this.localDone = true;
    }
    if (this.speechStarted !== null && now - this.speechStarted >= DOWNLOAD_MS) {
      this.speechStarted = null;
      this.config.voice.models_downloaded = true;
      this.config.voice.models_size_bytes = SPEECH_BYTES;
    }
  }

  private downloadState(): Downloads {
    this.tickDownloads();
    const one = (done: boolean, started: number | null, total: number): Download => {
      if (done) return { state: "done", done_bytes: total, total_bytes: total, message: null };
      if (started === null) return { state: "idle", done_bytes: 0, total_bytes: total, message: null };
      const share = Math.min(1, (Date.now() - started) / DOWNLOAD_MS);
      return { state: "running", done_bytes: Math.round(total * share), total_bytes: total, message: null };
    };
    return {
      local_model: one(this.localDone, this.localStarted, LOCAL_BYTES),
      speech_models: one(this.config.voice.models_downloaded, this.speechStarted, SPEECH_BYTES),
    };
  }

  // ------------------------------------------------------------ folders and doctor

  folders(prefix: string): Promise<Result<FolderSuggestion[]>> {
    return Promise.resolve(mockFolders(prefix));
  }

  doctor(): Promise<Result<Doctor>> {
    this.tickDownloads();
    const checks = doctorChecks(this.key.stored, this.localDone);
    const fixable = checks.filter((c) => c.status !== "ok" && ["local_model", "speech_models", "window"].includes(c.id)).map((c) => c.id);
    return Promise.resolve(ok({ ok: checks.every((c) => !c.needed || c.status === "ok"), checks, fixable }));
  }

  fix(id: string): Promise<Result<FixAnswer>> {
    if (id !== "local_model" && id !== "speech_models") return Promise.resolve(refused(`'${id}' cannot be fixed from here; follow the doctor's advice.`));
    void this.startDownload(id);
    return Promise.resolve(ok({ started: true, message: `Downloading the ${id === "local_model" ? "local model" : "speech models"} in the background.` }));
  }

  // ------------------------------------------------------------ reset and backups

  reset(level: ResetLevel, removeKey: boolean): Promise<Result<ResetAnswer>> {
    const files = { settings: ["config.toml"], house: ["house.toml"], everything: ["config.toml", "house.toml", "house", "log.db", "budget.json", "automations.json"] }[level];
    const backup = this.backup(level, files);
    if (level !== "house") {
      const completed = level === "settings" && this.config.completed;
      this.config = { ...defaults(), completed };
      this.rename(this.config.name);
    }
    if (level !== "settings") this.house.reset();
    if (level === "everything") {
      this.spent = 0;
      this.house.forgetAutomations();
      if (removeKey) this.key = { stored: false, replaced: false };
    }
    const restart = level === "everything" || this.snapshot().restart_pending.length > 0;
    const words = { settings: "Settings are back to their defaults.", house: "The house is back to the default rooms and agents.", everything: "Everything is fresh." }[level];
    const message = `${words}${removeKey && level === "everything" ? " The API key was removed from the Keychain." : ""}${restart ? " Restart the assistant to finish." : ""}`;
    return wait(400).then(() => ok({ backup, restart, message }));
  }

  backups(): Promise<Result<Backup[]>> {
    return Promise.resolve(ok(this.backupList.map((b) => ({ ...b, files: [...b.files] }))));
  }

  restore(id: string): Promise<Result<RestoreAnswer>> {
    const found = this.backupList.find((b) => b.id === id);
    if (!found) return Promise.resolve(refused(`There is no backup called '${id}'.`));
    const backup = this.backup("restore", [...found.files]);
    const restart = found.files.some((f) => f === "log.db" || f === "house" || f === "config.toml");
    return wait(400).then(() => ok({ restored: [...found.files], backup, restart }));
  }

  private backup(level: string, files: string[]): Backup {
    const d = new Date();
    const pad = (n: number): string => String(n).padStart(2, "0");
    const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
    const backup = { id: `${stamp}-${level}`, created_at: d.getTime() / 1000, level, files };
    this.backupList.unshift(backup);
    return { ...backup, files: [...files] };
  }

  // ------------------------------------------------------------ rooms

  patchRoom(id: string, patch: RoomPatch): Promise<Result<null>> {
    const plan = this.house.plan();
    const room = plan.rooms.find((r) => r.id === id);
    if (!room) return Promise.resolve(refused(`There is no room called '${id}'.`));
    const host = hostAgentId(plan);
    if (patch.name !== undefined && !plainName(patch.name)) return Promise.resolve(refused("A room's name must be 1 to 40 characters of plain text."));
    if (patch.agent !== undefined && patch.agent !== room.agent) {
      if (room.id === "hall") return Promise.resolve(refused("The Hall is the host's room; its agent does not change."));
      if (!plan.agents.some((a) => a.id === patch.agent)) return Promise.resolve(refused(`Unknown agent: ${patch.agent}`));
      if (patch.agent === host) return Promise.resolve(refused("The host orchestrates from the Hall and cannot run another room."));
    }
    if (patch.name !== undefined) room.name = patch.name.trim();
    if (patch.agent !== undefined) room.agent = patch.agent;
    if (patch.project !== undefined) room.project = patch.project;
    const agent = plan.agents.find((a) => a.id === room.agent);
    if (patch.model !== undefined || patch.agent !== undefined) {
      const own = patch.model === undefined ? null : patch.model;
      room.model = own ?? agent?.model ?? room.model;
    }
    if (patch.tools !== undefined || patch.agent !== undefined) room.tools = this.house.tools(patch.tools ?? null, room.agent);
    this.house.changed();
    return wait(250).then(() => ok(null));
  }

  removeRoom(id: string): Promise<Result<null>> {
    const plan = this.house.plan();
    const room = plan.rooms.find((r) => r.id === id);
    if (!room) return Promise.resolve(refused(`There is no room called '${id}'.`));
    if (room.kind !== "extra") return Promise.resolve(refused(`${room.name} is one of the house's own rooms and stays.`));
    plan.rooms = plan.rooms.filter((r) => r.id !== id);
    plan.doors = plan.doors.filter((d) => d.a !== id && d.b !== id);
    plan.free_slots.push(room.at);
    this.house.changed();
    return wait(250).then(() => ok(null));
  }
}

/** `{"agents": {"maker": {"name": "Tink"}}}` as `[["agents.maker.name", "Tink"]]`. */
export function flatten(patch: SettingsPatch): [string, Json][] {
  const out: [string, Json][] = [];
  const walk = (prefix: string, value: Json): void => {
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      for (const [k, v] of Object.entries(value)) walk(`${prefix}.${k}`, v);
    } else {
      out.push([prefix, value]);
    }
  };
  for (const [section, values] of Object.entries(patch)) walk(section, values);
  return out;
}

/** `GET /api/fs/dirs` over the made-up folder tree, with the daemon's rules. */
export function mockFolders(prefix: string): Result<FolderSuggestion[]> {
  const text = prefix.trim();
  if (!text.startsWith("/") && !text.startsWith("~")) return refused("A folder starts with / or ~.");
  if (text.split("/").includes("..")) return refused("A folder path cannot go up with '..'.");
  if (/^~[^/]/.test(text)) return refused("Only your own home folder (~) can be listed.");
  const cut = text === "~" ? 1 : text.lastIndexOf("/");
  const parent = text === "~" ? "~" : text.slice(0, cut) || "/";
  const partial = text === "~" ? "" : text.slice(cut + 1).toLowerCase();
  const names = FOLDERS[parent];
  if (!names) return refused(`There is no folder at ${parent}.`);
  return ok(
    names
      .filter((n) => n.toLowerCase().startsWith(partial) && (!n.startsWith(".") || partial.startsWith(".")))
      .slice(0, 50)
      .map((name) => ({ name, path: parent === "/" ? `/${name}` : `${parent}/${name}` })),
  );
}

function titleOf(id: string): string {
  const t = id.replace(/_/g, " ");
  return id === "open_url" ? "Open link" : t.charAt(0).toUpperCase() + t.slice(1);
}
