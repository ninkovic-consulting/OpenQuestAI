// The settings routes' shapes (the settings contract). The daemon is the
// source of truth; settings-guards.ts narrows its JSON to these.

export type Tier = "free" | "ask" | "never";
export type KeySource = "keychain" | "env_file" | "environment";
export type Verdict = "accepted" | "refused" | "unreachable" | "none";
export type DaemonMic = "granted" | "denied" | "unknown";
export type DownloadWhat = "local_model" | "speech_models";
export type ResetLevel = "settings" | "house" | "everything";

export interface SettingsAgent {
  id: string;
  name: string;
  model: string;
  heavy_model: string | null;
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
  models: {
    talk: string;
    heavy: string;
    local: { backend: string; model: string; downloaded: boolean; size_bytes: number | null };
  };
  budget: { month: string; spent_usd: number; cap_usd: number; warn_fraction: number };
  agents: SettingsAgent[];
  voice: VoiceState;
  gate: { tools: GateTool[]; tiers: Record<string, Tier>; never_free: string[] };
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

/** `PATCH /api/house/rooms/{id}`; null clears project, model or tools. */
export interface RoomPatch {
  name?: string;
  agent?: string;
  project?: string | null;
  model?: string | null;
  tools?: string[] | null;
}
