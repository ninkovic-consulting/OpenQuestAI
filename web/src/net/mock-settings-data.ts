// Mock mode's made-up answers for the settings screen: models with prices,
// audio devices, a folder tree, the doctor's checks and two old backups.

import { mockLevels } from "./mock-effort";
import type { Backup, DoctorCheck, ModelInfo, VoiceState } from "./settings-types";

export const HAIKU = "claude-haiku-5-5";
export const OPUS = "claude-opus-5-5";
export { DEFAULT_REPO as LOCAL_MODEL } from "./mock-local-data";
export const SPEECH_BYTES = 1_960_000_000;
/** The data folder, as the daemon names it in the settings answer. */
export const MOCK_HOME = "/Users/you/Library/Application Support/Vision";
/** The speech models' repo, as the delete-all preview lists it. */
export const SPEECH_REPO = "mlx-community/whisper-large-v3-turbo";

const model = (id: string, display_name: string, price: [number, number] | null, retires_at: string | null = null): ModelInfo => ({
  id,
  display_name,
  max_input_tokens: 1_000_000,
  max_tokens: 128_000,
  retires_at,
  price: price ? { input_per_mtok: price[0], output_per_mtok: price[1] } : null,
  efforts: mockLevels(id),
});

export const MOCK_MODELS: readonly ModelInfo[] = [
  model(OPUS, "Claude Opus 5.5", [4, 20]),
  model("claude-sonnet-5-5", "Claude Sonnet 5.5", [2, 10]),
  model(HAIKU, "Claude Haiku 5.5", [0.1, 0.5]),
  model("claude-fable-5-2", "Claude Fable 5.2", [8, 40]),
  model("claude-opus-4-6", "Claude Opus 4.6", [5, 25]),
  model("claude-sonnet-4-5", "Claude Sonnet 4.5", null, "2026-11-30"),
  model("claude-haiku-4-5", "Claude Haiku 4.5", [1, 5]),
];

export const VOICES = ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael", "bf_emma", "bf_isabella", "bm_george", "bm_lewis"];

export const INPUTS = [
  { name: "MacBook Pro Microphone", default: true },
  { name: "USB Audio Interface", default: false },
  { name: "Insta360 Link 2C", default: false },
  { name: "Sam's AirPods Pro", default: false, bluetooth: true },
];
/** A webcam in privacy mode: it opens, but sends only silence. */
export const SILENT_INPUT = "Insta360 Link 2C";
export const OUTPUTS = [
  { name: "MacBook Pro Speakers", default: true },
  { name: "Studio Headphones", default: false },
  { name: "Sam's AirPods Pro", default: false, bluetooth: true },
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
  listen: "hold",
  listening: "wake",
  models_downloaded: true,
  models_size_bytes: SPEECH_BYTES,
};

export const DEFAULT_TIERS = {
  remember: "free",
  recall: "free",
  open_app: "free",
  open_url: "ask",
  shell: "ask",
  run_program: "ask",
  create_automation: "free",
  list_automations: "free",
  update_automation: "free",
  pause_automation: "free",
  resume_automation: "free",
  run_automation: "free",
  delete_automation: "ask",
} as const;

export const TOOL_TEXT: Record<string, string> = {
  remember: "Writes a note into the memory vault.",
  recall: "Searches the memory vault.",
  open_app: "Opens an app on this Mac.",
  open_url: "Opens a link in the browser.",
  shell: "Runs a shell command on this Mac, after asking you unless you make it free.",
  run_program: "Runs one of the room's programs in one of its project folders, after asking you unless you make it free.",
  create_automation: "Sets up an instruction to carry out at set times.",
  list_automations: "Reads the automations, their next runs and last results.",
  update_automation: "Changes an automation's name, schedule, instruction or voice.",
  pause_automation: "Stops an automation from running until it is resumed.",
  resume_automation: "Lets a paused automation run on its schedule again.",
  run_automation: "Runs an automation once, now, outside its schedule.",
  delete_automation: "Removes an automation and its results.",
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
