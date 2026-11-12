// Room labels over the scene. An active room gets a solid chip with a mustard
// border and a dot; idle rooms get a quieter translucent chip.

import type { Store, ViewState } from "../net/store";
import type { RoomAnchor } from "../scene/stage";
import { el, setText } from "./dom";

/** Clearance from the scene's edges; the top keeps clear of the key hints. */
const EDGE = 8;
const TOP = 52;

interface Chip {
  node: HTMLElement;
  text: HTMLElement;
  /** Measured size, refreshed when the text or style changes. */
  w: number;
  h: number;
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
        chip = { node, text, w: 0, h: 0 };
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
    for (const chip of chips.values()) {
      chip.w = chip.node.offsetWidth;
      chip.h = chip.node.offsetHeight;
    }
  };
  style(store.get());
  void document.fonts.ready.then(() => style(store.get()));
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan || s.roomLights !== prev.roomLights) style(s);
  });

  return (anchors) => {
    const width = layer.clientWidth;
    const height = layer.clientHeight;
    for (const a of anchors) {
      const chip = chips.get(a.id);
      if (!chip) continue;
      // Hidden unless the whole chip fits inside the scene, so the panel edge never cuts one.
      const fits =
        a.x - chip.w / 2 >= EDGE && a.x + chip.w / 2 <= width - EDGE && a.y - chip.h / 2 >= TOP && a.y + chip.h / 2 <= height - EDGE;
      chip.node.style.visibility = a.visible && fits ? "visible" : "hidden";
      chip.node.style.transform = `translate(${Math.round(a.x)}px, ${Math.round(a.y)}px) translate(-50%, -50%)`;
    }
  };
}
