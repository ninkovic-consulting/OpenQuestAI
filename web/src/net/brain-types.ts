// What the window knows of the brains: offline mode and the local model
// (`brain.mode`, `GET /api/local-models`) and the thinking levels. Mirrors
// vision/core/events.py, vision/brains/catalog.py and vision/settings/local_models.py.

/** Thinking effort, lowest first. */
export const EFFORTS: readonly string[] = ["low", "medium", "high", "xhigh", "max"];

/** `brain.mode` and `mode` in `GET /api/state`. `local_tools` is null until the model has loaded. */
export interface BrainMode {
  offline: boolean;
  answering: "claude" | "local" | "fake";
  local_backend: string;
  local_model: string;
  local_tools: boolean | null;
  /** Whether the local model can read images; an older daemon leaves it out, which counts as no. */
  local_images?: boolean;
  /** The in-process model: not in memory, being loaded, in memory, or its load failed. A server's model says `unloaded`. */
  local_state?: LocalLoad;
  /** The memory the loaded weights hold. */
  local_bytes?: number | null;
  /** The memory the prompts kept for the next turn hold. */
  local_cache_bytes?: number;
  /** While a long prompt is read before the first word: tokens read, tokens to read. */
  local_reading?: readonly [number, number] | null;
  /** Why the last load failed, in words for the owner. */
  local_problem?: string | null;
}

export type LocalLoad = "unloaded" | "loading" | "ready" | "failed";

export type Fit = "comfortable" | "tight" | "too_big";
export type DownloadState = "idle" | "running" | "done" | "failed";

export interface LocalDownload {
  state: DownloadState;
  done_bytes: number;
  total_bytes: number | null;
  message: string | null;
}

/** One catalog entry against this Mac. `on_disk_bytes` is null until the model is downloaded. */
export interface LocalModelRow {
  id: string;
  title: string;
  good_at: string;
  kind: string;
  params_b: number;
  size_bytes: number;
  memory_gb: number;
  context: number;
  tools: boolean;
  tools_recommended: boolean;
  license: string;
  fit: Fit;
  on_disk_bytes: number | null;
  download: LocalDownload;
}

/** The model in use when it is not in the catalog (typed by hand). */
export interface CustomModel {
  id: string;
  on_disk_bytes: number | null;
  download: LocalDownload;
}

export interface LocalChosen {
  backend: string;
  model: string;
  server: string;
  tools: boolean | null;
}

/** `GET /api/local-models`. */
export interface LocalListing {
  taken: string;
  memory_bytes: number;
  recommended: string | null;
  models: LocalModelRow[];
  chosen: LocalChosen;
  custom: CustomModel | null;
  offline: boolean;
}

/** `POST /api/local-models/delete`: the listing and what was freed. */
export interface DeleteAnswer extends LocalListing {
  deleted: string;
  freed_bytes: number;
}

/** `POST /api/local-models/server/test`. */
export interface ServerTest {
  ok: boolean;
  models: string[];
  message: string;
}
