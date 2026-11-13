// Mock mode's settings routes: believable answers, validated the way the
// daemon validates them, so the whole settings screen and wizard work
// without a daemon. Rooms and agents change the mock house through `MockHouse`.

import type { BrainMode, DeleteAnswer, LocalListing, ServerTest } from "./brain-types";
import { applied, BRAIN_FIELDS, brainProblems, HF_REPO, SERVER_URL, valueProblem, type BrainState } from "./mock-brain-rules";
import { effortProblem, levelTable } from "./mock-effort";
import { folderRefusal, rootProblem } from "./mock-folders";
import { projectProblem } from "./project-name";
import { MockLocal } from "./mock-local";
import { MOCK_SERVER } from "./mock-local-data";
import { hostAgentId } from "./plan";
import {
  DEFAULT_TIERS,
  DEFAULT_VOICE,
  doctorChecks,
  FOLDERS,
  HAIKU,
  INPUTS,
  LOCAL_MODEL,
  MOCK_HOME,
  MOCK_MODELS,
  OLD_BACKUPS,
  OPUS,
  OUTPUTS,
  SILENT_INPUT,
  SPEECH_BYTES,
  SPEECH_REPO,
  TOOL_TEXT,
  VOICES,
} from "./mock-settings-data";
import { emptyOwner, ownerProblem, type Owner } from "./owner";
import { ok, refused, type Result, type SettingsApi } from "./settings-api";
import type {
  Backup,
  DeleteAllAnswer,
  DeleteAllPreview,
  Doctor,
  Download,
  Downloads,
  DownloadWhat,
  FieldError,
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
  SpeakChoice,
  SpeakTest,
  Tier,
  Verdict,
  VoiceDevices,
  VoiceState,
  VoiceTest,
} from "./settings-types";
import type { Listening, ListenMode, ListenView, MicState, Plan, ToolRef } from "./types";

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
  /** Starting over: unpaired, the phone's settings back to defaults; its token only when asked. */
  forgetPhone(removeToken: boolean): void;
}

const DOWNLOAD_MS = 15_000;
const TEST_MS = 3000;
const SPEAK_MS = 1500;
/** As the daemon words it: speech models are downloaded only when the owner asks. */
const MISSING_SPEECH =
  "The speech models are not downloaded (speech recognition, the speaking voice, voice detection, the speaking voice's English tagger missing). Download them in Settings, Voice; nothing is downloaded by itself.";
const SERVER_MS = 800;
const RESTART_FIELDS = new Set(["models.talk", "models.heavy"]);
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$/;
const KEY_SHAPE = /^sk-ant-[A-Za-z0-9_-]{20,300}$/;

interface Config {
  name: string;
  talk: string;
  heavy: string;
  talkEffort: string;
  heavyEffort: string;
  local: string;
  backend: string;
  server: string;
  offline: boolean;
  keep: "idle" | "always";
  cap: number;
  voice: VoiceState;
  tiers: Record<string, Tier>;
  projectsRoot: string;
  completed: boolean;
}

const defaults = (): Config => ({
  name: "Vision",
  talk: HAIKU,
  heavy: OPUS,
  talkEffort: "low",
  heavyEffort: "high",
  local: LOCAL_MODEL,
  backend: "mlx",
  server: MOCK_SERVER,
  offline: false,
  keep: "idle",
  cap: 150,
  voice: { ...DEFAULT_VOICE },
  tiers: { ...DEFAULT_TIERS },
  projectsRoot: "~/Projects",
  completed: false,
});

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const isNum = (v: Json): v is number => typeof v === "number" && Number.isFinite(v);
const plainName = (v: Json): boolean => typeof v === "string" && v.trim().length > 0 && v.trim().length <= 40 && !/[\u0000-\u001f]/.test(v);

export class MockSettings implements SettingsApi {
  private config = defaults();
  /** What the pretend daemon started with; differences in models wait for a restart. */
  private running = { talk: HAIKU, heavy: OPUS };
  private key: { stored: boolean; replaced: boolean } = { stored: false, replaced: false };
  private spent = 18.42;
  private speechStarted: number | null = null;
  private readonly local = new MockLocal();
  /** The owner's profile lives in the vault, so only starting over clears it. */
  private owner: Owner = emptyOwner();
  private backupList: Backup[] = OLD_BACKUPS.map((b) => ({ ...b, files: [...b.files] }));

  /**
   * `announce` hears every change of offline mode or of the local model, as
   * `brain.mode`; `listened` every change to when voice listens, or to voice
   * itself or the shell's tier, as `voice.listen` would announce it.
   */
  constructor(
    private readonly house: MockHouse,
    private readonly announce: (mode: BrainMode) => void = () => {},
    private readonly listened: () => void = () => {},
  ) {}

  /** `voice.listen` as things are, with the pretend microphone's `mic`. */
  listenView(mic: MicState): ListenView {
    const v = this.config.voice;
    return { mode: v.listen, mic: v.running ? mic : "closed", voice: v.running, listening: v.listening, shell_free: this.config.tiers["shell"] === "free" };
  }

  /** `?listen=hold|wake|always`: voice on and running, listening that way, for screenshots. */
  preset(mode: ListenMode): void {
    const v = this.config.voice;
    v.enabled = true;
    this.startVoice();
    v.listen = mode;
    if (mode !== "hold") v.listening = mode;
  }

  /** Offline mode and the local model, as `GET /api/state` and `brain.mode` carry them. */
  mode(): BrainMode {
    const c = this.config;
    return {
      offline: c.offline,
      answering: c.offline ? "local" : "claude",
      local_backend: c.backend,
      local_model: c.local,
      local_tools: c.backend === "mlx" ? MockLocal.tools(c.local) : true,
      // No local model in the catalog reads images yet, as on the daemon.
      local_images: false,
      // Offline mode loads the model at once; the pretend one is in memory as soon as it is on.
      local_state: c.backend === "mlx" && c.offline ? "ready" : "unloaded",
      local_bytes: c.backend === "mlx" && c.offline ? this.local.bytes(c.local) : null,
      local_cache_bytes: 0,
      local_reading: null,
      local_problem: null,
    };
  }

  private brainState(): BrainState {
    const c = this.config;
    return { talk: c.talk, heavy: c.heavy, talkEffort: c.talkEffort, heavyEffort: c.heavyEffort, offline: c.offline, backend: c.backend, local: c.local, server: c.server };
  }

  // ------------------------------------------------------------ settings

  settings(): Promise<Result<Settings>> {
    return Promise.resolve(ok(this.snapshot()));
  }

  private snapshot(): Settings {
    const c = this.config;
    this.tickDownloads();
    const host = hostAgentId(this.house.plan());
    const pending = (["talk", "heavy"] as const).filter((k) => c[k] !== this.running[k]).map((k) => `models.${k}`);
    return structuredClone({
      assistant: { name: c.name },
      owner: { ...this.owner },
      models: {
        talk: c.talk,
        heavy: c.heavy,
        talk_effort: c.talkEffort,
        heavy_effort: c.heavyEffort,
        local: {
          backend: c.backend,
          model: c.local,
          downloaded: c.backend !== "mlx" || this.local.onDisk(c.local),
          size_bytes: c.backend === "mlx" ? this.local.bytes(c.local) : null,
          server: c.server,
          tools: c.backend === "mlx" ? MockLocal.tools(c.local) : true,
          offline: c.offline,
          keep: c.keep,
          idle_s: 600,
        },
      },
      budget: { month: "2026-11", spent_usd: this.spent, cap_usd: c.cap, warn_fraction: 0.8 },
      agents: this.house.plan().agents.map((a) => ({ id: a.id, name: a.name, model: a.model, heavy_model: a.heavy_model ?? null, effort: a.effort ?? "medium", heavy_effort: a.heavy_effort ?? "high", is_host: a.id === host })),
      voice: c.voice,
      gate: {
        tools: Object.keys(DEFAULT_TIERS).map((id) => ({ id, title: titleOf(id), description: TOOL_TEXT[id] ?? "" })),
        tiers: c.tiers,
        never_free: ["start_project"],
        free_at_the_mac_only: ["shell"],
        free_for_jobs_from_the_mac: ["run_program"],
      },
      projects: { root: c.projectsRoot },
      key: { stored: this.key.stored, source: this.key.stored ? "keychain" : null },
      setup: { completed: c.completed, first_run: !this.key.stored || !c.completed },
      restart_pending: this.key.replaced ? [...pending, "key"] : pending,
      data: { home: MOCK_HOME },
    });
  }

  patchSettings(patch: SettingsPatch): Promise<Result<PatchAnswer>> {
    const fields = flatten(patch);
    const errors = fields.flatMap(([field, value]) => {
      const message = this.problem(field, value);
      return message ? [{ field, message }] : [];
    });
    if (errors.length === 0) errors.push(...this.changeProblems(fields), ...this.listenProblems(fields));
    if (errors.length > 0) return Promise.resolve(refused(errors.map((e) => e.message).join(" "), errors));
    const before = JSON.stringify(this.mode());
    const heard = JSON.stringify(this.listenView("closed"));
    const changed = fields.filter(([field, value]) => this.apply(field, value)).map(([field]) => field);
    if (JSON.stringify(this.mode()) !== before) this.announce(this.mode());
    if (JSON.stringify(this.listenView("closed")) !== heard) this.listened();
    return Promise.resolve(
      ok({
        changed,
        applied: changed.filter((f) => !RESTART_FIELDS.has(f)),
        restart: changed.filter((f) => RESTART_FIELDS.has(f)),
        settings: this.snapshot(),
      }),
    );
  }

  /** The problems of the whole change: levels the models do not take, and offline mode without its model. */
  private changeProblems(fields: readonly (readonly [string, Json])[]): FieldError[] {
    const before = this.brainState();
    const errors = brainProblems(before, applied(before, fields), this.local);
    const plan = this.house.plan();
    const value = (id: string, key: string): Json | undefined => fields.find(([f]) => f === `agents.${id}.${key}`)?.[1];
    for (const agent of plan.agents) {
      if (!fields.some(([f]) => f.startsWith(`agents.${agent.id}.`))) continue;
      const model = String(value(agent.id, "model") ?? agent.model);
      const levels = [
        ["effort", model, value(agent.id, "effort") ?? agent.effort ?? "medium"],
        ["heavy_effort", agent.heavy_model ?? model, value(agent.id, "heavy_effort") ?? agent.heavy_effort ?? "high"],
      ] as const;
      for (const [key, runsOn, level] of levels) {
        const message = effortProblem(runsOn, String(level));
        if (message) errors.push({ field: `agents.${agent.id}.${key}`, message });
      }
    }
    return errors;
  }

  /** Like the daemon: the listening mode changes only while voice is on with its speech models. */
  private listenProblems(fields: readonly (readonly [string, Json])[]): FieldError[] {
    const v = this.config.voice;
    const asked = fields.find(([f]) => f === "voice.listen");
    if (!asked || asked[1] === v.listen) return [];
    if (!v.enabled) return [{ field: "voice.listen", message: `Voice is off. Turn it on first, then choose when ${this.config.name} listens.` }];
    if (!v.models_downloaded) return [{ field: "voice.listen", message: MISSING_SPEECH }];
    return [];
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
      if (rest === "effort" || rest === "heavy_effort") return valueProblem(field, value);
      return "An agent has a name, a model, an effort and a heavy_effort.";
    }
    if (section === "owner") return ownerProblem(key ?? "", value);
    if (section === "gate") {
      if (key !== "tiers" || rest === undefined || !(rest in DEFAULT_TIERS)) return `There is no tool called '${rest ?? key ?? ""}'.`;
      return value === "free" || value === "ask" || value === "never" ? null : "A tier is free, ask or never.";
    }
    if (BRAIN_FIELDS.has(field)) return valueProblem(field, value);
    switch (field) {
      case "assistant.name":
        return plainName(value) ? null : "The assistant's name must be 1 to 40 characters of plain text.";
      case "models.talk":
      case "models.heavy":
        return typeof value === "string" && MODEL_ID.test(value) ? null : "Choose a model from the list; a model id looks like claude-opus-5-5.";
      case "budget.cap_usd":
        return isNum(value) && value >= 0 && value <= 1_000_000 ? null : "The monthly cap must be a number of dollars, 0 or more.";
      case "voice.input_device":
      case "voice.output_device":
        return typeof value === "string" ? null : "Choose a device by its name, or leave it empty for the system default.";
      case "voice.tts_voice":
        return typeof value === "string" && VOICES.includes(value) ? null : `The voice must be one of: ${VOICES.join(", ")}.`;
      case "voice.followup_s":
        return isNum(value) && value >= 0 && value <= 300 ? null : "The follow-up window must be a number of seconds from 0 to 300.";
      case "voice.listen":
        return value === "hold" || value === "wake" || value === "always" ? null : "When it listens is hold (only while you hold to talk), wake (for its name) or always.";
      case "voice.listening":
        return value === "wake" || value === "always" ? null : "The listening mode is wake or always.";
      case "setup.completed":
        return typeof value === "boolean" ? null : "Send true or false.";
      case "projects.root":
        return typeof value === "string" ? rootProblem(value, isMockFolder) : "Choose the folder new projects go in, such as ~/Projects.";
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
      if (!agent) return false;
      let changed = false;
      if (rest === "name" || rest === "model") changed = set(agent[rest], String(value), (v) => (agent[rest] = v));
      if (rest === "effort" || rest === "heavy_effort") changed = set(agent[rest] ?? "", String(value), (v) => (agent[rest] = v));
      if (changed) {
        plan.effort_levels = levelTable(plan.agents.flatMap((a) => [a.model, a.heavy_model ?? a.model]));
        this.house.changed();
      }
      return changed;
    }
    if (section === "owner" && (key === "name" || key === "business" || key === "notes")) {
      const part = key;
      return set(this.owner[part], String(value).trim(), (v) => (this.owner[part] = v));
    }
    if (section === "gate" && rest) return set<Tier | undefined>(c.tiers[rest], value as Tier, (v) => (c.tiers[rest] = v ?? "ask"));
    switch (field) {
      case "assistant.name":
        return set(c.name, String(value).trim(), (v) => this.rename(v));
      case "models.talk":
        return set(c.talk, String(value), (v) => (c.talk = v));
      case "models.heavy":
        return set(c.heavy, String(value), (v) => (c.heavy = v));
      case "models.talk_effort":
        return set(c.talkEffort, String(value), (v) => ((c.talkEffort = v), this.syncHost()));
      case "models.heavy_effort":
        return set(c.heavyEffort, String(value), (v) => ((c.heavyEffort = v), this.syncHost()));
      case "models.offline":
        return set(c.offline, value === true, (v) => (c.offline = v));
      case "models.local":
        return set(c.local, String(value).trim(), (v) => (c.local = v));
      case "models.local_backend":
        return set(c.backend, String(value), (v) => (c.backend = v));
      case "models.local_server":
        return set(c.server, String(value).trim().replace(/\/$/, ""), (v) => (c.server = v));
      case "models.local_keep":
        return set<Config["keep"]>(c.keep, value === "always" ? "always" : "idle", (v) => (c.keep = v));
      case "budget.cap_usd":
        return set(c.cap, Number(value), (v) => (c.cap = v));
      case "voice.input_device":
        return set(c.voice.input_device, String(value), (v) => {
          c.voice.input_device = v;
          if (c.voice.enabled) this.startVoice(); // a new microphone applies at once, after a failure too
        });
      case "voice.output_device":
        return set(c.voice.output_device, String(value), (v) => (c.voice.output_device = v));
      case "voice.tts_voice":
        return set(c.voice.tts_voice, String(value), (v) => (c.voice.tts_voice = v));
      case "voice.followup_s":
        return set(c.voice.followup_s, Number(value), (v) => (c.voice.followup_s = v));
      case "voice.listen":
        return set(c.voice.listen, value as ListenMode, (v) => {
          c.voice.listen = v;
          if (v !== "hold") c.voice.listening = v;
        });
      case "voice.listening":
        return set(c.voice.listening, value as Listening, (v) => (c.voice.listening = v));
      case "setup.completed":
        return set(c.completed, value === true, (v) => (c.completed = v));
      case "projects.root":
        return set(c.projectsRoot, String(value).trim(), (v) => (c.projectsRoot = v));
      default:
        return false;
    }
  }

  /** The host's levels are the talk and heavy levels. */
  private syncHost(): void {
    const plan = this.house.plan();
    const host = plan.agents.find((a) => a.id === hostAgentId(plan));
    if (!host) return;
    host.effort = this.config.talkEffort;
    host.heavy_effort = this.config.heavyEffort;
    this.house.changed();
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
    v.running = false;
    if (enabled) this.startVoice();
    return wait(400).then(() => {
      this.listened();
      return ok({ ...v });
    });
  }

  /** Open the pretend microphone; the webcam in privacy mode sends only silence. */
  private startVoice(): void {
    const v = this.config.voice;
    if (!v.models_downloaded) {
      // Like the daemon: nothing downloads by itself, and the microphone stays closed.
      v.running = false;
      v.mic = "unknown";
      v.mic_detail = MISSING_SPEECH;
      return;
    }
    const silent = v.input_device === SILENT_INPUT;
    v.running = !silent;
    v.mic = silent ? "silent" : "granted";
    v.mic_detail = silent
      ? `The microphone “${SILENT_INPUT}” sends only silence. It may be muted, asleep or covered: a webcam in privacy mode, or a laptop's own microphone with the lid closed. Choose another microphone in Settings, Voice. If no microphone works, check that Vision may use the microphone in System Settings > Privacy & Security > Microphone.`
      : null;
  }

  speakTest(choice: SpeakChoice): Promise<Result<SpeakTest>> {
    if (choice.tts_voice !== undefined && !VOICES.includes(choice.tts_voice)) return Promise.resolve(refused("Choose one of the speaking voices."));
    if (!this.config.voice.models_downloaded)
      return Promise.resolve(ok({ ok: false, message: "The speech models are not downloaded (the speaking voice, the speaking voice's English tagger missing). Download them in Settings, Voice; nothing is downloaded by itself." }));
    return wait(SPEAK_MS).then(() => ok({ ok: true, message: `Said: “Hello, I am ${this.config.name}. This is how I sound.”` }));
  }

  voiceTest(): Promise<Result<VoiceTest>> {
    this.config.voice.mic = "granted";
    if (!this.config.voice.models_downloaded)
      return Promise.resolve(ok({ ok: false, heard: "", message: MISSING_SPEECH }));
    const heard = "Testing one two three, can you hear me?";
    return wait(TEST_MS).then(() => ok({ ok: true, heard, message: `Heard: ${heard}` }));
  }

  // ------------------------------------------------------------ downloads

  downloads(): Promise<Result<Downloads>> {
    return Promise.resolve(ok(this.downloadState()));
  }

  startDownload(what: DownloadWhat): Promise<Result<Downloads>> {
    if (what === "local_model") this.local.start(this.config.local);
    if (what === "speech_models" && !this.config.voice.models_downloaded && this.speechStarted === null) this.speechStarted = Date.now();
    return this.downloads();
  }

  private tickDownloads(): void {
    const now = Date.now();
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
      local_model: this.local.download(this.config.local),
      speech_models: one(this.config.voice.models_downloaded, this.speechStarted, SPEECH_BYTES),
    };
  }

  // ------------------------------------------------------------ local models

  private chosen(): Parameters<MockLocal["listing"]>[0] {
    const c = this.config;
    return { backend: c.backend, model: c.local, server: c.server, offline: c.offline };
  }

  localModels(): Promise<Result<LocalListing>> {
    return Promise.resolve(ok(this.local.listing(this.chosen())));
  }

  downloadLocal(repo: string): Promise<Result<LocalListing>> {
    if (!HF_REPO.test(repo) || repo.includes("..")) return Promise.resolve(refused("Name a Hugging Face repo, like mlx-community/Qwen3-8B-4bit."));
    this.local.start(repo);
    return this.localModels();
  }

  deleteLocal(repo: string): Promise<Result<DeleteAnswer>> {
    const c = this.config;
    if (!HF_REPO.test(repo) || repo.includes("..")) return Promise.resolve(refused("Name a Hugging Face repo, like mlx-community/Qwen3-8B-4bit."));
    if (c.offline && c.backend === "mlx" && c.local === repo)
      return Promise.resolve(refused(`${repo} is the model offline mode is using. Choose another or turn offline mode off first.`));
    if (this.local.download(repo).state === "running") return Promise.resolve(refused(`${repo} is still downloading.`));
    const freed = this.local.remove(repo);
    return Promise.resolve(ok({ deleted: repo, freed_bytes: freed, ...this.local.listing(this.chosen()) }));
  }

  testServer(server?: string): Promise<Result<ServerTest>> {
    const address = server ?? this.config.server;
    if (!SERVER_URL.test(address.trim())) return Promise.resolve(refused("The server address is an http:// or https:// address, like http://127.0.0.1:1234/v1."));
    return wait(SERVER_MS).then(() => ok(MockLocal.testServer(address)));
  }

  // ------------------------------------------------------------ folders and doctor

  folders(prefix: string): Promise<Result<FolderSuggestion[]>> {
    return Promise.resolve(mockFolders(prefix));
  }

  doctor(): Promise<Result<Doctor>> {
    this.tickDownloads();
    const checks = doctorChecks(this.key.stored, this.local.onDisk(this.config.local));
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
    const files = { settings: ["config.toml"], house: ["house.toml"], everything: ["config.toml", "house.toml", "house", "log.db", "budget.json", "automations.json", "phone.json"] }[level];
    const backup = this.backup(level, files);
    if (level !== "house") {
      const completed = level === "settings" && this.config.completed;
      this.config = { ...defaults(), completed };
      this.rename(this.config.name);
      this.announce(this.mode());
    }
    if (level !== "settings") this.house.reset();
    if (level === "everything") {
      this.spent = 0;
      this.owner = emptyOwner();
      this.house.forgetAutomations();
      this.house.forgetPhone(removeKey);
      if (removeKey) this.key = { stored: false, replaced: false };
    }
    const restart = level === "everything" || this.snapshot().restart_pending.length > 0;
    const words = { settings: "Settings are back to their defaults.", house: "The house is back to the default rooms and agents.", everything: "Everything is fresh." }[level];
    const message = `${words}${removeKey && level === "everything" ? " The API key and the phone's bot token were removed from the Keychain." : ""}${restart ? " Restart the assistant to finish." : ""}`;
    return wait(400).then(() => ok({ backup, restart, message }));
  }

  // ------------------------------------------------------------ delete all data

  deleteAllPreview(): Promise<Result<DeleteAllPreview>> {
    const models = this.modelsOnDisk();
    return Promise.resolve(ok({ home: MOCK_HOME, models, models_bytes: models.reduce((n, m) => n + m.bytes, 0) }));
  }

  /** Answers as the daemon would; mock mode keeps running, since nothing here is real. */
  deleteAll(models: boolean): Promise<Result<DeleteAllAnswer>> {
    const present = this.modelsOnDisk();
    const freed = present.reduce((n, m) => n + m.bytes, 0);
    if (models) {
      for (const m of present) this.local.remove(m.repo);
      this.config.voice.models_downloaded = false;
      this.config.voice.models_size_bytes = null;
    }
    this.key = { stored: false, replaced: false };
    const left = [{ name: "notes.txt", why: "The app did not make it." }];
    const answer: DeleteAllAnswer = {
      home: MOCK_HOME,
      removed: ["backups", "config.toml", "house", "house.toml", "images", "log.db", "logs", "token"],
      left,
      folder_removed: false,
      elsewhere: [],
      keychain: { ok: true, message: "The API key and the phone's bot token are no longer in the Keychain." },
      models: models ? { removed: present.map((m) => m.repo), left: [], freed_bytes: freed } : null,
      launch_agent: { installed: false, removed: false, message: "" },
      message: "Everything the app made in the data folder is gone. It still holds what the app did not make: notes.txt. The assistant stops now.",
    };
    return wait(600).then(() => ok(answer));
  }

  private modelsOnDisk(): { repo: string; bytes: number }[] {
    const local = this.local.present(this.config.backend === "mlx" ? [this.config.local] : []);
    return this.config.voice.models_downloaded ? [...local, { repo: SPEECH_REPO, bytes: SPEECH_BYTES }] : local;
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
    const folders = patch.folders === undefined ? null : folderRefusal(patch.folders, plan.max_room_folders);
    if (folders !== null) return Promise.resolve(refused(folders, [{ field: "folders", message: folders }]));
    const project = patch.project === undefined ? null : projectProblem(patch.project);
    if (project !== null) return Promise.resolve(refused(project, [{ field: "project", message: project }]));
    if (patch.name !== undefined && !plainName(patch.name)) return Promise.resolve(refused("A room's name must be 1 to 40 characters of plain text."));
    if (patch.agent !== undefined && patch.agent !== room.agent) {
      if (room.id === "hall") return Promise.resolve(refused("The Hall is the host's room; its agent does not change."));
      if (!plan.agents.some((a) => a.id === patch.agent)) return Promise.resolve(refused(`Unknown agent: ${patch.agent}`));
      if (patch.agent === host) return Promise.resolve(refused("The host orchestrates from the Hall and cannot run another room."));
    }
    if (patch.name !== undefined) room.name = patch.name.trim();
    if (patch.agent !== undefined) room.agent = patch.agent;
    if (patch.folders !== undefined) room.folders = patch.folders.map((f) => f.trim());
    if (patch.project !== undefined) room.project = patch.project.trim() || null;
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

/** Whether the made-up folder tree holds this folder. */
export function isMockFolder(path: string): boolean {
  if (path in FOLDERS) return true;
  const cut = path.lastIndexOf("/");
  const parent = cut <= 0 ? (path.startsWith("~") ? "~" : "/") : path.slice(0, cut);
  return FOLDERS[parent]?.includes(path.slice(cut + 1)) ?? false;
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
  if (id === "open_url") return "Open link";
  if (id === "run_program") return "Run a program";
  return t.charAt(0).toUpperCase() + t.slice(1);
}
