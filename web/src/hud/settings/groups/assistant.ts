import { OWNER_LIMITS } from "../../../net/owner";
import { el } from "../../dom";
import { row, textArea, textInput } from "../bind";
import type { Group } from "../context";
import { block } from "../fields";

export const assistantGroup: Group = {
  id: "assistant",
  title: "Assistant",
  blurb: "What the assistant is called, and what it always knows about you. Both apply at once, from the next thing you say.",
  prefixes: ["assistant.", "owner."],
  render(ctx) {
    const root = el("div", "group-body");
    const name = ctx.settings.assistant.name;
    root.append(
      block(
        "The assistant",
        row(ctx, "assistant.name", "Name", textInput(ctx, "assistant.name", { maxLength: 40 }), {
          note: "The host agent, who runs the Hall, carries this name too.",
        }),
      ),
      block(
        "About you",
        el("p", "field-note", `${name} keeps this in mind in every conversation, and so do the other agents at work. It is saved in owner.md in the memory vault, where you can also edit it by hand. All of it is optional; ${name} changes it too when you tell it to.`),
        row(ctx, "owner.name", "What to call you", textInput(ctx, "owner.name", { maxLength: OWNER_LIMITS.name, placeholder: "Your name, or what you like to be called" })),
        row(ctx, "owner.business", "Your business", textArea(ctx, "owner.business", { maxLength: OWNER_LIMITS.business, rows: 3, placeholder: "Its name and what it does, in your own words" })),
        row(ctx, "owner.notes", "Anything else to keep in mind", textArea(ctx, "owner.notes", { maxLength: OWNER_LIMITS.notes, rows: 4, placeholder: "How you like to work, who is who, what matters this year" }), {
          note: `Up to ${OWNER_LIMITS.notes.toLocaleString("en")} characters. Longer material belongs in the Library.`,
        }),
      ),
    );
    return root;
  },
};
