// The gate card: the oldest pending request, in carpet red, with a countdown
// to `expires_at` and two buttons that answer it.

import type { Daemon } from "../net/daemon";
import type { Store, ViewState } from "../net/store";
import { envelope, type GateRequest } from "../net/types";
import { el, setText } from "./dom";

export function mountGate(parent: HTMLElement, store: Store, daemon: Daemon): void {
  let shownId: string | null = null;
  let card: HTMLElement | null = null;
  let countdown: HTMLElement | null = null;
  let expiresAt = 0;

  const answer = (id: string, decision: "allow" | "deny"): void => {
    daemon.send(envelope("gate.decision", { id, decision }));
  };

  const build = (gate: GateRequest): HTMLElement => {
    const node = el("section", "gate");
    node.setAttribute("role", "alertdialog");
    node.setAttribute("aria-label", "Needs your yes");
    const head = el("div", "gate-head caps");
    countdown = el("span");
    head.append(el("span", "", "Needs your yes"), countdown);
    const summary = el("p", "gate-summary", gate.summary || gate.tool);
    const detail = el("pre", "gate-detail", gate.detail);
    detail.hidden = gate.detail === "";
    const actions = el("div", "gate-actions");
    const yes = el("button", "yes caps", "Yes");
    const no = el("button", "no caps", "Not now");
    yes.type = no.type = "button";
    yes.addEventListener("click", () => answer(gate.id, "allow"));
    no.addEventListener("click", () => answer(gate.id, "deny"));
    actions.append(yes, no);
    node.append(head, summary, detail, actions);
    return node;
  };

  const render = (s: ViewState): void => {
    const gate = s.gates[0] ?? null;
    if ((gate?.id ?? null) === shownId) return;
    card?.remove();
    card = null;
    shownId = gate?.id ?? null;
    if (gate) {
      expiresAt = gate.expires_at;
      card = build(gate);
      parent.append(card);
      tick();
    }
  };

  const tick = (): void => {
    if (!countdown) return;
    const left = Math.max(0, Math.round(expiresAt - Date.now() / 1000));
    setText(countdown, `${left}s`);
  };

  setInterval(tick, 250);
  render(store.get());
  store.subscribe(render);
}
