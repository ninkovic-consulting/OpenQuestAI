// Room labels over the scene. An active room gets a solid chip with a mustard
// border and a dot; idle rooms get a quieter translucent chip. Chips never
// overlap: where two would, the more important room keeps its label.

import { hostRoom } from "../net/plan";
import type { Store, ViewState } from "../net/store";
import type { RoomAnchor } from "../scene/stage";
import { el, setText } from "./dom";

/** Clearance from the scene's edges; the top keeps clear of the key hints. */
const EDGE = 8;
const TOP = 52;
/** Space kept between two shown chips. */
const GAP = 4;

/** A chip's rectangle on screen, centred on (x, y). Lower ranks win overlaps. */
export interface LabelBox {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  rank: number;
}

/** The ids of the chips to show: in rank order, each chip that clears every chip already shown. */
export function resolveOverlaps(boxes: LabelBox[], gap = GAP): Set<string> {
  const shown: LabelBox[] = [];
  for (const b of [...boxes].sort((p, q) => p.rank - q.rank)) {
    const clear = shown.every((s) => Math.abs(s.x - b.x) * 2 >= s.w + b.w + gap * 2 || Math.abs(s.y - b.y) * 2 >= s.h + b.h + gap * 2);
    if (clear) shown.push(b);
  }
  return new Set(shown.map((b) => b.id));
}

/** Working rooms first, then the host's room, then larger rooms before smaller ones. */
function rank(active: boolean, host: boolean, area: number): number {
  return (active ? 0 : host ? 1 : 2) * 1e6 - area;
}

interface Chip {
  node: HTMLElement;
  text: HTMLElement;
  /** Measured size, refreshed when the text or style changes. */
  w: number;
  h: number;
  rank: number;
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
    const hostId = hostRoom(plan)?.id;
    for (const room of plan.rooms) {
      let chip = chips.get(room.id);
      if (!chip) {
        const node = el("div", "chip caps");
        const text = el("span");
        node.append(el("span", "dot"), text);
        layer.append(node);
        chip = { node, text, w: 0, h: 0, rank: 0 };
        chips.set(room.id, chip);
      }
      const light = s.roomLights[room.id] ?? room.state;
      // Whoever works there on a job now, else the room's own agent: a room can be lent for a job.
      const worker = Object.entries(s.agents).find(([, a]) => a.state !== "idle" && a.job !== null && s.jobs[a.job]?.room === room.id)?.[0];
      const agent = plan.agents.find((a) => a.id === (worker ?? room.agent))?.name;
      const tower = room.shape === "round";
      setText(chip.text, (light === "active" || tower) && agent ? `${room.name} · ${agent}` : room.name);
      chip.node.classList.toggle("is-active", light === "active" && !tower);
      chip.node.classList.toggle("is-tower", tower);
      chip.node.classList.toggle("is-dark", light === "dark");
      chip.rank = rank(light === "active", room.id === hostId, room.size[0] * room.size[1]);
    }
    for (const chip of chips.values()) {
      chip.w = chip.node.offsetWidth;
      chip.h = chip.node.offsetHeight;
    }
  };
  style(store.get());
  void document.fonts.ready.then(() => style(store.get()));
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan || s.roomLights !== prev.roomLights || s.agents !== prev.agents || s.jobs !== prev.jobs) style(s);
  });

  return (anchors) => {
    const width = layer.clientWidth;
    const height = layer.clientHeight;
    const boxes: LabelBox[] = [];
    for (const a of anchors) {
      const chip = chips.get(a.id);
      if (!chip) continue;
      chip.node.style.transform = `translate(${Math.round(a.x)}px, ${Math.round(a.y)}px) translate(-50%, -50%)`;
      // Only a chip that fits wholly inside the scene can show, so the panel edge never cuts one.
      const fits =
        a.x - chip.w / 2 >= EDGE && a.x + chip.w / 2 <= width - EDGE && a.y - chip.h / 2 >= TOP && a.y + chip.h / 2 <= height - EDGE;
      if (a.visible && fits) boxes.push({ id: a.id, x: a.x, y: a.y, w: chip.w, h: chip.h, rank: chip.rank });
    }
    const shown = resolveOverlaps(boxes);
    for (const [id, chip] of chips) chip.node.style.visibility = shown.has(id) ? "visible" : "hidden";
  };
}
