// One job in full: where it stands, who asked, the brief, its steps as a
// timeline, the result or the error, the cost, and Cancel while it is open.

import type { Job, JobDetails } from "../../net/job-types";
import { el } from "../dom";
import { formatSpend } from "../money";
import { block, button, statusLine } from "../settings/fields";
import { asker, cancellable, clock, STATUS_WORD, timeWords, type Names } from "./model";

export interface DetailOptions {
  /** The job as the store has it, always current. */
  job: Job;
  /** Its details once fetched; null while loading or when they could not be. */
  details: JobDetails | null;
  /** Why the details are missing, when they failed to load. */
  problem: string | null;
  names: Names;
  host: string;
  now: number;
  /** The job that made this request, when it is one. */
  parent: Job | null;
  cancel(): Promise<string | null>;
  open(id: string): void;
}

export function jobDetail(o: DetailOptions): HTMLElement {
  const { job, details, names } = o;
  const root = el("div", "group-body job-detail");

  const state = el("div", `job-state is-${job.status}`);
  state.append(el("span", "dot"), el("span", "caps", STATUS_WORD[job.status]), el("span", "when", timeWords(job, o.now)));
  const top = el("div", "job-top");
  top.append(state);
  if (cancellable(job)) {
    const cancel = button("Cancel job", "danger");
    const said = el("p", "field-error");
    said.hidden = true;
    cancel.addEventListener("click", () => {
      cancel.disabled = true;
      void o.cancel().then((problem) => {
        cancel.disabled = false;
        said.hidden = problem === null;
        said.textContent = problem ?? "";
      });
    });
    top.append(cancel, said);
  }
  root.append(top);

  if (job.needed_approval) root.append(statusLine("bad", "A tool asked for your yes during the work and nobody answered, so it did not run."));

  const facts = el("dl", "job-facts");
  const fact = (term: string, value: string): void => {
    const row = el("div");
    row.append(el("dt", "caps", term), el("dd", "", value));
    facts.append(row);
  };
  fact("Resident", names.agent(job.agent));
  fact("Room", names.room(job.room) ?? "None");
  fact("Asked by", `${asker(job, names, o.host)} · ${clock(job.created_at, o.now)}`);
  if (details) {
    fact("Careful", details.careful ? "Yes, the heavier model" : "No");
    fact("Cost", formatSpend(details.cost_usd));
  }
  root.append(facts);

  if (o.parent) {
    const link = el("button", "job-link", `A request from ${names.agent(o.parent.agent)}'s job “${o.parent.title}”`);
    link.type = "button";
    const parentId = o.parent.id;
    link.addEventListener("click", () => o.open(parentId));
    root.append(link);
  }

  if (!details) {
    root.append(statusLine(o.problem ? "bad" : "idle", o.problem ? `The details could not be loaded: ${o.problem}` : "Loading the brief and the steps…"));
    return root;
  }

  root.append(block("Brief", el("p", "job-text", details.brief)));
  if (details.error) root.append(block(job.status === "cancelled" ? "Why it stopped" : "What went wrong", statusLine(job.status === "failed" ? "bad" : "idle", details.error)));
  if (details.result) root.append(block(job.status === "done" ? "Result" : "Result so far", el("p", "job-text", details.result)));
  root.append(block(`Steps · ${details.steps.length}`, timeline(details, o.now)));
  return root;
}

function timeline(d: JobDetails, now: number): HTMLElement {
  const list = el("ol", "job-steps");
  for (const s of d.steps) {
    const item = el("li", `is-${s.kind}`);
    const head = el("div", "step-head");
    head.append(el("span", "dot"), el("span", "caps", s.kind), el("span", "when", clock(s.ts, now)));
    item.append(head, el("p", "step-text", s.text));
    list.append(item);
  }
  if (d.steps.length === 0) list.append(el("li", "is-empty", "No steps yet."));
  return list;
}
