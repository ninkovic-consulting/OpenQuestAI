// The left panel: wordmark, state, residents, budget, and the build and settings toggles.
// The gate card mounts into its foot.

import { hostAgentId } from "../net/plan";
import type { Store, ViewState } from "../net/store";
import type { RoomLight } from "../net/types";
import { el, setText } from "./dom";
import { formatSpend } from "./money";

const LIGHT_WORD: Record<RoomLight, string> = { active: "working", idle: "idle", dark: "asleep" };

export interface Panel {
  root: HTMLElement;
  /** Where the gate card goes. */
  foot: HTMLElement;
  buildToggle: HTMLButtonElement;
  settingsToggle: HTMLButtonElement;
}

export function mountPanel(parent: HTMLElement, store: Store): Panel {
  const root = el("aside", "panel");
  const wordmark = el("h1", "wordmark");
  const state = el("div", "state caps");
  const stateDot = el("span", "dot");
  const stateText = el("span");
  const brain = el("span", "brain");
  const running = el("span", "automation-running");
  state.append(stateDot, stateText, brain, running);
  const residents = el("ul", "residents");
  residents.setAttribute("aria-label", "Residents");
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
  const settingsToggle = el("button", "settings-toggle caps", "Settings");
  settingsToggle.type = "button";
  settingsToggle.title = "Settings (⌘ ,)";
  const actions = el("div", "panel-actions");
  actions.append(buildToggle, settingsToggle);
  const foot = el("div", "gate-slot");
  root.append(wordmark, state, residents, budget, actions, el("div", "spacer"), foot);
  parent.append(root);

  let residentsKey = "";
  const render = (s: ViewState): void => {
    setText(wordmark, s.plan?.assistant.name ?? "");
    document.title = s.plan?.assistant.name ?? document.title;
    const offline = s.connection !== "open";
    setText(stateText, offline ? (s.connection === "connecting" ? "connecting" : "offline") : s.assistant);
    state.className = `state caps${offline ? " is-offline" : s.assistant === "idle" ? " is-idle" : ""}`;
    setText(brain, s.brain === "local" ? "local model" : "");
    setText(running, !offline && s.automation ? `automation: ${s.automation.name}` : "");
    running.title = s.automation ? `Running the automation "${s.automation.name}"` : "";

    const key = JSON.stringify([s.plan?.revision, s.plan?.agents, s.roomLights, s.assistant]);
    if (key !== residentsKey) {
      residentsKey = key;
      residents.replaceChildren(...residentRows(s));
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
  render(store.get());
  store.subscribe(render);
  return { root, foot, buildToggle, settingsToggle };
}

function residentRows(s: ViewState): HTMLElement[] {
  const plan = s.plan;
  if (!plan) return [];
  const host = hostAgentId(plan);
  return plan.agents.map((agent) => {
    const rooms = plan.rooms.filter((r) => r.agent === agent.id);
    const lights = rooms.map((r) => s.roomLights[r.id] ?? r.state);
    const light: RoomLight = lights.includes("active") ? "active" : lights.includes("idle") ? "idle" : "dark";
    const isHost = agent.id === host;
    const status = isHost ? s.assistant : LIGHT_WORD[light];
    const here = (isHost ? rooms.find((r) => r.id === "hall") : undefined) ?? rooms.find((r) => (s.roomLights[r.id] ?? r.state) === "active");
    const where = here ? here.name : rooms[0] ? rooms[0].name + (rooms.length > 1 ? ` +${rooms.length - 1}` : "") : "No room";
    const tower = rooms.some((r) => r.shape === "round");
    const row = el("li", "resident");
    row.classList.add(isHost ? "is-awake" : `is-${light === "dark" ? "asleep" : light}`);
    if (tower) row.classList.add("is-tower");
    const filled = isHost || light === "active" || tower;
    row.append(
      el("span", filled ? "dot" : "dot hollow"),
      el("span", "name caps", agent.name),
      el("span", "where", `${where}, ${status}`),
    );
    return row;
  });
}
