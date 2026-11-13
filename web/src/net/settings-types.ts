// The settings routes' shapes (the settings contract). The daemon is the
// source of truth; settings-guards.ts narrows its JSON to these.

import type { Owner } from "./owner";
import type { Listening, ListenMode } from "./types";

export type Tier = "free" | "ask" | "never";
export type KeySource = "keychain" | "env_file" | "environment";
export type Verdict = "accepted" | "refused" | "unreachable" | "none";
/** What the daemon learnt when it last opened the microphone; `silent` is the device sending only zeros. */
export type DaemonMic = "granted" | "denied" | "silent" | "unknown";
export type DownloadWhat = "local_model" | "speech_models";
export type ResetLevel = "settings" | "house" | "everything";

export interface SettingsAgent {
  id: string;
  name: string;
  model: string;
  heavy_model: string | null;
  /** The thinking level for the model and for careful work; the host's follow the talk and heavy levels. */
  effort: string;
  heavy_effort: string;
  is_host: boolean;
}

export interface VoiceState {
  installed: boolean;
  enabled: boolean;
  running: boolean;
  mic: DaemonMic;
  mic_detail: string | null;
  input_device: string;
  output_device: string;
  tts_voice: string;
  followup_s: number;
  /** When it listens, and the listening mode the quick control goes back to. */
  listen: ListenMode;
  listening: Listening;
  models_downloaded: boolean;
  models_size_bytes: number | null;
}

export interface GateTool {
  id: string;
  title: string;
  description: string;
}

export interface Settings {
  assistant: { name: string };
  /** The owner's profile, kept in the memory vault rather than config.toml. */
  owner: Owner;
  models: {
    talk: string;
    heavy: string;
    talk_effort: string;
    heavy_effort: string;
    /** `tools` is whether the local model can call tools, null until it has loaded. */
    /** `keep` is whether the model stays ready after its last use while offline mode is off: for `idle_s` seconds, or always. */
    local: { backend: string; model: string; downloaded: boolean; size_bytes: number | null; server: string; tools: boolean | null; offline: boolean; keep: "idle" | "always"; idle_s: number };
  };
  budget: { month: string; spent_usd: number; cap_usd: number; warn_fraction: number };
  agents: SettingsAgent[];
  voice: VoiceState;
  /**
   * `free_at_the_mac_only`: free holds only for what the owner types or says at the Mac.
   * `free_for_jobs_from_the_mac`: free holds only in a job the owner started at the Mac
   * (typed, said, or made in the window).
   */
  gate: { tools: GateTool[]; tiers: Record<string, Tier>; never_free: string[]; free_at_the_mac_only: string[]; free_for_jobs_from_the_mac: string[] };
  /** `root`: the folder new projects are made in, as the owner wrote it (`[projects] root`). */
  projects: { root: string };
  key: { stored: boolean; source: KeySource | null };
  setup: { completed: boolean; first_run: boolean };
  restart_pending: string[];
}

/** JSON a PATCH body may hold. */
export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

/** `PATCH /api/settings`: sections of dotted fields, e.g. `{"budget": {"cap_usd": 150}}`. */
export type SettingsPatch = Record<string, Record<string, Json>>;

export interface PatchAnswer {
  changed: string[];
  applied: string[];
  restart: string[];
  settings: Settings;
}

export interface FieldError {
  field: string;
  message: string;
}

export interface ModelPrice {
  input_per_mtok: number;
  output_per_mtok: number;
}

export interface ModelInfo {
  id: string;
  display_name: string;
  max_input_tokens: number | null;
  max_tokens: number | null;
  retires_at: string | null;
  price: ModelPrice | null;
  /** The thinking levels the model takes, lowest first; none for a model without the setting. */
  efforts: string[];
}

export interface ModelListing {
  source: "api" | "cache" | "built_in";
  fetched_at: number | null;
  models: ModelInfo[];
}

export interface KeyAnswer {
  stored: boolean;
  source: KeySource | null;
  verdict: Verdict;
}

export interface AudioDevice {
  name: string;
  default: boolean;
  /** Connected over Bluetooth (AirPods, a headset); an older daemon leaves it out. */
  bluetooth?: boolean;
}

export interface VoiceDevices {
  installed: boolean;
  inputs: AudioDevice[];
  outputs: AudioDevice[];
  voices: string[];
}

export interface VoiceTest {
  ok: boolean;
  heard: string;
  message: string;
}

/** `POST /api/voice/speak`: one sentence through the speakers. */
export interface SpeakTest {
  ok: boolean;
  message: string;
}

/** The unsaved choices the speaker test may try; left out, the saved ones. */
export interface SpeakChoice {
  tts_voice?: string;
  output_device?: string;
}

export interface Download {
  state: "idle" | "running" | "done" | "failed";
  done_bytes: number;
  total_bytes: number | null;
  message: string | null;
}

export type Downloads = Record<DownloadWhat, Download>;

export interface FolderSuggestion {
  name: string;
  path: string;
}

export interface DoctorCheck {
  id: string;
  title: string;
  needed_for: string;
  needed: boolean;
  status: "ok" | "missing" | "optional";
  detail: string;
  fix: string;
}

export interface Doctor {
  ok: boolean;
  checks: DoctorCheck[];
  fixable: string[];
}

export interface FixAnswer {
  started: boolean;
  message: string;
}

export interface Backup {
  id: string;
  created_at: number;
  level: string;
  files: string[];
}

export interface ResetAnswer {
  backup: Backup;
  restart: boolean;
  message: string;
}

export interface RestoreAnswer {
  restored: string[];
  backup: Backup;
  restart: boolean;
}

/** `PATCH /api/house/rooms/{id}`; null clears model or tools; `folders` is the whole list, and an empty one detaches every folder; an empty `project` clears the project name. */
export interface RoomPatch {
  name?: string;
  agent?: string;
  project?: string;
  folders?: string[];
  model?: string | null;
  tools?: string[] | null;
}
