import { el } from "../../dom";
import { row, textInput } from "../bind";
import type { Group, SettingsContext } from "../context";
import { effortSlot } from "../effort-slot";
import { EFFORT_HELP } from "../effort";
import { block, note } from "../fields";
import { formatMonth } from "../format";
import { mountLocal } from "../local-control";
import { formatSpend } from "../../money";
import { mountModelPicker } from "../../pickers/model-picker";

const SOURCE_WORDS = {
  api: "Listed from Anthropic with your key.",
  cache: "Listed from Anthropic earlier; the list is kept for an hour.",
  built_in: "The built-in list: Anthropic could not be asked (no key, or offline).",
} as const;

/** A model's dropdown with its thinking level under it; a new model may move the level. */
function modelWithLevel(ctx: SettingsContext, field: string, label: string, note: string, levelField: string): HTMLElement[] {
  const model = ctx.draft[field] ?? "";
  const level = effortSlot(ctx, levelField, "Thinking level", model);
  const picker = mountModelPicker({
    source: ctx.models,
    value: model,
    own: null,
    onChange: (v) => {
      ctx.edit(field, v);
      level.follow(v);
    },
  });
  return [row(ctx, field, label, picker.root, { note }), level.root];
}

export const modelsGroup: Group = {
  id: "models",
  title: "Models",
  blurb: "Which Claude models the assistant talks and thinks with and how hard they think, working offline on a model of your own, and the monthly cap. A change of Claude model takes effect after a restart; the rest applies at once.",
  prefixes: ["models.", "budget."],
  render(ctx) {
    const s = ctx.settings;
    const root = el("div", "group-body");
    const source = note();
    void ctx.models().then((l) => (source.textContent = l ? SOURCE_WORDS[l.source] : "The list of models could not be loaded."));

    const claude = block(
      "Claude",
      ...modelWithLevel(ctx, "models.talk", "Talk model", "Answers every turn; also the host agent's model.", "models.talk_effort"),
      ...modelWithLevel(ctx, "models.heavy", "Heavy model", "Used when a question needs more thought.", "models.heavy_effort"),
      el("p", "field-note effort-help", EFFORT_HELP),
      source,
    );

    const cap = el("div", "money-input");
    cap.append(el("span", "unit", "$"), textInput(ctx, "budget.cap_usd", { inputMode: "decimal" }));
    const share = s.budget.cap_usd > 0 ? Math.round((s.budget.spent_usd / s.budget.cap_usd) * 100) : null;
    const budget = block(
      "Monthly cap",
      row(ctx, "budget.cap_usd", "Cap in dollars", cap, {
        note: `Past the cap the local model answers. A warning comes at ${Math.round(s.budget.warn_fraction * 100)}%.`,
      }),
      el("p", "spend", `${formatSpend(s.budget.spent_usd)} spent in ${formatMonth(s.budget.month)}${share === null ? "" : `, ${share}% of the cap`}.`),
    );
    const local = mountLocal(ctx);
    root.append(local.offline, claude, budget, local.local);
    return root;
  },
};
