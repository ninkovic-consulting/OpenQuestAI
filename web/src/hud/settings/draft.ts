// The edits on the settings screen, apart from the DOM: a flat draft keyed by
// the daemon's dotted field names, what changed against the saved settings,
// the PATCH body with only those fields, and where the daemon's errors go.

import type { FieldError, Json, PatchAnswer, Settings, SettingsPatch } from "../../net/settings-types";

/** Every editable value as text, keyed like `budget.cap_usd` or `agents.maker.name`. */
export type Draft = Record<string, string>;

/** Fields sent as numbers. */
const NUMERIC: ReadonlySet<string> = new Set(["budget.cap_usd", "voice.followup_s"]);

/** Fields that only a restart applies; the screen marks them. */
export const RESTART_FIELDS: ReadonlySet<string> = new Set(["models.talk", "models.heavy", "models.local"]);

const LABELS: Record<string, string> = {
  "assistant.name": "assistant's name",
  "models.talk": "talk model",
  "models.heavy": "heavy model",
  "models.local": "local model",
  "budget.cap_usd": "monthly cap",
  "voice.input_device": "microphone",
  "voice.output_device": "speakers",
  "voice.tts_voice": "speaking voice",
  "voice.followup_s": "follow-up window",
  "setup.completed": "setup",
  key: "API key",
};

/** The draft the saved settings make. The host agent has none: it follows the assistant. */
export function draftFrom(s: Settings): Draft {
  const d: Draft = {
    "assistant.name": s.assistant.name,
    "models.talk": s.models.talk,
    "models.heavy": s.models.heavy,
    "models.local": s.models.local.model,
    "budget.cap_usd": String(s.budget.cap_usd),
    "voice.input_device": s.voice.input_device,
    "voice.output_device": s.voice.output_device,
    "voice.tts_voice": s.voice.tts_voice,
    "voice.followup_s": String(s.voice.followup_s),
  };
  for (const a of s.agents) {
    if (a.is_host) continue;
    d[`agents.${a.id}.name`] = a.name;
    d[`agents.${a.id}.model`] = a.model;
  }
  for (const [tool, tier] of Object.entries(s.gate.tiers)) d[`gate.tiers.${tool}`] = tier;
  return d;
}

const inGroup = (field: string, prefixes: readonly string[]): boolean => prefixes.some((p) => field.startsWith(p));

function same(field: string, a: string, b: string): boolean {
  if (NUMERIC.has(field)) {
    const x = Number(a.trim());
    const y = Number(b.trim());
    if (a.trim() !== "" && b.trim() !== "" && Number.isFinite(x) && Number.isFinite(y)) return x === y;
  }
  return field.endsWith(".name") ? a.trim() === b.trim() : a === b;
}

/** The fields under these prefixes whose draft differs from the saved value. */
export function changedFields(saved: Draft, draft: Draft, prefixes: readonly string[]): string[] {
  return Object.keys(draft).filter((f) => inGroup(f, prefixes) && saved[f] !== undefined && !same(f, saved[f] ?? "", draft[f] ?? ""));
}

/**
 * The PATCH body for the changed fields under these prefixes, nested the way
 * the daemon reads it. A number field that is not a number is not sent; it
 * comes back as an error for its field.
 */
export function buildPatch(saved: Draft, draft: Draft, prefixes: readonly string[]): { patch: SettingsPatch; errors: FieldError[] } {
  const patch: SettingsPatch = {};
  const errors: FieldError[] = [];
  for (const field of changedFields(saved, draft, prefixes)) {
    const text = draft[field] ?? "";
    let value: Json = field.endsWith(".name") ? text.trim() : text;
    if (NUMERIC.has(field)) {
      const n = Number(text.trim());
      if (text.trim() === "" || !Number.isFinite(n)) {
        errors.push({ field, message: "Enter a number." });
        continue;
      }
      value = n;
    }
    setPath(patch, field, value);
  }
  return { patch, errors };
}

function setPath(patch: SettingsPatch, field: string, value: Json): void {
  const [section, ...rest] = field.split(".");
  if (!section || rest.length === 0) return;
  const top = (patch[section] ??= {});
  let node: Record<string, Json> = top;
  for (const key of rest.slice(0, -1)) {
    const next = node[key];
    const child: Record<string, Json> = typeof next === "object" && next !== null && !Array.isArray(next) ? next : {};
    node[key] = child;
    node = child;
  }
  node[rest[rest.length - 1] ?? ""] = value;
}

/** The daemon's errors by field; those that name no field shown here go under `general`. */
export function placeErrors(errors: readonly FieldError[], shown: readonly string[]): { byField: Map<string, string>; general: string[] } {
  const byField = new Map<string, string>();
  const general: string[] = [];
  for (const e of errors) {
    if (shown.includes(e.field)) byField.set(e.field, byField.has(e.field) ? `${byField.get(e.field)} ${e.message}` : e.message);
    else general.push(e.message);
  }
  return { byField, general };
}

/** A field's name in a sentence: "talk model", "Tink's model", "the Shell tier". */
export function fieldLabel(field: string, s: Settings): string {
  const known = LABELS[field];
  if (known) return known;
  const agent = /^agents\.([^.]+)\.(name|model)$/.exec(field);
  if (agent) {
    const name = s.agents.find((a) => a.id === agent[1])?.name ?? agent[1];
    return `${name}'s ${agent[2]}`;
  }
  const tier = /^gate\.tiers\.(.+)$/.exec(field);
  if (tier) return `asking first for ${s.gate.tools.find((t) => t.id === tier[1])?.title ?? tier[1]}`;
  return field;
}

const list = (fields: readonly string[], s: Settings): string => fields.map((f) => fieldLabel(f, s)).join(", ");

/** What a save did, plainly: what applies now, what waits for a restart. */
export function saveSummary(answer: PatchAnswer): string {
  if (answer.changed.length === 0) return "Nothing changed.";
  const s = answer.settings;
  const parts: string[] = [];
  if (answer.applied.length > 0) parts.push(`Applied now: ${list(answer.applied, s)}.`);
  if (answer.restart.length > 0) parts.push(`Takes effect after a restart: ${list(answer.restart, s)}.`);
  return `Saved. ${parts.join(" ")}`;
}

/** The persistent line when saved changes wait for a restart; null when none do. */
export function restartLine(s: Settings): string | null {
  if (s.restart_pending.length === 0) return null;
  return `Restart needed for: ${list(s.restart_pending, s)}.`;
}

/**
 * The draft after new saved settings arrive: fields under `reset` and fields
 * that were not edited take the new values; other edits are kept.
 */
export function rebase(oldSaved: Draft, newSaved: Draft, draft: Draft, reset: readonly string[]): Draft {
  const next: Draft = { ...newSaved };
  for (const [field, value] of Object.entries(draft)) {
    const edited = oldSaved[field] !== undefined && value !== oldSaved[field];
    if (edited && !inGroup(field, reset) && newSaved[field] !== undefined) next[field] = value;
  }
  return next;
}
