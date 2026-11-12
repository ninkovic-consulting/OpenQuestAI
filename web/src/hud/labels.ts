// Room labels over the scene. An active room gets a solid chip with a mustard
// border and a dot; idle rooms get a quieter translucent chip.

import type { Store, ViewState } from "../net/store";
import type { RoomAnchor } from "../scene/stage";
import { el, setText } from "./dom";

interface Chip {
  node: HTMLElement;
  text: HTMLElement;
}

export function mountLabels(parent: HTMLElement, store: Store): (anchors: RoomAnchor[]) => void {
  const layer = el("div", "labels");
  layer.setAttribute("aria-hidden", "true");
  parent.append(layer);
  const chips = new Map<string, Chip>();

  const style = (s: ViewState): void => {
    const plan = s.plan;
    if (!plan) return;
    for (const [id, chip] of chips) {
      if (!plan.rooms.some((r) => r.id === id)) {
        chip.node.remove();
        chips.delete(id);
      }
    }
    for (const room of plan.rooms) {
      let chip = chips.get(room.id);
      if (!chip) {
        const node = el("div", "chip caps");
        const text = el("span");
        node.append(el("span", "dot"), text);
        layer.append(node);
        chip = { node, text };
        chips.set(room.id, chip);
      }
      const light = s.roomLights[room.id] ?? room.state;
      const agent = plan.agents.find((a) => a.id === room.agent)?.name;
      const tower = room.shape === "round";
      setText(chip.text, (light === "active" || tower) && agent ? `${room.name} · ${agent}` : room.name);
      chip.node.classList.toggle("is-active", light === "active" && !tower);
      chip.node.classList.toggle("is-tower", tower);
      chip.node.classList.toggle("is-dark", light === "dark");
    }
  };
  style(store.get());
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan || s.roomLights !== prev.roomLights) style(s);
  });

  return (anchors) => {
    for (const a of anchors) {
      const chip = chips.get(a.id);
      if (!chip) continue;
      chip.node.style.visibility = a.visible ? "visible" : "hidden";
      chip.node.style.transform = `translate(${Math.round(a.x)}px, ${Math.round(a.y)}px) translate(-50%, -50%)`;
    }
  };
}
