// The Proposals view: a full-height overlay over the scene in the Jobs
// panel's frame, with three tabs. Proposals: tools and changes the agents
// proposed, waiting ones first, each shown in full to approve or decline here
// and nowhere else. Tools: the approved tools, to turn on or off, re-tier,
// roll back or delete. Procedures: what each agent wrote down for next time.
// It follows the daemon's events while open; a narrow scene shows the list or
// the item, and Escape and Back step out.

import "../../styles/jobs.css";
import "../../styles/proposals.css";
import type { ProceduresApi } from "../../net/procedures-api";
import { SHARED, type Procedure, type ProcedureListing } from "../../net/procedure-types";
import type { ProposalsApi } from "../../net/proposals-api";
import type { Confinement, MadeTool, MadeToolDetail, Proposal, ProposalList } from "../../net/proposal-types";
import type { Store, ViewState } from "../../net/store";
import { el, setText } from "../dom";
import { namesFrom } from "../jobs/model";
import { segmented } from "../settings/fields";
import { madeList, procedureList, proposalList } from "./lists";
import { kindWord, madeRows, procedureGroups, procedureKey, proposalRows, waitingCount } from "./model";
import { procedureDetail } from "./procedure-detail";
import { proposalDetail } from "./proposal-detail";
import { toolDetail } from "./tool-detail";

/** Below this width the view shows the list or the item, not both (as in jobs.css). */
const NARROW_PX = 760;

export type Tab = "proposals" | "tools" | "procedures";

const TAB_TITLE: Record<Tab, string> = { proposals: "Proposals", tools: "Tools", procedures: "Procedures" };
const TAB_BLURB: Record<Tab, string> = {
  proposals: "New tools and changes the agents proposed. Nothing they propose does anything until you approve it here, at the Mac.",
  tools: "Tools the agents wrote and you approved. Each runs confined by macOS, only with the folders and network you allowed.",
  procedures: "What each agent wrote down so it does a task the same way next time, and the procedures every agent shares.",
};

export interface ProposalsDeps {
  api: ProposalsApi;
  procedures: ProceduresApi;
  store: Store;
  /** Hears the view open and close (the panel's toggle lights up). */
  onShown(open: boolean): void;
}

export interface ProposalsView {
  open(tab?: Tab): void;
  /** One step back: out of an edit, then the item on a narrow scene, then the view. False when it was not open. */
  back(): boolean;
  close(): boolean;
  isOpen(): boolean;
}

export function mountProposals(parent: HTMLElement, deps: ProposalsDeps): ProposalsView {
  const { api, store } = deps;
  const root = el("div", "settings jobs proposals");
  root.hidden = true;
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.setAttribute("aria-label", "Proposals");

  const side = el("nav", "settings-nav jobs-side");
  const sideHead = el("div", "settings-title pr-side-title");
  const sideTitle = el("h2", "", "Proposals");
  const tabSlot = el("div", "pr-tabs");
  sideHead.append(sideTitle, el("span", "caps hint", "Esc"), tabSlot);
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

  let tab: Tab = "proposals";
  const selected: Record<Tab, string | null> = { proposals: null, tools: null, procedures: null };
  let listing = true;
  let editing: string | null = null;

  let proposals: Proposal[] | null = null;
  const full = new Map<string, Proposal>();
  const previous = new Map<string, string | null>();
  let tools: MadeTool[] | null = null;
  let confinement: Confinement | null = null;
  const toolDetails = new Map<string, MadeToolDetail>();
  let procedures: ProcedureListing | null = null;
  const procFull = new Map<string, Procedure>();
  const problems = new Map<string, string>();
  let listProblem: string | null = null;
  let mainKey = "";

  const narrow = (): boolean => root.clientWidth <= NARROW_PX;
  const now = (): number => Date.now() / 1000;
  const st = (): ViewState => store.get();

  // ------------------------------------------------------------ loading

  const tookList = (list: ProposalList): void => {
    proposals = list.proposals;
    store.dispatch({ kind: "proposals", waiting: list.waiting });
  };

  /** On a wide scene, the first item of a tab is shown when none was chosen yet. */
  const firstOf = (t: Tab): string | null => {
    if (t === "proposals") return proposals ? (proposalRows(proposals)[0]?.id ?? null) : null;
    if (t === "tools") return tools ? (madeRows(tools)[0]?.name ?? null) : null;
    const group = procedures ? procedureGroups(procedures).groups[0] : undefined;
    const first = group?.procedures[0];
    return group && first ? procedureKey(group.owner, first.name) : null;
  };

  const loaded = (t: Tab): void => {
    if (tab === t && selected[t] === null && !narrow() && !root.hidden) {
      selected[t] = firstOf(t);
      if (selected[t] !== null) loadSelected();
    }
    render();
  };

  const loadProposals = async (): Promise<void> => {
    const r = await api.list();
    if (r.ok) tookList(r.value);
    else listProblem = r.message;
    loaded("proposals");
  };

  const loadTools = async (): Promise<void> => {
    const r = await api.tools();
    if (r.ok) {
      tools = r.value.tools;
      confinement = r.value.confinement;
    } else listProblem = r.message;
    loaded("tools");
  };

  const loadProcedures = async (): Promise<void> => {
    const r = await deps.procedures.list();
    if (r.ok) procedures = r.value;
    else listProblem = r.message;
    loaded("procedures");
  };

  const loadProposal = async (id: string): Promise<void> => {
    const r = await api.get(id);
    if (r.ok) {
      full.set(id, r.value);
      problems.delete(id);
      const tool = r.value.tool;
      if (tool && tool.replaces !== null) await loadPrevious(tool.name, tool.replaces);
    } else problems.set(id, r.message);
    render();
  };

  const loadPrevious = async (name: string, version: number): Promise<void> => {
    const key = `${name}@${version}`;
    if (previous.has(key)) return;
    const r = await api.tool(name);
    previous.set(key, r.ok ? (r.value.tool.versions.find((v) => v.version === version)?.script ?? null) : null);
  };

  const loadTool = async (name: string): Promise<void> => {
    const r = await api.tool(name);
    if (r.ok) {
      toolDetails.set(name, r.value);
      problems.delete(`tool:${name}`);
    } else problems.set(`tool:${name}`, r.message);
    render();
  };

  const loadProcedure = async (key: string): Promise<void> => {
    const [owner = "", name = ""] = key.split("/");
    const r = await deps.procedures.get(owner, name);
    if (r.ok) {
      procFull.set(key, r.value);
      problems.delete(`proc:${key}`);
    } else problems.set(`proc:${key}`, r.message);
    render();
  };

  const loadTab = (t: Tab): void => {
    listProblem = null;
    if (t === "proposals") void loadProposals();
    else if (t === "tools") void loadTools();
    else void loadProcedures();
    if (t === "proposals" && confinement === null) void loadTools();
  };

  const loadSelected = (): void => {
    const sel = selected[tab];
    if (sel === null) return;
    if (tab === "proposals") void loadProposal(sel);
    else if (tab === "tools") void loadTool(sel);
    else void loadProcedure(sel);
  };

  // ------------------------------------------------------------ drawing

  const drawTabs = (): void => {
    const waiting = proposals ? waitingCount(proposals) : (st().proposalsWaiting ?? 0);
    const tabs = segmented(
      "Show",
      (["proposals", "tools", "procedures"] as const).map((t) => ({ value: t, label: t === "proposals" && waiting > 0 ? `${TAB_TITLE[t]} ${waiting}` : TAB_TITLE[t] })),
      tab,
      (v) => show(v === "tools" ? "tools" : v === "procedures" ? "procedures" : "proposals"),
    );
    tabSlot.replaceChildren(tabs);
  };

  const renderList = (): void => {
    const sel = selected[tab];
    const t = now();
    const list =
      tab === "proposals"
        ? proposalList(proposals, sel, t, (id) => pick(id))
        : tab === "tools"
          ? madeList(tools, sel, t, (name) => pick(name))
          : procedureList(procedures, sel, t, (key) => pick(key));
    if (listProblem) list.prepend(el("li", "job-empty field-error", `Could not load: ${listProblem}`));
    listSlot.replaceChildren(list);
  };

  const emptyMain = (): void => {
    setText(kicker, "");
    setText(title, TAB_TITLE[tab]);
    setText(blurb, TAB_BLURB[tab]);
    body.replaceChildren();
  };

  const renderMain = (force = false): void => {
    const sel = selected[tab];
    root.dataset["pane"] = sel !== null && !listing ? "item" : "list";
    const node = tab === "proposals" ? proposalMain(sel) : tab === "tools" ? toolMain(sel) : procedureMain(sel);
    if (node === null) {
      mainKey = "";
      emptyMain();
      return;
    }
    if (!force && node.key === mainKey) return;
    mainKey = node.key;
    const keepScroll = node.same ? body.scrollTop : 0;
    body.replaceChildren(node.build());
    body.scrollTop = keepScroll;
  };

  interface MainNode {
    key: string;
    /** The same item as before: keep the scroll. */
    same: boolean;
    build(): HTMLElement;
  }

  const sameItem = (key: string): boolean => mainKey.startsWith(`${key}|`);

  const proposalMain = (id: string | null): MainNode | null => {
    const summary = proposals?.find((p) => p.id === id);
    if (!id || !summary) return null;
    const detail = full.get(id);
    const p = detail && detail.status === summary.status && detail.restored_at === summary.restored_at ? detail : summary;
    const tool = p.tool;
    const prev = tool && tool.replaces !== null ? (previous.get(`${tool.name}@${tool.replaces}`) ?? null) : null;
    setText(kicker, `${p.agent_name} · ${kindWord(p)}`);
    setText(title, p.title);
    setText(blurb, p.tool?.description ?? "");
    const room = namesFrom(st().plan).room(p.room);
    const key = `p:${id}|${JSON.stringify([p, p === detail, problems.get(id), confinement, prev])}`;
    return {
      key,
      same: sameItem(`p:${id}`),
      build: () =>
        proposalDetail({
          proposal: p,
          full: p === detail,
          problem: problems.get(id) ?? null,
          confinement,
          previous: prev,
          room,
          now: now(),
          act: {
            approve: async (b) => after(id, await api.approve(id, b)),
            decline: async (note) => after(id, await api.decline(id, note)),
            restore: async () => after(id, await api.restore(id)),
          },
        }),
    };
  };

  /** A decision went through: keep the answer, and refetch what it changed. */
  const after = (id: string, r: Awaited<ReturnType<ProposalsApi["approve"]>>): string | null => {
    if (!r.ok) return r.message;
    full.set(id, r.value);
    void loadProposals();
    void loadTools();
    return null;
  };

  const toolMain = (name: string | null): MainNode | null => {
    const tool = tools?.find((t) => t.name === name);
    if (!name || !tool) return null;
    setText(kicker, `Approved tool · ${tool.author_name}`);
    setText(title, tool.name);
    setText(blurb, tool.description);
    const detail = toolDetails.get(name) ?? null;
    const problem = problems.get(`tool:${name}`) ?? null;
    const changed = async (r: { ok: true } | { ok: false; message: string }): Promise<string | null> => {
      if (!r.ok) return r.message;
      await loadTools();
      await loadTool(name);
      return null;
    };
    return {
      key: `t:${name}|${JSON.stringify([tool, detail, problem, confinement])}`,
      same: sameItem(`t:${name}`),
      build: () =>
        toolDetail({
          tool,
          detail,
          problem,
          confinement,
          now: now(),
          act: {
            patch: async (patch) => changed(await api.patchTool(name, patch)),
            use: async (version) => changed(await api.useVersion(name, version)),
            remove: async () => {
              const r = await api.deleteTool(name);
              if (!r.ok) return r.message;
              selected.tools = null;
              toolDetails.delete(name);
              listing = true;
              await loadTools();
              return null;
            },
          },
        }),
    };
  };

  const procedureMain = (key: string | null): MainNode | null => {
    if (!key || !procedures) return null;
    const [owner = "", name = ""] = key.split("/");
    const agent = procedures.agents.find((a) => a.id === owner);
    const list = owner === SHARED ? procedures.shared : agent?.procedures;
    const summary = list?.find((p) => p.name === name);
    if (!summary) return null;
    const ownerName = owner === SHARED ? "Shared" : (agent?.name ?? owner);
    const authorName = procedures.agents.find((a) => a.id === summary.author)?.name ?? summary.author;
    setText(kicker, owner === SHARED ? "Shared procedure" : `${ownerName}'s procedure`);
    setText(title, summary.title);
    setText(blurb, "");
    const fullOne = procFull.get(key) ?? null;
    const problem = problems.get(`proc:${key}`) ?? null;
    const limits = procedures.limits;
    const isEditing = editing === key;
    return {
      key: `r:${key}|${JSON.stringify([summary, fullOne, problem, isEditing])}`,
      same: sameItem(`r:${key}`),
      build: () =>
        procedureDetail({
          summary,
          ownerName,
          authorName,
          full: fullOne,
          problem,
          limits,
          editing: isEditing,
          now: now(),
          act: {
            editing: (on) => {
              editing = on ? key : null;
              renderMain();
            },
            edit: async (edit) => {
              const r = await deps.procedures.edit(owner, name, edit);
              if (!r.ok) return r.message;
              procFull.set(key, r.value);
              editing = null;
              await loadProcedures();
              return null;
            },
            remove: async () => {
              const r = await deps.procedures.remove(owner, name);
              if (!r.ok) return r.message;
              selected.procedures = null;
              procFull.delete(key);
              listing = true;
              await loadProcedures();
              return null;
            },
          },
        }),
    };
  };

  function render(): void {
    if (root.hidden) return;
    setText(sideTitle, TAB_TITLE[tab]);
    drawTabs();
    renderList();
    // A procedure being edited is not redrawn under the owner's hands.
    if (editing !== null && tab === "procedures" && selected.procedures === editing && mainKey.startsWith(`r:${editing}|`) && body.querySelector("form")) return;
    renderMain();
  }

  // ------------------------------------------------------------ moving

  function pick(key: string): void {
    selected[tab] = key;
    listing = false;
    editing = null;
    render();
    loadSelected();
  }

  function show(t: Tab): void {
    if (t === tab) return;
    tab = t;
    editing = null;
    listing = selected[t] === null;
    render();
    loadTab(t);
    loadSelected();
  }

  const hide = (): boolean => {
    if (root.hidden) return false;
    root.hidden = true;
    editing = null;
    deps.onShown(false);
    if (root.contains(document.activeElement) && document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return true;
  };

  function back(): boolean {
    if (root.hidden) return false;
    if (editing !== null) {
      editing = null;
      renderMain(true);
      return true;
    }
    if (narrow() && !listing && selected[tab] !== null) {
      listing = true;
      renderMain(true);
      return true;
    }
    return hide();
  }

  backBtn.addEventListener("click", () => back());
  close.addEventListener("click", hide);
  // Keys typed here stay here: Space must not start push to talk, letters must not go to the message field.
  root.addEventListener("keydown", (ev) => {
    ev.stopPropagation();
    if (ev.key === "Escape") back();
  });

  // The count on the panel's control, after every (re)connect; events keep it current.
  const count = (): void =>
    void api.list().then((r) => {
      if (r.ok) tookList(r.value);
    });
  if (st().connection === "open") count();

  store.subscribe((s, prev) => {
    if (s.connection === "open" && prev.connection !== "open") count();
    if (root.hidden) return;
    if (s.proposalsRevision !== prev.proposalsRevision) {
      void loadProposals();
      if (tab === "proposals" && selected.proposals) void loadProposal(selected.proposals);
    }
    if (s.madeToolsRevision !== prev.madeToolsRevision) {
      void loadTools();
      if (tab === "tools" && selected.tools) void loadTool(selected.tools);
    }
    if (s.proceduresRevision !== prev.proceduresRevision) {
      void loadProcedures();
      if (tab === "procedures" && selected.procedures && editing === null) void loadProcedure(selected.procedures);
    }
    if (s.plan !== prev.plan) render();
  });

  return {
    open(t?: Tab): void {
      root.hidden = false;
      deps.onShown(true);
      if (t) tab = t;
      editing = null;
      listing = selected[tab] === null;
      mainKey = "";
      render();
      loadTab(tab);
      loadSelected();
      tabSlot.querySelector<HTMLElement>("[aria-checked='true']")?.focus();
    },
    back,
    close: hide,
    isOpen: () => !root.hidden,
  };
}
