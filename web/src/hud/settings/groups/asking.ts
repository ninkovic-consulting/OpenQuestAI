import { el } from "../../dom";
import type { Group } from "../context";
import { fieldRow, segmented, type Segment } from "../fields";

const LOCKED = "Always asks first: it can run anything on this Mac.";

export const askingGroup: Group = {
  id: "asking",
  title: "Asking first",
  blurb: "For each tool: free runs it without asking, ask waits for your yes, never refuses it. Applies at once.",
  prefixes: ["gate."],
  render(ctx) {
    const s = ctx.settings;
    const root = el("div", "group-body");
    const list = el("div", "tier-list");
    for (const tool of s.gate.tools) {
      const field = `gate.tiers.${tool.id}`;
      const neverFree = s.gate.never_free.includes(tool.id);
      const segments: Segment[] = [
        neverFree ? { value: "free", label: "Free", locked: LOCKED } : { value: "free", label: "Free" },
        { value: "ask", label: "Ask" },
        { value: "never", label: "Never" },
      ];
      const control = segmented(tool.title, segments, ctx.draft[field] ?? "ask", (v) => ctx.edit(field, v));
      const row = fieldRow(tool.title, control, { note: neverFree ? `${tool.description} ${LOCKED}` : tool.description, error: ctx.errorFor(field) });
      row.classList.add("tier-row");
      list.append(row);
    }
    root.append(list);
    return root;
  },
};
