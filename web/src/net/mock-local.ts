// Mock mode's local models: what is on the pretend Mac's disk, downloads that
// take a while, and a pretend local server. Rules as in the daemon
// (vision/settings/local_models.py): a download cannot be cancelled, the model
// offline mode uses cannot be deleted, a server is tested at its address.

import type { LocalDownload, LocalListing, ServerTest } from "./brain-types";
import { CATALOG, CUSTOM_BYTES, fitOf, MOCK_MEMORY, MOCK_SERVER, MOCK_SERVER_MODELS, recommendedOf } from "./mock-local-data";

/** How fast the pretend network is. */
const BYTES_PER_S = 200_000_000;
const FAIL_AFTER_MS = 2500;
const FAILED =
  "The download stopped (the connection was reset by the server). Check the network, the free disk space and the repo's name, then try again.";
/** The model already here, and one whose last download failed. */
const ON_DISK_AT_START = ["mlx-community/Qwen3-8B-4bit"];
const FAILED_AT_START = "mlx-community/Qwen3.5-4B-MLX-4bit";

interface Disk {
  /** When the running download began. */
  started: number | null;
  done: boolean;
  failed: string | null;
}

/** The choice the listing is read against. */
export interface Chosen {
  backend: string;
  model: string;
  server: string;
  offline: boolean;
}

export class MockLocal {
  private readonly disk = new Map<string, Disk>();

  constructor() {
    for (const repo of ON_DISK_AT_START) this.disk.set(repo, { started: null, done: true, failed: null });
    this.disk.set(FAILED_AT_START, { started: null, done: false, failed: FAILED });
  }

  private sizeOf(repo: string): number {
    return CATALOG.find((m) => m.id === repo)?.size_bytes ?? CUSTOM_BYTES;
  }

  /** A repo that cannot be found on the Hub fails soon after it starts. */
  private static missing(repo: string): boolean {
    return repo.includes("missing");
  }

  private tick(repo: string): Disk {
    const d = this.disk.get(repo) ?? { started: null, done: false, failed: null };
    if (d.started !== null) {
      const ran = Date.now() - d.started;
      if (MockLocal.missing(repo) && ran >= FAIL_AFTER_MS) Object.assign(d, { started: null, failed: FAILED });
      else if (ran * (BYTES_PER_S / 1000) >= this.sizeOf(repo)) Object.assign(d, { started: null, done: true });
    }
    this.disk.set(repo, d);
    return d;
  }

  onDisk(repo: string): boolean {
    return this.tick(repo).done;
  }

  /** What a repo takes on disk, null when it is not here. */
  bytes(repo: string): number | null {
    return this.onDisk(repo) ? this.sizeOf(repo) : null;
  }

  download(repo: string): LocalDownload {
    const d = this.tick(repo);
    const total = this.sizeOf(repo);
    if (d.done) return { state: "done", done_bytes: total, total_bytes: total, message: null };
    if (d.started !== null) return { state: "running", done_bytes: Math.min(total, Math.round(((Date.now() - d.started) / 1000) * BYTES_PER_S)), total_bytes: total, message: null };
    if (d.failed) return { state: "failed", done_bytes: Math.round(total * 0.4), total_bytes: total, message: d.failed };
    return { state: "idle", done_bytes: 0, total_bytes: total, message: null };
  }

  /** Start fetching a repo unless it is running or here. */
  start(repo: string): void {
    const d = this.tick(repo);
    if (d.done || d.started !== null) return;
    this.disk.set(repo, { started: Date.now(), done: false, failed: null });
  }

  /** Remove a repo; the bytes freed. */
  remove(repo: string): number {
    const freed = this.bytes(repo) ?? 0;
    this.disk.delete(repo);
    return freed;
  }

  /** Whether a model can use tools: the catalog knows, a model typed by hand is unknown until loaded. */
  static tools(repo: string): boolean | null {
    return CATALOG.find((m) => m.id === repo)?.tools ?? null;
  }

  listing(chosen: Chosen): LocalListing {
    const custom = chosen.backend === "mlx" && !CATALOG.some((m) => m.id === chosen.model) ? chosen.model : null;
    return {
      taken: "2026-11-13",
      memory_bytes: MOCK_MEMORY,
      recommended: recommendedOf(MOCK_MEMORY),
      models: CATALOG.map((m) => ({ ...m, fit: fitOf(m, MOCK_MEMORY), on_disk_bytes: this.bytes(m.id), download: this.download(m.id) })),
      chosen: { backend: chosen.backend, model: chosen.model, server: chosen.server, tools: chosen.backend === "mlx" ? MockLocal.tools(chosen.model) : true },
      custom: custom === null ? null : { id: custom, on_disk_bytes: this.bytes(custom), download: this.download(custom) },
      offline: chosen.offline,
    };
  }

  /** The pretend server answers at LM Studio's address and no other. */
  static testServer(server: string): ServerTest {
    const url = server.trim().replace(/\/$/, "");
    if (url === MOCK_SERVER) return { ok: true, models: [...MOCK_SERVER_MODELS], message: `The server answers and has ${MOCK_SERVER_MODELS.length} models.` };
    return { ok: false, models: [], message: `Nothing answered at ${url}. Is the server running, and is the address the one it shows, ending in /v1?` };
  }
}
