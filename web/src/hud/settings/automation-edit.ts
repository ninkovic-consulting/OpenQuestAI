// The Automations group's logic, apart from the DOM: the form's state, the
// body or patch it sends, and each automation's state and last result in words.

import type { Automation, AutomationBody, AutomationLimits, AutomationPatch, RunResult, RunStatus } from "../../net/automation-types";
import type { Tone } from "./fields";
import { formatWhen } from "./format";
import { draftFrom, scheduleFrom, whenWords, type ScheduleDraft } from "./schedule-edit";

export interface AutomationEdit {
  name: string;
  instruction: string;
  speak: boolean;
  schedule: ScheduleDraft;
}

export type FormField = "name" | "instruction" | "schedule";
export interface FormError {
  field: FormField;
  message: string;
}

export function editFrom(a: Automation | null, now: Date): AutomationEdit {
  return { name: a?.name ?? "", instruction: a?.instruction ?? "", speak: a?.speak ?? true, schedule: draftFrom(a?.schedule ?? null, now) };
}

/** The body to create with, or every problem at once. */
export function bodyFrom(edit: AutomationEdit, limits: AutomationLimits, now: Date): { ok: true; body: AutomationBody } | { ok: false; errors: FormError[] } {
  const errors: FormError[] = [];
  const name = edit.name.trim().split(/\s+/).join(" ");
  const instruction = edit.instruction.trim();
  if (!name) errors.push({ field: "name", message: "Give it a name." });
  else if (name.length > limits.name_max) errors.push({ field: "name", message: `At most ${limits.name_max} characters.` });
  if (!instruction) errors.push({ field: "instruction", message: "Say what it should do, in words." });
  else if (instruction.length > limits.instruction_max) errors.push({ field: "instruction", message: `At most ${limits.instruction_max} characters; this has ${instruction.length}.` });
  const built = scheduleFrom(edit.schedule, now);
  if (!built.ok) errors.push({ field: "schedule", message: built.message });
  if (errors.length > 0 || !built.ok) return { ok: false, errors };
  return { ok: true, body: { name, instruction, schedule: built.schedule, speak: edit.speak } };
}

/** Only what changed, so an unchanged schedule keeps counting from where it was. */
export function patchFrom(before: Automation, body: AutomationBody): AutomationPatch {
  const patch: AutomationPatch = {};
  if (body.name !== before.name) patch.name = body.name;
  if (body.instruction !== before.instruction) patch.instruction = body.instruction;
  if (body.speak !== before.speak) patch.speak = body.speak;
  if (JSON.stringify(body.schedule) !== JSON.stringify(before.schedule)) patch.schedule = body.schedule;
  return patch;
}

/** Where an automation stands: running, paused, finished, or when it runs next. */
export function stateWords(a: Automation, now: number): { tone: Tone; text: string } {
  if (a.running) return { tone: "warn", text: "Running now" };
  if (a.paused) return { tone: "idle", text: "Paused" };
  if (a.finished || a.next_run === null) return { tone: "idle", text: "Finished; it ran once" };
  return { tone: "ok", text: `Next ${whenWords(a.next_run, now)}` };
}

const STATUS: Record<RunStatus, { tone: Tone; text: string }> = {
  ok: { tone: "ok", text: "Done" },
  failed: { tone: "bad", text: "Failed" },
  interrupted: { tone: "warn", text: "Interrupted" },
  needed_approval: { tone: "warn", text: "Needed your approval; nothing that asks first was done" },
  missed: { tone: "idle", text: "Missed" },
};

/** "Done, 12 Nov 2026, 09:00 (run now): It is sunny…", or null before the first run. */
export function resultWords(result: RunResult | undefined): { tone: Tone; text: string } | null {
  if (!result) return null;
  const status = STATUS[result.status];
  const how = result.trigger === "manual" ? " (run now)" : result.trigger === "catch_up" ? " (made up after a miss)" : "";
  const reply = result.reply ? `: ${result.reply}` : "";
  return { tone: status.tone, text: `${status.text}, ${formatWhen(result.started_at)}${how}${reply}` };
}

/** The count against the limit, for the head of the list. */
export function countWords(count: number, limits: AutomationLimits): string {
  if (count === 0) return "No automations yet.";
  return `${count} of at most ${limits.max_automations} automation${limits.max_automations === 1 ? "" : "s"}.`;
}
