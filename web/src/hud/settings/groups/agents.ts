import { el } from "../../dom";
import { row, textInput } from "../bind";
import type { Group } from "../context";
import { EFFORT_HELP } from "../effort";
import { effortSlot } from "../effort-slot";
import { button } from "../fields";
import { mountModelPicker } from "../../pickers/model-picker";

export const agentsGroup: Group = {
  id: "agents",
  title: "Agents",
  blurb: "The residents of the house: each one's name, model and thinking level. Changes apply at once.",
  prefixes: ["agents."],
  render(ctx) {
    const s = ctx.settings;
    const root = el("div", "group-body");
    root.append(el("p", "field-note effort-help", `${EFFORT_HELP} A model that takes no levels shows none.`));
    for (const agent of s.agents) {
      const card = el("section", `agent-card${agent.is_host ? " is-host" : ""}`);
      const head = el("div", "card-head");
      head.append(el("h4", "card-title", agent.name), el("span", "tag", agent.is_host ? "host · runs the Hall" : agent.id));
      card.append(head);
      if (agent.is_host) {
        const models = button("Change in Models");
        models.addEventListener("click", () => ctx.goTo("models"));
        const rename = button("Rename the assistant");
        rename.addEventListener("click", () => ctx.goTo("assistant"));
        const actions = el("div", "row-actions");
        actions.append(rename, models);
        card.append(
          el("p", "field-note", `The host runs the Hall and only the Hall. Its name follows the assistant's name, and its model is the talk model (${s.models.talk}). Its thinking levels are the talk and heavy levels in Models.`),
          actions,
        );
      } else {
        const modelField = `agents.${agent.id}.model`;
        const model = ctx.draft[modelField] ?? agent.model;
        const careful = agent.heavy_model;
        const level = effortSlot(ctx, `agents.${agent.id}.effort`, "Thinking level", model);
        const heavy = effortSlot(ctx, `agents.${agent.id}.heavy_effort`, "Thinking level for careful work", careful ?? model);
        const picker = mountModelPicker({
          source: ctx.models,
          value: model,
          own: null,
          onChange: (v) => {
            ctx.edit(modelField, v);
            level.follow(v);
            if (!careful) heavy.follow(v);
          },
        });
        const fields = el("div", "two-up");
        fields.append(
          row(ctx, `agents.${agent.id}.name`, "Name", textInput(ctx, `agents.${agent.id}.name`, { maxLength: 40 })),
          row(ctx, modelField, "Model", picker.root),
        );
        const levels = el("div", "two-up effort-pair");
        levels.append(level.root, heavy.root);
        card.append(fields, levels);
      }
      root.append(card);
    }
    return root;
  },
};
