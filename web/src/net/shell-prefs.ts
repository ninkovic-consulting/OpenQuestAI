// The Mac app's own preferences for the widget and the global shortcuts, as
// its bridge answers `widgetPrefs()` and `setWidgetPrefs(changes)`. The shell
// stores them; the page only shows and changes them.

/** What the app shows when it opens: the house, only the widget, or only its menu bar item. */
export type OpenWith = "house" | "widget" | "menubar";

export interface ShortcutOption {
  id: string;
  label: string;
}

/** Whether a shortcut is in place, and if not (or not quite), why, in the owner's words. */
export interface ShortcutStatus {
  registered: boolean;
  problem: string | null;
}

export interface WidgetPrefs {
  /** The widget shows by itself whenever the app runs. */
  widget: boolean;
  /** What the app shows when it opens. */
  openWith: OpenWith;
  /** The summon shortcut's id, or "off". */
  summon: string;
  /** The push-to-talk shortcut's id, or "off". */
  talk: string;
  /** The widget is on screen now. */
  shown: boolean;
  shortcuts: ShortcutOption[];
  status: { summon: ShortcutStatus; talk: ShortcutStatus };
}

export type WidgetPrefsChange = Partial<Pick<WidgetPrefs, "widget" | "openWith" | "summon" | "talk">>;

export const SHORTCUT_OFF = "off";

const record = (v: unknown): Record<string, unknown> | null => (typeof v === "object" && v !== null ? (v as Record<string, unknown>) : null);

function asStatus(v: unknown): ShortcutStatus {
  const r = record(v);
  const problem = r?.["problem"];
  return { registered: r?.["registered"] === true, problem: typeof problem === "string" && problem !== "" ? problem : null };
}

function asOptions(v: unknown): ShortcutOption[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((o) => {
    const r = record(o);
    const id = r?.["id"];
    const label = r?.["label"];
    return typeof id === "string" && typeof label === "string" ? [{ id, label }] : [];
  });
}

/** Narrows the shell's answer; null when it is not one. */
export function asWidgetPrefs(v: unknown): WidgetPrefs | null {
  const r = record(v);
  if (!r) return null;
  const { widget, openWith, summon, talk, shown } = r;
  if (typeof widget !== "boolean" || typeof summon !== "string" || typeof talk !== "string") return null;
  if (openWith !== "house" && openWith !== "widget" && openWith !== "menubar") return null;
  const status = record(r["status"]);
  return {
    widget,
    openWith,
    summon,
    talk,
    shown: shown === true,
    shortcuts: asOptions(r["shortcuts"]),
    status: { summon: asStatus(status?.["summon"]), talk: asStatus(status?.["talk"]) },
  };
}

/** The line under a shortcut's choice: off, ready, ready with a warning, or why it does not work. */
export function shortcutLine(id: string, s: ShortcutStatus): { tone: "ok" | "warn" | "bad" | "idle"; text: string } {
  if (id === SHORTCUT_OFF) return { tone: "idle", text: "Off." };
  if (!s.registered) return { tone: "bad", text: s.problem ?? "It could not be set up." };
  if (s.problem) return { tone: "warn", text: s.problem };
  return { tone: "ok", text: "Ready in every app." };
}
