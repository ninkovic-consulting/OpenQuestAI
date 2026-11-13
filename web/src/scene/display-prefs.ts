// The window's own display preferences: the scene's quality, the performance
// readout, and stepping back while the assistant works on this Mac. They
// belong to this window, not to the assistant, so they live in the page's
// localStorage rather than in the daemon's settings. The Mac app's web view
// keeps localStorage for the daemon's origin (http://127.0.0.1:7341) across
// restarts; where storage is unavailable the defaults apply.

import { DEFAULT_QUALITY, isQuality, type Quality } from "./quality";

export interface DisplayPrefs {
  quality: Quality;
  /** Show the performance readout. */
  readout: boolean;
  /** Lighten the scene while the assistant works on this Mac. */
  stepBack: boolean;
}

export const DEFAULT_PREFS: DisplayPrefs = { quality: DEFAULT_QUALITY, readout: false, stepBack: true };

export const STORAGE_KEY = "vision.display";

/** Reads stored preferences, keeping the default for anything missing or malformed. */
export function parsePrefs(raw: string | null): DisplayPrefs {
  if (raw === null) return { ...DEFAULT_PREFS };
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return { ...DEFAULT_PREFS };
  }
  const r = typeof v === "object" && v !== null ? (v as Record<string, unknown>) : {};
  return {
    quality: isQuality(r["quality"]) ? r["quality"] : DEFAULT_PREFS.quality,
    readout: typeof r["readout"] === "boolean" ? r["readout"] : DEFAULT_PREFS.readout,
    stepBack: typeof r["stepBack"] === "boolean" ? r["stepBack"] : DEFAULT_PREFS.stepBack,
  };
}

/** The minimal storage this needs; `localStorage` in the page. */
export interface PrefsStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export class DisplayPrefsStore {
  private prefs: DisplayPrefs;
  private readonly listeners = new Set<(p: DisplayPrefs) => void>();

  constructor(private readonly storage: PrefsStorage | null) {
    let raw: string | null = null;
    try {
      raw = storage?.getItem(STORAGE_KEY) ?? null;
    } catch {
      raw = null;
    }
    this.prefs = parsePrefs(raw);
  }

  get(): DisplayPrefs {
    return this.prefs;
  }

  set(change: Partial<DisplayPrefs>): void {
    this.prefs = { ...this.prefs, ...change };
    try {
      this.storage?.setItem(STORAGE_KEY, JSON.stringify(this.prefs));
    } catch {
      // Private mode or storage switched off: the choice holds until the window closes.
    }
    for (const l of this.listeners) l(this.prefs);
  }

  subscribe(listener: (p: DisplayPrefs) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

let shared: DisplayPrefsStore | null = null;

/** The page's one preferences store, made on first use. */
export function displayPrefs(): DisplayPrefsStore {
  if (!shared) {
    let storage: PrefsStorage | null = null;
    try {
      storage = typeof localStorage === "undefined" ? null : localStorage;
    } catch {
      storage = null;
    }
    shared = new DisplayPrefsStore(storage);
  }
  return shared;
}
