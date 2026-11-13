// The rooms an agent runs, listed under its row in the left panel. A room's
// row does what a double-click on the room in the scene does.

import { el } from "../dom";
import { folderWords, ROOM_STATE_WORD, type AgentRoom } from "./model";

export function agentRoomList(rooms: AgentRoom[], agentName: string, focus: (roomId: string) => void): HTMLElement {
  const list = el("ul", "agent-rooms");
  list.setAttribute("aria-label", `${agentName}'s rooms`);
  if (rooms.length === 0) {
    list.append(el("li", "is-empty", `${agentName} runs no room.`));
    return list;
  }
  for (const room of rooms) {
    const b = el("button", `agent-room is-${room.state}${room.selected ? " is-selected" : ""}`);
    b.type = "button";
    b.dataset["focus"] = `r:${room.id}`;
    if (room.selected) b.setAttribute("aria-current", "true");
    const text = el("span", "agent-room-text");
    text.append(el("span", "agent-room-name", room.name), el("span", "agent-room-meta", `${folderWords(room.folders)} · ${ROOM_STATE_WORD[room.state]}`));
    b.append(el("span", room.state === "dark" || room.state === "idle" ? "dot hollow" : "dot"), text);
    b.addEventListener("click", () => focus(room.id));
    const item = el("li");
    item.append(b);
    list.append(item);
  }
  return list;
}
