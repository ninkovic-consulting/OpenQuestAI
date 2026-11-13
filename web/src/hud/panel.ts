// The left panel: wordmark, state, residents, budget, and the build, jobs,
// proposals and settings toggles, two to a row, then Minimize and Quit when
// the Mac app offers them. The gate card mounts into its foot.

import type { AgentWork } from "../net/job-types";
import { hostAgentId } from "../net/plan";
import type { Store, ViewState } from "../net/store";
import { residenceOf } from "../scene/residence";
import { el, setText } from "./dom";
import { runningCount } from "./jobs/model";
import { formatSpend } from "./money";
import { offlineMark, offlineTitle } from "./mode";
import { makeQuit } from "./quit";
import { makeMinimize } from "./minimize";
import { agentRoomList } from "./rooms/agent-rooms";
import { keepKeys } from "./rooms/keep-keys";
import { agentRooms, agentToOpen, selectionIn, type AgentRoom } from "./rooms/model";
import type { RoomSelection } from "./rooms/selection";

export interface Panel {
  root: HTMLElement;
  /** Where the gate card goes. */
  foot: HTMLElement;
  /** Under the state: where the quick listening control and the offline switch go. */
  modeSlot: HTMLElement;
  buildToggle: HTMLButtonElement;
  jobsToggle: HTMLButtonElement;
  /** Opens the Proposals view; its count is the proposals waiting for the owner. */
  proposalsToggle: HTMLButtonElement;
  settingsToggle: HTMLButtonElement;
}

/** The rooms of the house as the panel offers them: the one chosen, and how to go into one. */
export interface Rooms {
  selection: RoomSelection;
  /** Flies the camera into the room and opens its card: the same as a double-click in the scene. */
  focus(roomId: string): void;
}

export function mountPanel(parent: HTMLElement, store: Store, rooms: Rooms): Panel {
  const root = el("aside", "panel");
  const wordmark = el("h1", "wordmark");
  const state = el("div", "state caps");
  const stateDot = el("span", "dot");
  const stateText = el("span");
  const brain = el("span", "brain");
  const running = el("span", "automation-running");
  const modeMark = el("span", "mode-mark");
  state.append(stateDot, stateText, brain, modeMark, running);
  const modeSlot = el("div", "mode-slot");
  const residents = el("ul", "residents");
  residents.setAttribute("aria-label", "Residents");
  keepKeys(residents);
  const budget = el("section", "budget");
  const budgetRow = el("div", "budget-row caps");
  const budgetAmount = el("span", "amount");
  budgetRow.append(el("span", "", "This month"), budgetAmount);
  const bar = el("div", "budget-bar");
  const barFill = el("span");
  bar.append(barFill);
  budget.append(budgetRow, bar);
  const buildToggle = el("button", "build-toggle caps", "Build");
  buildToggle.type = "button";
  const jobsToggle = el("button", "jobs-toggle caps", "Jobs");
  jobsToggle.type = "button";
  const jobsCount = el("span", "count");
  jobsToggle.append(jobsCount);
  const proposalsToggle = el("button", "proposals-toggle caps", "Proposals");
  proposalsToggle.type = "button";
  const proposalsCount = el("span", "count");
  proposalsToggle.append(proposalsCount);
  const settingsToggle = el("button", "settings-toggle caps", "Settings");
  settingsToggle.type = "button";
  settingsToggle.title = "Settings (⌘ ,)";
  const quit = makeQuit();
  const minimize = makeMinimize();
  const actions = el("div", "panel-actions");
  actions.append(buildToggle, jobsToggle, proposalsToggle, settingsToggle, minimize.button, quit.button);
  const foot = el("div", "gate-slot");
  root.append(wordmark, state, modeSlot, residents, budget, actions, quit.confirm, el("div", "spacer"), foot);
  parent.append(root);

  let residentsKey = "";
  /** The agent whose rooms are listed; one at a time. */
  let open: string | null = null;
  const render = (s: ViewState): void => {
    setText(wordmark, s.plan?.assistant.name ?? "");
    document.title = s.plan?.assistant.name ?? document.title;
    quit.sync(s.plan?.assistant.name ?? "");
    minimize.sync();
    const offline = s.connection !== "open";
    setText(stateText, offline ? (s.connection === "connecting" ? "connecting" : "offline") : s.assistant);
    state.className = `state caps${offline ? " is-offline" : s.assistant === "idle" ? " is-idle" : ""}`;
    const mark = !offline && s.mode ? offlineMark(s.mode) : null;
    setText(modeMark, mark ?? "");
    modeMark.title = mark && s.mode ? offlineTitle(s.mode) : "";
    setText(brain, mark === null && s.brain === "local" ? "local model" : "");
    setText(running, !offline && s.automation ? `automation: ${s.automation.name}` : "");
    running.title = s.automation ? `Running the automation "${s.automation.name}"` : "";

    const working = runningCount(s.jobs);
    setText(jobsCount, working > 0 ? String(working) : "");
    jobsToggle.title = working > 0 ? `${working} ${working === 1 ? "job" : "jobs"} running` : "Jobs";
    const waiting = s.proposalsWaiting ?? 0;
    setText(proposalsCount, waiting > 0 ? String(waiting) : "");
    proposalsToggle.title = waiting > 0 ? `${waiting} ${waiting === 1 ? "proposal waits" : "proposals wait"} for you` : "Proposals, approved tools and procedures";

    const selected = selectionIn(s.plan, rooms.selection.get());
    const listed = open && s.plan ? agentRooms(s.plan, open, s, s.roomLights, selected) : [];
    const key = JSON.stringify([s.plan?.revision, s.plan?.agents, s.roomLights, s.assistant, s.agents, workTitles(s), open, selected, listed]);
    if (key !== residentsKey) {
      residentsKey = key;
      const back = residents.contains(document.activeElement) ? (document.activeElement as HTMLElement).dataset["focus"] : undefined;
      residents.replaceChildren(...residentRows(s, { open, listed, toggle, focus: rooms.focus }));
      if (back) residents.querySelector<HTMLElement>(`[data-focus="${back}"]`)?.focus();
    }

    if (s.budget) {
      const share = s.budget.cap_usd > 0 ? s.budget.spent_usd / s.budget.cap_usd : 1;
      setText(budgetAmount, `${formatSpend(s.budget.spent_usd)} of $${s.budget.cap_usd.toFixed(0)}`);
      barFill.style.width = `${Math.min(100, share * 100).toFixed(1)}%`;
      budget.classList.toggle("is-high", share >= 0.8);
      budget.hidden = false;
    } else {
      budget.hidden = true;
    }
  };
  const toggle = (agent: string): void => {
    open = open === agent ? null : agent;
    render(store.get());
  };
  rooms.selection.subscribe((id) => {
    open = agentToOpen(store.get().plan, selectionIn(store.get().plan, id), open);
    render(store.get());
  });
  render(store.get());
  store.subscribe(render);
  return { root, foot, modeSlot, buildToggle, jobsToggle, proposalsToggle, settingsToggle };
}

const WORK_WORD: Record<AgentWork, string> = { idle: "idle", working: "working", waiting: "waiting for your yes" };

/** The titles of the jobs residents are on, so a renamed job redraws its row. */
function workTitles(s: ViewState): string[] {
  return Object.values(s.agents).map((a) => (a.job ? (s.jobs[a.job]?.title ?? "") : ""));
}

interface RowActions {
  open: string | null;
  /** The open agent's rooms. */
  listed: AgentRoom[];
  toggle(agent: string): void;
  focus(roomId: string): void;
}

function residentRows(s: ViewState, act: RowActions): HTMLElement[] {
  const plan = s.plan;
  if (!plan) return [];
  const host = hostAgentId(plan);
  return plan.agents.map((agent) => {
    const rooms = plan.rooms.filter((r) => r.agent === agent.id);
    const isHost = agent.id === host;
    const home = residenceOf(plan, agent.id, s.roomLights, s);
    const work: AgentWork = isHost ? "idle" : (home?.work ?? "idle");
    const busy = work !== "idle";
    const here = isHost ? rooms.find((r) => r.id === "hall") : busy || home?.light === "active" ? home?.room : undefined;
    const where = here ? here.name : rooms[0] ? rooms[0].name + (rooms.length > 1 ? ` +${rooms.length - 1}` : "") : "No room";
    const status = isHost ? s.assistant : WORK_WORD[work];
    const tower = rooms.some((r) => r.shape === "round");
    const row = el("li", "resident");
    row.classList.add(isHost ? "is-awake" : `is-${work}`);
    if (tower) row.classList.add("is-tower");
    const filled = isHost || busy || tower;
    const line = el("span", "where", `${where}, ${status}`);
    if (work === "working" && home?.job) line.append(el("span", "job-title", home.job.title));
    const head = el("button", "resident-row");
    head.type = "button";
    head.dataset["focus"] = `a:${agent.id}`;
    head.setAttribute("aria-expanded", String(act.open === agent.id));
    head.append(el("span", filled ? "dot" : "dot hollow"), el("span", "name caps", agent.name), line);
    head.addEventListener("click", () => act.toggle(agent.id));
    row.append(head);
    if (act.open === agent.id) row.append(agentRoomList(act.listed, agent.name, act.focus));
    return row;
  });
}
