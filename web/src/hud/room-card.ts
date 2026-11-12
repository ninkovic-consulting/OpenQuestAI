// The card shown while the camera is inside a room: who runs it, on which
// model, which project folder, and its tools with what each can do today.

import type { Store, ViewState } from "../net/store";
import type { Plan } from "../net/types";
import { el } from "./dom";

/** Built-in tools run now; project tools wait for the next slice or for their program. */
export type ToolState = "runs" | "waits" | "missing";

const TOOL_WORD: Record<ToolState, string> = { runs: "runs today", waits: "next slice", missing: "not installed" };

export interface RoomCardModel {
  name: string;
  agent: string;
  model: string;
  project: string | null;
  tools: { title: string; state: ToolState }[];
  note: string;
}

export function roomCardModel(plan: Plan, roomId: string): RoomCardModel | null {
  const room = plan.rooms.find((r) => r.id === roomId);
  if (!room) return null;
  const agent = plan.agents.find((a) => a.id === room.agent);
  return {
    name: room.name,
    agent: agent?.name ?? room.agent,
    model: room.model,
    project: room.project,
    tools: room.tools.map((t) => ({ title: t.title, state: t.built_in ? "runs" : t.available ? "waits" : "missing" })),
    note: `Only ${plan.assistant.name}'s built-in tools run in this slice. Project tools start working when the other agents wake up.`,
  };
}

export interface RoomCard {
  /** Show the card for a room, or hide it with null. */
  show(roomId: string | null): void;
}

export function mountRoomCard(parent: HTMLElement, store: Store): RoomCard {
  const card = el("section", "room-card");
  card.setAttribute("aria-live", "polite");
  card.hidden = true;
  parent.append(card);
  let shown: string | null = null;

  const render = (s: ViewState): void => {
    const model = shown && s.plan ? roomCardModel(s.plan, shown) : null;
    card.hidden = model === null;
    if (!model) return;
    const row = (label: string, value: string, muted = false): HTMLElement => {
      const node = el("div", "row");
      node.append(el("dt", "caps", label), el("dd", muted ? "is-muted" : "", value));
      return node;
    };
    const facts = el("dl");
    facts.append(row("Agent", model.agent), row("Model", model.model), row("Project", model.project ?? "None", model.project === null));
    const tools = el("ul", "card-tools");
    tools.setAttribute("aria-label", "Tools");
    tools.append(
      ...model.tools.map((t) => {
        const item = el("li", `is-${t.state}`);
        item.append(el("span", t.state === "runs" ? "dot" : "dot hollow"), el("span", "title", t.title), el("span", "tag", TOOL_WORD[t.state]));
        return item;
      }),
    );
    if (model.tools.length === 0) tools.append(el("li", "is-empty", "No tools"));
    card.replaceChildren(el("div", "caps kicker", "Room"), el("h2", "", model.name), facts, el("div", "caps kicker", "Tools"), tools, el("p", "note", model.note));
  };

  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan) render(s);
  });
  return {
    show(roomId: string | null): void {
      shown = roomId;
      render(store.get());
    },
  };
}
