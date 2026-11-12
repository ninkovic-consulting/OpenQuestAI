import { el } from "../../dom";
import type { Group } from "../context";
import { block } from "../fields";
import { keyForm, keyStatus } from "../key-parts";

export const keyGroup: Group = {
  id: "key",
  title: "API key",
  blurb: "The Anthropic API key the assistant talks to Claude with. A first key works at once; replacing a key takes effect after a restart.",
  prefixes: [],
  render(ctx) {
    const key = ctx.settings.key;
    const root = el("div", "group-body");
    const where = block("Where it is", keyStatus(key));
    if (key.source === "env_file" || key.source === "environment") {
      where.append(el("p", "field-note", "This key is not in the Keychain. A key saved here goes to the Keychain; remove the old one where it is kept so there is only one."));
    }
    const form = keyForm(ctx.api, key.stored, (answer) => {
      where.querySelector(".status")?.replaceWith(keyStatus({ stored: answer.stored, source: answer.source }));
      void ctx.reload({ redraw: false });
    });
    root.append(where, block(key.stored ? "Replace it" : "Add it", form));
    return root;
  },
};
