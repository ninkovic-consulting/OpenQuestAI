// The Jobs panel: a full-height overlay over the scene in the Settings style,
// the jobs on the left and the chosen one (or the "New job" form) on the
// right. It follows the board live while open. A narrow scene shows one side
// at a time; Escape and Back step from the form to the job to the list.

import "../../styles/jobs.css";
import type { JobDetails, JobLimits, Started } from "../../net/job-types";
import type { JobsApi } from "../../net/jobs-api";
import type { Store, ViewState } from "../../net/store";
import { el, setText } from "../dom";
import { button } from "../settings/fields";
import { jobDetail } from "./detail";
import { jobForm } from "./form";
import { jobList } from "./list";
import { jobRows, namesFrom, whoWhere } from "./model";

/** Below this width the panel shows the list or the job, not both (as in jobs.css). */
const NARROW_PX = 760;
/** How often the times in the list ("4 min") move on while the panel is open. */
const TICK_MS = 15_000;

export interface JobsDeps {
  api: JobsApi;
  store: Store;
  /** Hears the panel open and close (the panel's toggle lights up). */
  onShown(open: boolean): void;
}

export interface JobsView {
  /** Open the panel, on this job when it is known. */
  open(jobId?: string): void;
  /** One step back: the form, then the job on a narrow scene, then the panel. False when it was not open. */
  back(): boolean;
  close(): boolean;
  isOpen(): boolean;
}

export function mountJobs(parent: HTMLElement, deps: JobsDeps): JobsView {
  const { api, store } = deps;
  const root = el("div", "settings jobs");
  root.hidden = true;
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.setAttribute("aria-label", "Jobs");

  const side = el("nav", "settings-nav jobs-side");
  const sideHead = el("div", "settings-title");
  const add = button("New job", "primary");
  sideHead.append(el("h2", "", "Jobs"), el("span", "caps hint", "Esc"), add);
  const listSlot = el("div", "job-list-slot");
  side.append(sideHead, listSlot);

  const main = el("section", "settings-main jobs-main");
  const head = el("header", "settings-head");
  const titles = el("div");
  const kicker = el("p", "kicker caps");
  const title = el("h3");
  const blurb = el("p", "blurb");
  titles.append(kicker, title, blurb);
  const backBtn = el("button", "settings-close jobs-back caps", "Back");
  const close = el("button", "settings-close caps", "Close");
  backBtn.type = close.type = "button";
  const headActions = el("div", "jobs-head-actions");
  headActions.append(backBtn, close);
  head.append(titles, headActions);
  const body = el("div", "settings-body");
  main.append(head, body);
  const frame = el("div", "settings-frame");
  frame.append(side, main);
  root.append(frame);
  parent.append(root);

  let selected: string | null = null;
  let form = false;
  /** On a narrow scene: the list shows rather than the job. */
  let listing = true;
  let limits: JobLimits | null = null;
  let said = "";
  const details = new Map<string, JobDetails>();
  const problems = new Map<string, string>();
  let loading: string | null = null;
  let loadAgain = false;
  let timer = 0;

  const narrow = (): boolean => root.clientWidth <= NARROW_PX;
  const s = (): ViewState => store.get();

  const renderList = (): void => {
    const st = s();
    listSlot.replaceChildren(jobList({ jobs: st.jobs, selected: form ? null : selected, names: namesFrom(st.plan), now: Date.now() / 1000, pick }));
  };

  const renderMain = (): void => {
    const st = s();
    const names = namesFrom(st.plan);
    const job = selected ? st.jobs[selected] : undefined;
    root.dataset["pane"] = form ? "form" : job && !listing ? "job" : "list";
    if (form && st.plan) {
      setText(kicker, "Jobs");
      setText(title, "New job");
      setText(blurb, "Hand work to one of the residents. It starts as soon as the resident and a place are free; the assistant tells you how it went.");
      body.replaceChildren(el("div", "group-body"));
      body.firstElementChild?.append(jobForm({ api, plan: st.plan, limits, done: started, cancel: () => back() }));
      return;
    }
    if (!job) {
      setText(kicker, "");
      setText(title, "Jobs");
      setText(blurb, "Work the assistant hands to the residents, and work they ask of each other. Pick one to see its steps.");
      body.replaceChildren();
      return;
    }
    setText(kicker, whoWhere(job, names));
    setText(title, job.title);
    setText(blurb, said);
    const parentJob = job.parent ? (st.jobs[job.parent] ?? null) : null;
    const hostName = st.plan?.assistant.name ?? "the assistant";
    body.replaceChildren(
      jobDetail({
        job,
        details: details.get(job.id) ?? null,
        problem: problems.get(job.id) ?? null,
        names,
        host: hostName,
        now: Date.now() / 1000,
        parent: parentJob,
        cancel: async () => {
          const r = await api.cancel(job.id);
          return r.ok ? null : r.message;
        },
        open: pick,
      }),
    );
  };

  const render = (): void => {
    renderList();
    renderMain();
  };

  const fetchDetails = async (id: string): Promise<void> => {
    if (loading !== null) {
      loadAgain = loadAgain || loading === id;
      return;
    }
    loading = id;
    const r = await api.get(id);
    loading = null;
    if (r.ok) {
      details.set(id, r.value);
      problems.delete(id);
    } else problems.set(id, r.message);
    if (!root.hidden && selected === id && !form) renderMain();
    if (loadAgain) {
      loadAgain = false;
      if (selected) void fetchDetails(selected);
    }
  };

  function pick(id: string): void {
    selected = id;
    form = false;
    listing = false;
    said = "";
    render();
    body.scrollTop = 0;
    void fetchDetails(id);
  }

  function started(r: Started): void {
    const name = namesFrom(s().plan).agent(r.job.agent);
    pick(r.job.id);
    said = r.started ? `${name} started on it.` : `It waits its turn and starts by itself when ${name} and a place are free.`;
    renderMain();
  }

  const hide = (): boolean => {
    if (root.hidden) return false;
    root.hidden = true;
    window.clearInterval(timer);
    deps.onShown(false);
    if (root.contains(document.activeElement) && document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return true;
  };

  function back(): boolean {
    if (root.hidden) return false;
    if (form) {
      form = false;
      render();
      return true;
    }
    if (narrow() && !listing && selected) {
      listing = true;
      renderMain();
      return true;
    }
    return hide();
  }

  add.addEventListener("click", () => {
    form = true;
    said = "";
    render();
    body.querySelector<HTMLElement>("textarea")?.focus();
  });
  backBtn.addEventListener("click", () => back());
  close.addEventListener("click", hide);

  // Keys typed here stay here: Space must not start push to talk, letters must not go to the message field.
  root.addEventListener("keydown", (ev) => {
    ev.stopPropagation();
    if (ev.key === "Escape") back();
  });

  store.subscribe((st, prev) => {
    if (root.hidden) return;
    if (st.jobs !== prev.jobs || st.plan !== prev.plan) renderList();
    const changed = selected !== null && st.jobs[selected] !== prev.jobs[selected];
    if (!form && (changed || st.plan !== prev.plan)) renderMain();
    if (changed && selected) void fetchDetails(selected);
  });

  return {
    open(jobId?: string): void {
      root.hidden = false;
      deps.onShown(true);
      form = false;
      said = "";
      const wanted = jobId !== undefined && s().jobs[jobId] !== undefined;
      listing = !wanted;
      if (wanted) selected = jobId;
      const rows = jobRows(s().jobs);
      if (!selected || !s().jobs[selected]) selected = rows[0]?.job.id ?? null;
      render();
      if (selected) void fetchDetails(selected);
      (listSlot.querySelector<HTMLElement>("[aria-current='true']") ?? add).focus();
      window.clearInterval(timer);
      timer = window.setInterval(renderList, TICK_MS);
      // The list from the daemon also refreshes the store, and carries the limits for the form.
      void api.list().then((r) => {
        if (!r.ok) return;
        limits = r.value.limits;
        store.dispatch({ kind: "jobs", list: r.value });
      });
    },
    back,
    close: hide,
    isOpen: () => !root.hidden,
  };
}
