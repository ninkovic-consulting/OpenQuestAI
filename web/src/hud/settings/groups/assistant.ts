import { el } from "../../dom";
import { row, textInput } from "../bind";
import type { Group } from "../context";

export const assistantGroup: Group = {
  id: "assistant",
  title: "Assistant",
  blurb: "What the assistant is called. A new name applies at once, in this window and in what it says.",
  prefixes: ["assistant."],
  render(ctx) {
    const root = el("div", "group-body");
    root.append(
      row(ctx, "assistant.name", "Name", textInput(ctx, "assistant.name", { maxLength: 40 }), {
        note: "The host agent, who runs the Hall, carries this name too.",
      }),
    );
    return root;
  },
};
