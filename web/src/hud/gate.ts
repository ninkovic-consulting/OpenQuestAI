// The gate card: the oldest pending request, in carpet red, with who asks,
// a countdown to `expires_at` and two buttons that answer it. More requests
// wait behind it, answered one by one, oldest first. The detail (an exact
// command and its folder, a file preview) is preformatted and scrolls inside
// the card.

import type { Daemon } from "../net/daemon";
import type { Store, ViewState } from "../net/store";
import { envelope, type GateRequest } from "../net/types";
import { el, setText } from "./dom";

export interface GateCard {
  gate: GateRequest;
  /** "Tink, in the Workshop" when a resident asks during a job; empty for the host's own requests. */
  who: string;
  /** The daemon's summary without the `who: ` it starts with. */
  summary: string;
  /** How many more requests wait behind this one. */
  more: number;
}

/** What the card shows: the request that arrived first, and how many wait after it. */
export function gateCard(s: Pick<ViewState, "gates" | "jobs" | "plan">): GateCard | null {
  const gate = s.gates[0];
  if (!gate) return null;
  const job = gate.job ? s.jobs[gate.job] : undefined;
  const room = job?.room ? s.plan?.rooms.find((r) => r.id === job.room)?.name : undefined;
  const name = gate.agent_name ?? (gate.agent ? (s.plan?.agents.find((a) => a.id === gate.agent)?.name ?? gate.agent) : null);
  const who = name ? `${name}${room ? `, in the ${room}` : ""}` : "";
  const prefix = name ? new RegExp(`^${escape(name)}(, in the [^:]+)?: `) : null;
  const rest = prefix ? gate.summary.replace(prefix, "") : gate.summary;
  const summary = rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : gate.tool;
  return { gate, who, summary, more: s.gates.length - 1 };
}

const escape = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function mountGate(parent: HTMLElement, store: Store, daemon: Daemon): void {
  let shownId: string | null = null;
  let card: HTMLElement | null = null;
  let countdown: HTMLElement | null = null;
  let queue: HTMLElement | null = null;
  let shownMore = -1;
  let expiresAt = 0;

  const answer = (id: string, decision: "allow" | "deny"): void => {
    daemon.send(envelope("gate.decision", { id, decision }));
  };

  const build = (c: GateCard): HTMLElement => {
    const { gate } = c;
    const node = el("section", "gate");
    node.setAttribute("role", "alertdialog");
    node.setAttribute("aria-label", c.who ? `${c.who} needs your yes` : "Needs your yes");
    const head = el("div", "gate-head caps");
    countdown = el("span");
    head.append(el("span", "", "Needs your yes"), countdown);
    node.append(head);
    if (c.who) node.append(el("p", "gate-who caps", c.who));
    const summary = el("p", "gate-summary", c.summary);
    const detail = el("pre", "gate-detail", gate.detail);
    detail.hidden = gate.detail === "";
    detail.tabIndex = 0;
    const actions = el("div", "gate-actions");
    const yes = el("button", "yes caps", "Yes");
    const no = el("button", "no caps", "Not now");
    yes.type = no.type = "button";
    yes.addEventListener("click", () => answer(gate.id, "allow"));
    no.addEventListener("click", () => answer(gate.id, "deny"));
    actions.append(yes, no);
    queue = el("p", "gate-queue caps");
    node.append(summary, detail, actions, queue);
    return node;
  };

  const render = (s: ViewState): void => {
    const c = gateCard(s);
    const fresh = (c?.gate.id ?? null) !== shownId;
    if (fresh) {
      card?.remove();
      card = null;
      shownId = c?.gate.id ?? null;
      if (c) {
        expiresAt = c.gate.expires_at;
        card = build(c);
        parent.append(card);
        tick();
      }
    }
    const more = c?.more ?? 0;
    if (!queue || !card || (!fresh && more === shownMore)) return;
    shownMore = more;
    setText(queue, more > 0 ? `${more} more ${more === 1 ? "request waits" : "requests wait"} after this one` : "");
    queue.hidden = more === 0;
    // A short window scrolls the panel: the request that needs an answer comes into view, whole.
    card.scrollIntoView({ block: "nearest" });
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
