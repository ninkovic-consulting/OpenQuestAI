import { el } from "../../dom";
import { modelInput, row, textInput } from "../bind";
import type { Group } from "../context";
import { button } from "../fields";

export const agentsGroup: Group = {
  id: "agents",
  title: "Agents",
  blurb: "The residents of the house: each one's name and model. Changes apply at once.",
  prefixes: ["agents."],
  render(ctx) {
    const s = ctx.settings;
    const root = el("div", "group-body");
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
          el("p", "field-note", `The host runs the Hall and only the Hall. Its name follows the assistant's name, and its model is the talk model (${s.models.talk}).`),
          actions,
        );
      } else {
        const fields = el("div", "two-up");
        fields.append(
          row(ctx, `agents.${agent.id}.name`, "Name", textInput(ctx, `agents.${agent.id}.name`, { maxLength: 40 })),
          row(ctx, `agents.${agent.id}.model`, "Model", modelInput(ctx, `agents.${agent.id}.model`)),
        );
        card.append(fields);
      }
      root.append(card);
    }
    return root;
  },
};
