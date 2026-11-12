import { el } from "../../dom";
import { modelInput, row, textInput } from "../bind";
import type { Group } from "../context";
import { downloadControl } from "../download-control";
import { block, note } from "../fields";
import { formatSpend } from "../../money";
import { formatMonth } from "../format";

const SOURCE_WORDS = {
  api: "Listed from Anthropic with your key.",
  cache: "Listed from Anthropic earlier; the list is kept for an hour.",
  built_in: "The built-in list: Anthropic could not be asked (no key, or offline).",
} as const;

export const modelsGroup: Group = {
  id: "models",
  title: "Models",
  blurb: "Which Claude models the assistant talks and thinks with, the local fallback, and the monthly cap. Model changes take effect after a restart; the cap applies at once.",
  prefixes: ["models.", "budget."],
  render(ctx) {
    const s = ctx.settings;
    const root = el("div", "group-body");
    const source = note();
    void ctx.models().then((l) => (source.textContent = l ? SOURCE_WORDS[l.source] : "The list of models could not be loaded."));

    const claude = block(
      "Claude",
      row(ctx, "models.talk", "Talk model", modelInput(ctx, "models.talk"), { note: "Answers every turn; also the host agent's model." }),
      row(ctx, "models.heavy", "Heavy model", modelInput(ctx, "models.heavy"), { note: "Used when a question needs more thought." }),
      source,
    );

    const local = block(
      "Local fallback",
      row(ctx, "models.local", "Local model", textInput(ctx, "models.local", { placeholder: "mlx-community/…" }), {
        note: "Answers when offline or over the cap. A Hugging Face repo, run on this Mac.",
      }),
      downloadControl(ctx.api, "local_model", () => void ctx.reload({ redraw: false })),
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
    root.append(claude, local, budget);
    return root;
  },
};
