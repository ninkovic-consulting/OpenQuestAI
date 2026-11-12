// The form to create or edit an automation, with the schedule builder: the
// kind as a row of choices, then only the fields that kind needs. A raw cron
// line appears only when Cron is chosen.

import { WEEKDAYS, type Automation, type AutomationLimits, type Weekday } from "../../net/automation-types";
import { el, setText } from "../dom";
import { bodyFrom, editFrom, patchFrom, type FormError, type FormField } from "./automation-edit";
import type { SettingsContext } from "./context";
import { button, fieldRow, note, segmented } from "./fields";
import { KIND_LABELS, scheduleFrom, scheduleWords, type ScheduleDraft } from "./schedule-edit";

const DAY_LABELS: Record<Weekday, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

export interface FormOptions {
  ctx: SettingsContext;
  limits: AutomationLimits;
  /** The automation to edit, or null for a new one. */
  editing: Automation | null;
  /** Saved: back to the list, with this line to show. */
  done(message: string): void;
  cancel(): void;
}

export function automationForm(o: FormOptions): HTMLElement {
  const edit = editFrom(o.editing, new Date());
  const card = el("section", "automation-editor");
  const head = el("div", "card-head");
  head.append(el("h4", "card-title", o.editing ? `Edit ${o.editing.name}` : "New automation"));

  const name = el("input");
  name.maxLength = o.limits.name_max;
  name.placeholder = "Morning briefing";
  name.value = edit.name;
  name.addEventListener("input", () => (edit.name = name.value));

  const instruction = el("textarea", "instruction");
  instruction.rows = 3;
  instruction.maxLength = o.limits.instruction_max;
  instruction.placeholder = "Tell me the weather and the first things in my calendar.";
  instruction.value = edit.instruction;
  instruction.addEventListener("input", () => (edit.instruction = instruction.value));

  const preview = el("p", "schedule-preview");
  const fields = el("div", "schedule-fields");
  const refresh = (): void => {
    const built = scheduleFrom(edit.schedule, new Date());
    setText(preview, built.ok ? `Runs ${scheduleWords(built.schedule)}, in the Mac's local time.` : built.message);
    preview.classList.toggle("is-bad", !built.ok);
  };
  const drawFields = (): void => {
    fields.replaceChildren(...scheduleFields(edit.schedule, refresh));
    refresh();
  };
  const kinds = segmented(
    "When it runs",
    (Object.keys(KIND_LABELS) as ScheduleDraft["kind"][]).map((k) => ({ value: k, label: KIND_LABELS[k] })),
    edit.schedule.kind,
    (v) => {
      edit.schedule.kind = v as ScheduleDraft["kind"];
      drawFields();
    },
  );
  drawFields();

  const voice = segmented(
    "Result",
    [
      { value: "spoken", label: "Spoken" },
      { value: "shown", label: "Shown only" },
    ],
    edit.speak ? "spoken" : "shown",
    (v) => (edit.speak = v === "spoken"),
  );

  const rows: Record<FormField, HTMLElement> = {
    name: fieldRow("Name", name),
    instruction: fieldRow("Instruction", instruction, { note: `What the assistant does when it runs, in plain words. At most ${o.limits.instruction_max} characters.` }),
    schedule: fieldRow("When", kinds),
  };
  const scheduleRow = rows.schedule;
  scheduleRow.insertBefore(fields, scheduleRow.querySelector(".field-error"));
  scheduleRow.insertBefore(preview, scheduleRow.querySelector(".field-error"));

  const result = note();
  const save = button(o.editing ? "Save changes" : "Create", "primary");
  const cancel = button("Cancel");
  cancel.addEventListener("click", o.cancel);
  save.addEventListener("click", () => {
    const built = bodyFrom(edit, o.limits, new Date());
    showErrors(rows, built.ok ? [] : built.errors);
    if (!built.ok) {
      setText(result, "Some fields need fixing first.");
      return;
    }
    const before = o.editing;
    save.disabled = true;
    setText(result, "Saving…");
    const sent = before ? o.ctx.automations.update(before.id, patchFrom(before, built.body)) : o.ctx.automations.create(built.body);
    void sent.then((r) => {
      save.disabled = false;
      if (r.ok) o.done(before ? `Saved ${r.value.name}.` : `Created ${r.value.name}: ${scheduleWords(r.value.schedule)}.`);
      else setText(result, r.message);
    });
  });

  const actions = el("div", "row-actions");
  actions.append(save, cancel);
  card.append(
    head,
    rows.name,
    rows.instruction,
    rows.schedule,
    fieldRow("Result", voice, { note: "Spoken aloud when it runs, or only shown in the window." }),
    actions,
    result,
  );
  return card;
}

/** Errors beside their fields; the schedule's own shows in its live preview line. */
function showErrors(rows: Record<FormField, HTMLElement>, errors: readonly FormError[]): void {
  for (const field of ["name", "instruction"] as const) {
    const row = rows[field];
    const slot = row.querySelector<HTMLElement>(".field-error");
    if (!slot) continue;
    const message = errors.find((e) => e.field === field)?.message ?? "";
    slot.textContent = message;
    slot.hidden = message === "";
  }
}

/** The inputs one kind of schedule needs; each edit writes the draft and calls `changed`. */
function scheduleFields(d: ScheduleDraft, changed: () => void): HTMLElement[] {
  const input = (type: string, value: string, label: string, write: (v: string) => void, attrs: Partial<HTMLInputElement> = {}): HTMLInputElement => {
    const i = el("input");
    i.type = type;
    i.value = value;
    i.setAttribute("aria-label", label);
    Object.assign(i, attrs);
    i.addEventListener("input", () => {
      write(i.value);
      changed();
    });
    return i;
  };
  const time = (): HTMLInputElement => input("time", d.time, "Time", (v) => (d.time = v));
  const line = (...parts: (HTMLElement | string)[]): HTMLElement => {
    const row = el("div", "schedule-line");
    row.append(...parts.map((p) => (typeof p === "string" ? el("span", "joiner", p) : p)));
    return row;
  };
  switch (d.kind) {
    case "once":
      return [line("On", input("date", d.date, "Date", (v) => (d.date = v)), "at", time())];
    case "daily":
      return [line("Every day at", time())];
    case "weekly":
      return [dayToggles(d, changed), line("at", time())];
    case "interval": {
      const unit = segmented(
        "Unit",
        [
          { value: "minutes", label: "Minutes" },
          { value: "hours", label: "Hours" },
        ],
        d.unit,
        (v) => {
          d.unit = v === "hours" ? "hours" : "minutes";
          changed();
        },
      );
      return [line("Every", input("number", d.every, "Every", (v) => (d.every = v), { min: "1", step: "1", inputMode: "numeric" }), unit)];
    }
    case "cron": {
      const expr = input("text", d.expr, "Cron line", (v) => (d.expr = v), { spellcheck: false, autocomplete: "off", placeholder: "0 9 * * 1-5" });
      expr.classList.add("cron-input");
      return [line(expr), el("p", "field-note", "Five fields: minute, hour, day of month, month, day of week. 0 9 * * 1-5 is 09:00 on weekdays.")];
    }
  }
}

function dayToggles(d: ScheduleDraft, changed: () => void): HTMLElement {
  const group = el("div", "day-toggles");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", "Days");
  for (const day of WEEKDAYS) {
    const b = el("button", "segment caps", DAY_LABELS[day]);
    b.type = "button";
    b.setAttribute("aria-pressed", String(d.days.includes(day)));
    b.addEventListener("click", () => {
      d.days = d.days.includes(day) ? d.days.filter((x) => x !== day) : [...d.days, day];
      b.setAttribute("aria-pressed", String(d.days.includes(day)));
      changed();
    });
    group.append(b);
  }
  return group;
}
