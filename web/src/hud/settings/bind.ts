// Controls bound to one draft field: they show the draft's value and write
// every edit back to it.

import { el } from "../dom";
import { mountModelPicker } from "../pickers/model-picker";
import type { SettingsContext } from "./context";
import { fieldRow, type FieldOptions } from "./fields";
import { RESTART_FIELDS } from "./draft";

export interface Choice {
  value: string;
  label: string;
}

export function textInput(ctx: SettingsContext, field: string, attrs: Partial<Pick<HTMLInputElement, "maxLength" | "inputMode" | "placeholder">> = {}): HTMLInputElement {
  const input = el("input");
  input.type = "text";
  input.autocomplete = "off";
  input.spellcheck = false;
  Object.assign(input, attrs);
  input.value = ctx.draft[field] ?? "";
  input.addEventListener("input", () => ctx.edit(field, input.value));
  return input;
}

export function selectInput(ctx: SettingsContext, field: string, choices: readonly Choice[]): HTMLSelectElement {
  const select = el("select");
  const value = ctx.draft[field] ?? "";
  const all = choices.some((c) => c.value === value) ? choices : [...choices, { value, label: value }];
  select.append(
    ...all.map((c) => {
      const option = el("option", "", c.label);
      option.value = c.value;
      return option;
    }),
  );
  select.value = value;
  select.addEventListener("change", () => ctx.edit(field, select.value));
  return select;
}

/** A model dropdown for a field that must name a model (no "agent's own" choice). */
export function modelInput(ctx: SettingsContext, field: string): HTMLElement {
  return mountModelPicker({ source: ctx.models, value: ctx.draft[field] ?? "", own: null, onChange: (v) => ctx.edit(field, v) }).root;
}

/** A labelled row for a draft field, with its restart note and its last error. */
export function row(ctx: SettingsContext, field: string, label: string, control: HTMLElement, opts: Omit<FieldOptions, "error" | "restart"> = {}): HTMLElement {
  return fieldRow(label, control, { ...opts, restart: RESTART_FIELDS.has(field), error: ctx.errorFor(field) });
}
