import type { GateTool, Settings } from "../../../net/settings-types";
import { el } from "../../dom";
import { ROOM_RUNS_COMMANDS } from "../../listen";
import type { Group, SettingsContext } from "../context";
import { button, fieldRow, segmented, type Segment } from "../fields";

const LOCKED = "Always asks first: it makes a folder and a room, and may start paid work.";
const AT_THE_MAC =
  "Free applies only to what you type or say at this Mac. During an automation's run, a job report or a message from your phone it still asks first, here at the Mac: nobody may be watching, and those turns can carry words you did not write.";
const FROM_THE_MAC =
  "Free applies only to jobs you start at this Mac: typed, said, or from a room's card. A job started from your phone, by an automation or by another agent still asks first, here at the Mac. A program can run code from the project.";
const WARNING =
  "With Free, a shell command the assistant decides to run happens at once, without a card. It can run anything on this Mac. Every run is still written to the audit log.";
const PROGRAM_WARNING =
  "With Free, a program an agent decides to run in a job you started here happens at once, without a card. A program such as git, npm or python can run any code in the project. Every run is still written to the audit log.";
const ROOM_STARTS_PROGRAMS =
  "With Always on and programs Free, anything said in the room can start a job whose programs run without a card.";

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
 * The words under a tool's tiers: its description, then what Free means for it.
 * Shell also points to the switch for the programs the other agents run.
 */
export function tierNote(gate: Settings["gate"], tool: GateTool): string {
  if (gate.never_free.includes(tool.id)) return `${tool.description} ${LOCKED}`;
  if (gate.free_for_jobs_from_the_mac.includes(tool.id)) return `${tool.description} ${FROM_THE_MAC}`;
  if (!gate.free_at_the_mac_only.includes(tool.id)) return tool.description;
  const programs = tool.id === "shell" ? gate.tools.find((t) => gate.free_for_jobs_from_the_mac.includes(t.id)) : undefined;
  const pointer = programs ? ` Programs the other agents run in a project folder have their own switch: ${programs.title}.` : "";
  return `${tool.description}${pointer} ${AT_THE_MAC}`;
}

/** The question asked before Free is taken for a tool that may be free only in some turns or jobs. */
function freeWarning(tool: GateTool, gate: Settings["gate"], listen: string): string {
  if (gate.free_for_jobs_from_the_mac.includes(tool.id)) return listen === "always" ? `${PROGRAM_WARNING} ${ROOM_STARTS_PROGRAMS}` : PROGRAM_WARNING;
  return listen === "always" && tool.id === "shell" ? `${WARNING} ${ROOM_RUNS_COMMANDS}` : WARNING;
}

/**
 * One tool's tiers. A tool that is never free shows Free struck through; a
 * tool that is free only at the Mac, or only in jobs started at the Mac, asks
 * for a confirmation before Free is taken.
 */
function tierRow(ctx: SettingsContext, tool: GateTool): HTMLElement {
  const field = `gate.tiers.${tool.id}`;
  const gate = ctx.settings.gate;
  const neverFree = gate.never_free.includes(tool.id);
  const confirmFree = gate.free_at_the_mac_only.includes(tool.id) || gate.free_for_jobs_from_the_mac.includes(tool.id);
  const segments: Segment[] = [
    neverFree ? { value: "free", label: "Free", locked: LOCKED } : { value: "free", label: "Free" },
    { value: "ask", label: "Ask" },
    { value: "never", label: "Never" },
  ];
  const note = tierNote(gate, tool);
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
    const label = gate.free_for_jobs_from_the_mac.includes(tool.id) ? `Make "${tool.title}" free` : `Make ${tool.title.toLowerCase()} free`;
    const yes = button(label, "danger");
    const no = button("Cancel");
    const actions = el("div", "row-actions");
    actions.append(yes, no);
    const listen = ctx.draft["voice.listen"] ?? ctx.settings.voice.listen;
    box.append(el("p", "confirm-question", freeWarning(tool, gate, listen)), actions);
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
