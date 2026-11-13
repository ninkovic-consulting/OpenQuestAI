// The card shown while the camera is inside a room: who runs it, on which
// model, which project folders, and its tools with what each can do today.

import type { Store, ViewState } from "../net/store";
import type { Plan, ToolRef } from "../net/types";
import { el } from "./dom";

/** Built-in tools always run; a project tool needs its program on this Mac and at least one project folder on the room. */
export type ToolState = "runs" | "waits" | "missing";

const TOOL_WORD: Record<ToolState, string> = { runs: "ready", waits: "needs a project folder", missing: "not installed" };

function toolState(tool: ToolRef, hasFolder: boolean): ToolState {
  if (tool.built_in) return "runs";
  if (!tool.available) return "missing";
  return hasFolder ? "runs" : "waits";
}

export interface RoomCardModel {
  name: string;
  agent: string;
  model: string;
  folders: string[];
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
    folders: [...room.folders],
    tools: room.tools.map((t) => ({ title: t.title, state: toolState(t, room.folders.length > 0) })),
    note: room.folders.length > 0
      ? "An agent working here reads and searches the project folders freely. Writing files and running these programs ask you first."
      : "Attach a project folder to this room and agents can work in it with these tools.",
  };
}

export interface RoomCard {
  /** Show the card for a room, or hide it with null. */
  show(roomId: string | null): void;
}

/** `onEdit` opens Settings, Rooms at the room shown. */
export function mountRoomCard(parent: HTMLElement, store: Store, onEdit: (roomId: string) => void): RoomCard {
  const card = el("section", "room-card");
  card.setAttribute("aria-live", "polite");
  card.hidden = true;
  parent.append(card);
  let shown: string | null = null;

  const render = (s: ViewState): void => {
    const model = shown && s.plan ? roomCardModel(s.plan, shown) : null;
    card.hidden = model === null;
    if (!model) return;
    const row = (label: string, value: string | string[], muted = false): HTMLElement => {
      const node = el("div", "row");
      const dd = el("dd", muted ? "is-muted" : "");
      if (typeof value === "string") dd.textContent = value;
      else dd.append(...value.map((path) => el("span", "path", path)));
      node.append(el("dt", "caps", label), dd);
      return node;
    };
    const facts = el("dl");
    facts.append(
      row("Agent", model.agent),
      row("Model", model.model),
      model.folders.length > 0 ? row(model.folders.length === 1 ? "Folder" : "Folders", model.folders) : row("Folders", "None", true),
    );
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
    const edit = el("button", "settings-toggle caps edit-room", "Edit room");
    edit.type = "button";
    const id = shown;
    edit.addEventListener("click", () => {
      if (id) onEdit(id);
    });
    card.replaceChildren(el("div", "caps kicker", "Room"), el("h2", "", model.name), facts, el("div", "caps kicker", "Tools"), tools, el("p", "note", model.note), edit);
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
