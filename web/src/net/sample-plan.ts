// A sample plan in the exact shape of spec 4.8, for mock mode and tests.
// Neutral defaults only: these are the repo's original names.

import type { Plan, Room } from "./types";

function room(
  id: string,
  name: string,
  at: [number, number],
  size: [number, number],
  agent: string,
  floor: string,
  wall: string,
  state: Room["state"] = "idle",
  shape: Room["shape"] = "rect",
): Room {
  const model = agent === "maker" || agent === "checker" ? "claude-opus-5-5" : "claude-haiku-5-5";
  return { id, name, kind: "default", shape, at, size, agent, model, project: null, floor, wall, state };
}

export function samplePlan(): Plan {
  return {
    revision: 1,
    cell_m: 4.0,
    wall_height_m: 2.6,
    max_extra_rooms: 20,
    assistant: { name: "Vision" },
    agents: [
      { id: "host", name: "Vision", model: "claude-haiku-5-5", heavy_model: "claude-opus-5-5" },
      { id: "steward", name: "Brass", model: "claude-haiku-5-5" },
      { id: "envoy", name: "Wren", model: "claude-haiku-5-5" },
      { id: "maker", name: "Tink", model: "claude-opus-5-5" },
      { id: "checker", name: "Tock", model: "claude-opus-5-5" },
      { id: "scout", name: "Rook", model: "claude-haiku-5-5" },
    ],
    rooms: [
      room("hall", "Hall", [1, 1], [2, 2], "host", "red-carpet", "teal-panel", "active"),
      room("library", "Library", [0, 0], [1, 2], "steward", "wood-floor", "wallpaper"),
      room("study", "Study", [1, 0], [1, 1], "envoy", "wood-floor", "teal-panel"),
      room("parlour", "Parlour", [2, 0], [1, 1], "checker", "red-carpet", "wallpaper"),
      room("gallery", "Gallery", [3, 0], [1, 2], "checker", "wood-floor", "teal-panel"),
      room("kitchen", "Kitchen", [0, 2], [1, 2], "steward", "stone-tile", "wallpaper"),
      room("dining", "Dining Room", [1, 3], [2, 1], "envoy", "wood-floor", "wallpaper", "dark"),
      room("workshop", "Workshop", [3, 2], [1, 1], "maker", "wood-floor", "teal-panel"),
      room("garage", "Garage", [3, 3], [1, 1], "maker", "stone-tile", "teal-panel"),
      room("attic", "Attic", [4, 0], [1, 1], "scout", "stone-tile", "pale-stone", "idle", "round"),
    ],
    doors: [
      { a: "library", b: "hall", cell: [0, 1], side: "e" },
      { a: "study", b: "hall", cell: [1, 0], side: "s" },
      { a: "parlour", b: "hall", cell: [2, 0], side: "s" },
      { a: "gallery", b: "hall", cell: [3, 1], side: "w" },
      { a: "kitchen", b: "hall", cell: [0, 2], side: "e" },
      { a: "dining", b: "hall", cell: [2, 3], side: "n" },
      { a: "workshop", b: "hall", cell: [3, 2], side: "w" },
      { a: "garage", b: "workshop", cell: [3, 3], side: "n" },
      { a: "attic", b: "gallery", cell: [4, 0], side: "w" },
    ],
    free_slots: [
      [4, 1],
      [4, 2],
      [4, 3],
      [0, 4],
      [1, 4],
      [2, 4],
      [3, 4],
      [-1, 1],
      [-1, 2],
    ],
  };
}
