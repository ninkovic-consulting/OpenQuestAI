// One proposal in full. A tool: who proposed it and why, what it does, its
// reach, its input, the whole script and its hash, the changes from the
// version it replaces, and the confinement; Approve with who may use it and
// how it runs, or Decline with a note. A change: before and after side by
// side; Approve or Decline, and Restore once approved.

import type { ApproveBody, Confinement, Proposal, ProposedTool } from "../../net/proposal-types";
import { el } from "../dom";
import { block, button, confirmButton, segmented, statusLine } from "../settings/fields";
import {
  approveBody,
  changeSides,
  DEFAULT_CHOICE,
  decidedWhen,
  FIELD_WORD,
  lineCount,
  lineDiff,
  networkWarning,
  restorable,
  STATUS_WORD,
  TIER_CHOICES,
  versionNote,
  whoChoices,
  type ApproveChoice,
} from "./model";
import { codeBlock, confinementBlock, diffBlock, facts, hashLine, reachList, refusalLine, stateChip } from "./parts";

export interface ProposalActions {
  /** Each answers the daemon's refusal, or null when it went through. */
  approve(body: ApproveBody): Promise<string | null>;
  decline(note: string): Promise<string | null>;
  restore(): Promise<string | null>;
}

export interface ProposalDetailOptions {
  /** The proposal in full once fetched; until then the listing's summary. */
  proposal: Proposal;
  full: boolean;
  problem: string | null;
  confinement: Confinement | null;
  /** For a new version: the script of the version it replaces; null while loading or when it is gone. */
  previous: string | null;
  /** Where the proposal was made: the room's name. */
  room: string | null;
  now: number;
  act: ProposalActions;
}

export function proposalDetail(o: ProposalDetailOptions): HTMLElement {
  const p = o.proposal;
  const root = el("div", "group-body job-detail proposal-detail");
  const top = el("div", "job-top");
  top.append(stateChip(p.status, STATUS_WORD[p.status], decidedWhen(p, o.now)));
  root.append(top);
  if (p.note) root.append(block("Your note", el("p", "job-text", p.note)));
  if (o.problem) root.append(statusLine("bad", `The proposal could not be loaded in full: ${o.problem}`));
  if (p.tool) toolParts(root, p, p.tool, o);
  else changeParts(root, p, o);
  return root;
}

function toolParts(root: HTMLElement, p: Proposal, tool: ProposedTool, o: ProposalDetailOptions): void {
  root.append(
    facts([
      ["Proposed by", o.room ? `${p.agent_name}, in the ${o.room}` : p.agent_name],
      ["Tool", tool.tool_name],
      ["Language", tool.language === "python" ? "Python (standard library)" : "POSIX shell"],
      ["Version", tool.replaces === null ? "1, a new tool" : `${tool.version}, replaces ${tool.replaces}`],
    ]),
  );
  const note = versionNote(tool);
  if (note) root.append(statusLine("warn", note));
  root.append(block("Why", el("p", "job-text", p.reason)), block("Reach", reachList(tool.reach)));
  if (tool.script === undefined) root.append(block("Script", statusLine(o.problem ? "bad" : "idle", o.problem ? "The script could not be loaded." : "Loading the script…")));
  else {
    const script = block(`Script · ${lineCount(tool.script)} lines`, codeBlock(tool.script, `The script of ${tool.name}`), hashLine(tool.sha256));
    root.append(script);
    if (tool.replaces !== null) root.append(compare(tool, tool.script, o.previous));
  }
  root.append(block("Input", codeBlock(JSON.stringify(tool.input_schema, null, 2), "Input schema")));
  root.append(block("Confinement", confinementBlock(o.confinement)));
  if (p.status === "waiting") root.append(decide(p, o, tool));
}

function compare(tool: ProposedTool, script: string, previous: string | null): HTMLElement {
  const details = el("details", "compare");
  details.append(el("summary", "caps", `Changes from version ${tool.replaces ?? ""}`));
  if (previous === null) details.append(statusLine("idle", "The earlier version's script is not available."));
  else details.append(diffBlock(lineDiff(previous, script), `Changes from version ${tool.replaces ?? ""}`), codeLabel(`Version ${tool.replaces ?? ""} in full`), codeBlock(previous, `Version ${tool.replaces ?? ""}`));
  return details;
}

const codeLabel = (text: string): HTMLElement => el("p", "field-note caps compare-label", text);

function changeParts(root: HTMLElement, p: Proposal, o: ProposalDetailOptions): void {
  const change = p.change;
  if (!change) return;
  const self = change.agent === p.agent;
  root.append(
    facts([
      ["Whose", change.agent_name],
      ["What", FIELD_WORD[change.field]],
      ["Proposed by", self ? `${p.agent_name} itself` : p.agent_name],
    ]),
  );
  root.append(block("Why", el("p", "job-text", p.reason)));
  const sides = el("div", `sides${change.field === "persona" ? " is-long" : ""}`);
  for (const [i, side] of changeSides(change, p.status).entries()) {
    const box = el("div", `side${i === 1 ? " is-after" : ""}`);
    box.append(el("h5", "caps", side.label), el(side.long ? "div" : "p", side.long ? "side-text" : "side-value", side.text));
    if (side.long) box.lastElementChild?.setAttribute("tabindex", "0");
    sides.append(box);
  }
  const clipped = p.clipped === true && !o.full;
  root.append(block(`${FIELD_WORD[change.field]} · before and after`, sides));
  if (clipped) root.append(statusLine("idle", "Loading the whole text…"));
  if (p.status === "waiting") root.append(decide(p, o, null));
  else if (restorable(p)) {
    const said = refusalLine();
    const back = confirmButton(
      "Restore",
      { question: `Put ${change.agent_name}'s ${FIELD_WORD[change.field]} back to what it was before this change?`, confirm: "Restore", danger: true },
      async () => {
        const problem = await o.act.restore();
        said.say(problem);
        return problem === null ? "Put back." : "";
      },
    );
    root.append(block("Put it back", el("p", "field-note", "Restore puts the earlier value back, the same way the change was made."), back, said.node));
  }
}

/** Approve, with the choices a tool needs, or Decline with an optional note. */
function decide(p: Proposal, o: ProposalDetailOptions, tool: ProposedTool | null): HTMLElement {
  const root = el("section", "block decide");
  root.append(el("h4", "caps", "Your decision"));
  const choice: ApproveChoice = { ...DEFAULT_CHOICE };
  const warn = el("p", "field-error decide-warning");
  warn.hidden = true;
  if (tool) {
    const showWarning = (): void => {
      const w = networkWarning(tool, choice.tier);
      warn.hidden = w === null;
      warn.textContent = w ?? "";
    };
    const row = (label: string, control: HTMLElement): HTMLElement => {
      const line = el("div", "decide-row");
      line.append(el("span", "caps decide-label", label), control);
      return line;
    };
    root.append(
      row("Who may use it", segmented("Who may use it", whoChoices(p.agent_name), choice.who, (v) => (choice.who = v === "everyone" ? "everyone" : "author"))),
      row(
        "How it runs",
        segmented("How it runs", TIER_CHOICES, choice.tier, (v) => {
          choice.tier = v === "free" ? "free" : "ask";
          showWarning();
        }),
      ),
      warn,
    );
    if (o.confinement && !o.confinement.available) root.append(statusLine("bad", "Approved now, it will not run until this Mac can confine it."));
  }
  const approve = button("Approve", "primary");
  const decline = button("Decline");
  const actions = el("div", "row-actions");
  actions.append(approve, decline);
  const said = refusalLine();
  const noteBox = el("div", "confirm-box decline-box");
  noteBox.hidden = true;
  const note = el("textarea", "decline-note");
  note.rows = 2;
  note.maxLength = 500;
  note.placeholder = "A note for the agent (optional)";
  note.setAttribute("aria-label", "A note for the agent");
  const sure = button("Decline", "danger");
  const keep = button("Cancel");
  const noteActions = el("div", "row-actions");
  noteActions.append(sure, keep);
  noteBox.append(el("p", "confirm-question", `Decline ${p.title}? The agent sees your note.`), note, noteActions);
  root.append(actions, noteBox, said.node);

  const busy = (on: boolean): void => {
    for (const b of [approve, decline, sure, keep]) b.disabled = on;
  };
  const run = async (work: Promise<string | null>): Promise<void> => {
    busy(true);
    said.say(null);
    const problem = await work;
    busy(false);
    said.say(problem);
  };
  // A tool's script must be on screen before it can be approved.
  approve.disabled = tool !== null && tool.script === undefined;
  approve.addEventListener("click", () => void run(o.act.approve(approveBody(p, choice))));
  decline.addEventListener("click", () => {
    actions.hidden = true;
    noteBox.hidden = false;
    note.focus();
  });
  keep.addEventListener("click", () => {
    noteBox.hidden = true;
    actions.hidden = false;
    decline.focus();
  });
  sure.addEventListener("click", () => void run(o.act.decline(note.value.trim())));
  return root;
}
