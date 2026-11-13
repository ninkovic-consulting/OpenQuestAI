// The list of jobs on the left of the Jobs panel: newest first, each request
// between residents under the job that made it.

import type { Job } from "../../net/job-types";
import { el } from "../dom";
import { jobRows, STATUS_WORD, timeWords, whoWhere, type Names } from "./model";

export interface ListOptions {
  jobs: Readonly<Record<string, Job>>;
  selected: string | null;
  names: Names;
  now: number;
  pick(id: string): void;
}

export function jobList(o: ListOptions): HTMLElement {
  const rows = jobRows(o.jobs);
  const list = el("ul", "job-list");
  list.setAttribute("aria-label", "Jobs");
  if (rows.length === 0) {
    list.append(el("li", "job-empty", "No jobs yet. Ask the assistant to hand one to a resident, or start one here."));
    return list;
  }
  for (const { job, depth } of rows) {
    const item = el("li");
    const b = el("button", `job-row is-${job.status}${depth ? " is-request" : ""}`);
    b.type = "button";
    b.setAttribute("aria-current", String(job.id === o.selected));
    const who = el("span", "job-who caps", `${whoWhere(job, o.names)} · ${STATUS_WORD[job.status]}`);
    const text = el("span", "job-row-text");
    if (depth) text.append(el("span", "job-asked caps", `Asked by ${o.names.agent(job.asked_by)}`));
    text.append(el("span", "job-title", job.title), who, el("span", "job-when", timeWords(job, o.now)));
    if (job.last_step) text.append(el("span", "job-last", job.last_step.text));
    if (job.needed_approval) text.append(el("span", "job-flag caps", "An approval was missed"));
    b.append(el("span", "dot"), text);
    b.addEventListener("click", () => o.pick(job.id));
    item.append(b);
    list.append(item);
  }
  return list;
}
