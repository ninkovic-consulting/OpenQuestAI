import type { GateTool } from "../../../net/settings-types";
import { el } from "../../dom";
import type { Group, SettingsContext } from "../context";
import { button, fieldRow, segmented, type Segment } from "../fields";

const LOCKED = "Always asks first: a project's programs can run any code.";
const AT_THE_MAC =
  "Free applies only to what you type or say at this Mac. During an automation's run, a job report or a message from your phone it still asks first, here at the Mac: nobody may be watching, and those turns can carry words you did not write.";
const WARNING =
  "With Free, a shell command the assistant decides to run happens at once, without a card. It can run anything on this Mac. Every run is still written to the audit log.";

export const askingGroup: Group = {
  id: "asking",
  title: "Asking first",
  blurb: "For each tool: free runs it without asking, ask waits for your yes, never refuses it. Applies at once.",
  prefixes: ["gate."],
  render(ctx) {
    const root = el("div", "group-body");
    const list = el("div", "tier-list");
    for (const tool of ctx.settings.gate.tools) list.append(tierRow(ctx, tool));
    root.append(list);
    return root;
  },
};

/**
 * One tool's tiers. A tool that is never free shows Free struck through; a
 * tool that is free only at the Mac asks for a confirmation before Free is taken.
 */
function tierRow(ctx: SettingsContext, tool: GateTool): HTMLElement {
  const field = `gate.tiers.${tool.id}`;
  const gate = ctx.settings.gate;
  const neverFree = gate.never_free.includes(tool.id);
  const confirmFree = gate.free_at_the_mac_only.includes(tool.id);
  const segments: Segment[] = [
    neverFree ? { value: "free", label: "Free", locked: LOCKED } : { value: "free", label: "Free" },
    { value: "ask", label: "Ask" },
    { value: "never", label: "Never" },
  ];
  const note = neverFree ? `${tool.description} ${LOCKED}` : confirmFree ? `${tool.description} ${AT_THE_MAC}` : tool.description;
  const confirm = el("div", "tier-confirm");
  const control = (): HTMLElement =>
    segmented(tool.title, segments, ctx.draft[field] ?? "ask", (v) => {
      if (v === "free" && confirmFree && ctx.draft[field] !== "free") askFirst();
      else {
        confirm.replaceChildren();
        ctx.edit(field, v);
      }
    });
  let current = control();
  const row = fieldRow(tool.title, current, { note, error: ctx.errorFor(field) });
  row.classList.add("tier-row");
  row.append(confirm);

  /** Free is shown chosen while the question is up; Cancel puts the old choice back. */
  const askFirst = (): void => {
    const box = el("div", "confirm-box");
    const yes = button(`Make ${tool.title.toLowerCase()} free`, "danger");
    const no = button("Cancel");
    const actions = el("div", "row-actions");
    actions.append(yes, no);
    box.append(el("p", "confirm-question", WARNING), actions);
    confirm.replaceChildren(box);
    yes.focus();
    yes.addEventListener("click", () => {
      confirm.replaceChildren();
      ctx.edit(field, "free");
    });
    no.addEventListener("click", () => {
      confirm.replaceChildren();
      const fresh = control();
      current.replaceWith(fresh);
      current = fresh;
    });
  };
  return row;
}
