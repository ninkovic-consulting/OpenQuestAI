// One procedure: when to use it, who wrote it, how often it was read and its
// steps; Edit (title, when, steps) and Delete after a confirmation.

import type { Procedure, ProcedureEdit, ProcedureLimits, ProcedureSummary } from "../../net/procedure-types";
import { el } from "../dom";
import { block, button, confirmButton, fieldRow, statusLine } from "../settings/fields";
import { procedureEdit, procedureMeta } from "./model";
import { refusalLine } from "./parts";

export interface ProcedureActions {
  /** Each answers the daemon's refusal, or null when it went through. */
  edit(edit: ProcedureEdit): Promise<string | null>;
  remove(): Promise<string | null>;
  /** Switch between reading and editing. */
  editing(on: boolean): void;
}

export interface ProcedureDetailOptions {
  summary: ProcedureSummary;
  /** Whose: the agent's name, or "Shared". */
  ownerName: string;
  authorName: string;
  full: Procedure | null;
  problem: string | null;
  limits: ProcedureLimits | null;
  editing: boolean;
  now: number;
  act: ProcedureActions;
}

export function procedureDetail(o: ProcedureDetailOptions): HTMLElement {
  const root = el("div", "group-body job-detail procedure-detail");
  const s = o.summary;
  const meta = el("p", "procedure-meta", procedureMeta(s, o.authorName, o.now));
  root.append(meta);
  if (!o.full) {
    root.append(statusLine(o.problem ? "bad" : "idle", o.problem ? `The steps could not be loaded: ${o.problem}` : "Loading the steps…"));
    return root;
  }
  if (o.editing) {
    root.append(editor(o.full, o));
    return root;
  }
  const said = refusalLine();
  const top = el("div", "row-actions procedure-actions");
  const edit = button("Edit");
  edit.addEventListener("click", () => o.act.editing(true));
  const shared = s.shared ? ` It is shared: every agent sees it, and only ${o.authorName} or the host may change it.` : "";
  top.append(
    edit,
    confirmButton("Delete", { question: `Delete “${s.title}”?${shared} This cannot be undone.`, confirm: "Delete", danger: true }, async () => {
      const problem = await o.act.remove();
      said.say(problem);
      return problem === null ? "Deleted." : "";
    }),
  );
  root.append(top, said.node);
  root.append(block("When to use it", el("p", "job-text", s.when || "Not said.")));
  const steps = el("div", "procedure-steps", o.full.steps);
  steps.tabIndex = 0;
  root.append(block(`Steps · ${s.chars.toLocaleString("en-GB")} characters`, steps));
  return root;
}

function editor(full: Procedure, o: ProcedureDetailOptions): HTMLElement {
  const form = el("form", "procedure-form");
  const title = el("input");
  title.value = full.title;
  const when = el("textarea", "procedure-when");
  when.rows = 2;
  when.value = full.when;
  const steps = el("textarea", "procedure-steps-edit");
  steps.rows = 14;
  steps.value = full.steps;
  const limits = o.limits;
  if (limits) {
    title.maxLength = limits.name;
    when.maxLength = limits.when;
    steps.maxLength = limits.steps;
  }
  const count = el("p", "field-note");
  const counted = (): void => {
    count.textContent = limits ? `${steps.value.length.toLocaleString("en-GB")} of ${limits.steps.toLocaleString("en-GB")} characters` : "";
  };
  counted();
  steps.addEventListener("input", counted);
  const said = refusalLine();
  const save = button("Save", "primary");
  save.type = "submit";
  const cancel = button("Cancel");
  const actions = el("div", "row-actions");
  actions.append(save, cancel);
  form.append(fieldRow("Title", title), fieldRow("When to use it", when), fieldRow("Steps", steps), count, actions, said.node);
  cancel.addEventListener("click", () => o.act.editing(false));
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const body = procedureEdit(full, { title: title.value, when: when.value, steps: steps.value });
    if (body === null) {
      o.act.editing(false);
      return;
    }
    save.disabled = cancel.disabled = true;
    void o.act.edit(body).then((problem) => {
      save.disabled = cancel.disabled = false;
      said.say(problem);
    });
  });
  queueMicrotask(() => title.focus());
  return form;
}
