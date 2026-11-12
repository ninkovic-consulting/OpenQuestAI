// A model dropdown from `GET /api/models`, each option with its price per
// million tokens. Used by the add-room form, the Rooms and Agents groups,
// the Models group and the wizard.

import type { SettingsApi } from "../../net/settings-api";
import type { ModelInfo, ModelListing } from "../../net/settings-types";
import { el } from "../dom";
import { formatDay, formatPrice, formatTokens, modelOption } from "../settings/format";

/** The listing, asked for once and kept; a failed answer is asked for again next time. */
export type ModelSource = () => Promise<ModelListing | null>;

export function modelSource(api: SettingsApi): ModelSource {
  let kept: Promise<ModelListing | null> | null = null;
  return () => {
    kept ??= api.models().then((r) => {
      if (!r.ok) kept = null;
      return r.ok ? r.value : null;
    });
    return kept;
  };
}

export interface Choice {
  value: string;
  label: string;
}

/** The choice that sends no model: the room or agent keeps its own. */
export const OWN_MODEL = "The agent's own model";

/**
 * The dropdown's options: optionally "the agent's own model" first (value ""),
 * then every listed model; a current id the list lacks stays choosable.
 */
export function modelChoices(listing: ModelListing | null, current: string, own: string | null): Choice[] {
  const choices: Choice[] = own === null ? [] : [{ value: "", label: own }];
  const models = listing?.models ?? [];
  choices.push(...models.map((m) => ({ value: m.id, label: modelOption(m) })));
  if (current !== "" && !models.some((m) => m.id === current)) choices.push({ value: current, label: `${current} · not in the list` });
  return choices;
}

/** The line under the dropdown about the chosen model. */
export function modelDetail(model: ModelInfo | undefined, ownNote: string): string {
  if (!model) return ownNote;
  const context = model.max_input_tokens ? ` · ${formatTokens(model.max_input_tokens)} tokens of context` : "";
  const retires = model.retires_at ? ` · retires ${formatDay(model.retires_at)}` : "";
  return `${formatPrice(model.price)}${context}${retires}`;
}

export interface ModelPicker {
  root: HTMLElement;
  select: HTMLSelectElement;
  value(): string;
  set(value: string): void;
}

export interface ModelPickerOptions {
  source: ModelSource;
  value: string;
  /** Offer the agent's own model as the first choice, with this note under it; null offers none. */
  own: { label: string; note: string } | null;
  onChange?: (value: string) => void;
}

export function mountModelPicker(opts: ModelPickerOptions): ModelPicker {
  const root = el("div", "model-picker");
  const select = el("select");
  const detail = el("p", "field-note");
  root.append(select, detail);
  let listing: ModelListing | null = null;
  let current = opts.value;

  const render = (): void => {
    select.replaceChildren(
      ...modelChoices(listing, current, opts.own?.label ?? null).map((c) => {
        const option = el("option", "", c.label);
        option.value = c.value;
        return option;
      }),
    );
    select.value = current;
    renderDetail();
  };
  const renderDetail = (): void => {
    detail.textContent = modelDetail(
      listing?.models.find((m) => m.id === select.value),
      select.value === "" ? (opts.own?.note ?? "") : listing ? "Not in the list from Anthropic." : "Loading the models…",
    );
  };

  select.addEventListener("change", () => {
    current = select.value;
    renderDetail();
    opts.onChange?.(current);
  });
  render();
  void opts.source().then((l) => {
    listing = l;
    render();
  });
  return {
    root,
    select,
    value: () => current,
    set(value: string): void {
      current = value;
      render();
    },
  };
}
