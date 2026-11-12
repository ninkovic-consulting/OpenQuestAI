// Mock mode's made-up answers for the settings screen: models with prices,
// audio devices, a folder tree, the doctor's checks and two old backups.

import type { Backup, DoctorCheck, ModelInfo, VoiceState } from "./settings-types";

export const HAIKU = "claude-haiku-5-5";
export const OPUS = "claude-opus-5-5";
export const LOCAL_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-4bit";
export const LOCAL_BYTES = 2_100_000_000;
export const SPEECH_BYTES = 1_960_000_000;

const model = (id: string, display_name: string, price: [number, number] | null, retires_at: string | null = null): ModelInfo => ({
  id,
  display_name,
  max_input_tokens: 1_000_000,
  max_tokens: 128_000,
  retires_at,
  price: price ? { input_per_mtok: price[0], output_per_mtok: price[1] } : null,
});

export const MOCK_MODELS: readonly ModelInfo[] = [
  model(OPUS, "Claude Opus 5.5", [4, 20]),
  model("claude-sonnet-5-5", "Claude Sonnet 5.5", [2, 10]),
  model(HAIKU, "Claude Haiku 5.5", [0.1, 0.5]),
  model("claude-fable-5-2", "Claude Fable 5.2", [8, 40]),
  model("claude-sonnet-4-5", "Claude Sonnet 4.5", null, "2026-11-30"),
];

export const VOICES = ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael", "bf_emma", "bf_isabella", "bm_george", "bm_lewis"];

export const INPUTS = [
  { name: "MacBook Pro Microphone", default: true },
  { name: "USB Audio Interface", default: false },
];
export const OUTPUTS = [
  { name: "MacBook Pro Speakers", default: true },
  { name: "Studio Headphones", default: false },
];

export const DEFAULT_VOICE: VoiceState = {
  installed: true,
  enabled: false,
  running: false,
  mic: "unknown",
  mic_detail: null,
  input_device: "",
  output_device: "",
  tts_voice: "af_heart",
  followup_s: 20,
  models_downloaded: true,
  models_size_bytes: SPEECH_BYTES,
};

export const DEFAULT_TIERS = { remember: "free", recall: "free", open_app: "free", open_url: "ask", shell: "ask" } as const;

export const TOOL_TEXT: Record<string, string> = {
  remember: "Writes a note into the memory vault.",
  recall: "Searches the memory vault.",
  open_app: "Opens an app on this Mac.",
  open_url: "Opens a link in the browser.",
  shell: "Runs a shell command.",
};

/** A small home folder: which folders each folder holds. */
export const FOLDERS: Record<string, string[]> = {
  "/": ["Applications", "Library", "System", "Users"],
  "/Users": ["Shared"],
  "~": [".config", "Desktop", "Documents", "Downloads", "Music", "Pictures", "Projects"],
  "~/Documents": ["Letters", "Notes", "Receipts"],
  "~/Projects": ["api-server", "data-tools", "my-app", "notes", "website"],
  "~/Projects/my-app": ["docs", "src", "tests"],
};

export function doctorChecks(keyStored: boolean, localDownloaded: boolean): DoctorCheck[] {
  const check = (id: string, title: string, needed_for: string, needed: boolean, met: boolean, detail: string, fix: string): DoctorCheck => ({
    id,
    title,
    needed_for,
    needed,
    status: met ? "ok" : needed ? "missing" : "optional",
    detail,
    fix: met ? "" : fix,
  });
  return [
    check("python", "Python", "running the assistant", true, true, "Python 3.13", ""),
    check("api_key", "API key", "talking to Claude", true, keyStored, keyStored ? "stored in the Keychain" : "no key stored", "add it in Settings, API key, or run `vision auth`"),
    check("window", "Window", "this window", true, true, "built", "`cd web && npm ci && npm run build`"),
    check("speech_models", "Speech models", "talking out loud", false, true, "downloaded, 2.0 GB", "download them (about 2 GB)"),
    check("local_model", "Local model", "answering when offline or over the cap", false, localDownloaded, localDownloaded ? "downloaded, 2.1 GB" : "not downloaded", "download it (2.1 GB)"),
    check("login", "Start at login", "keeping the assistant running after you log in", false, false, "the app is installed but does not open at login", "turn on Start at login in the app's menu bar item (or `vision setup`)"),
    check("github", "GitHub CLI", "project rooms that use GitHub", false, false, "installed, not signed in", "`gh auth login`"),
  ];
}

export const OLD_BACKUPS: readonly Backup[] = [
  { id: "20261110-091512-settings", created_at: 1794302112, level: "settings", files: ["config.toml"] },
  { id: "20261104-182040-house", created_at: 1793902840, level: "house", files: ["house.toml"] },
];
