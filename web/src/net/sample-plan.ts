// The plan the real house backend serves for the repo's default house
// (house/default.toml), in the exact shape of spec 4.8. Mock mode and the
// tests use it, so mock mode looks like the real thing.

import type { Plan, Room, ToolRef } from "./types";

const HAIKU = "claude-haiku-5-5";
const OPUS = "claude-opus-5-5";

const builtIn = (id: string, title: string): ToolRef => ({ id, title, available: true, built_in: true });

/** The host's tools in house/default.toml: the assistant's five built-in tools. */
export const HOST_TOOLS: readonly ToolRef[] = [
  builtIn("remember", "Remember"),
  builtIn("recall", "Recall"),
  builtIn("open_app", "Open app"),
  builtIn("open_url", "Open link"),
  builtIn("shell", "Shell"),
];

function room(
  id: string,
  name: string,
  at: [number, number],
  size: [number, number],
  agent: string,
  model: string,
  floor: string,
  wall: string,
  state: Room["state"] = "dark",
  shape: Room["shape"] = "rect",
): Room {
  const tools = agent === "host" ? HOST_TOOLS.map((t) => ({ ...t })) : [];
  return { id, name, kind: "default", shape, at, size, agent, model, folders: [], floor, wall, tools, state };
}

export function samplePlan(): Plan {
  return {
    revision: 0,
    cell_m: 4.0,
    wall_height_m: 2.6,
    max_extra_rooms: 20,
    max_room_folders: 8,
    assistant: { name: "Vision" },
    agents: [
      { id: "host", name: "Vision", model: HAIKU, heavy_model: OPUS },
      { id: "steward", name: "Brass", model: HAIKU, heavy_model: null },
      { id: "envoy", name: "Wren", model: HAIKU, heavy_model: null },
      { id: "maker", name: "Tink", model: OPUS, heavy_model: null },
      { id: "checker", name: "Tock", model: HAIKU, heavy_model: OPUS },
      { id: "scout", name: "Rook", model: HAIKU, heavy_model: OPUS },
    ],
    rooms: [
      room("hall", "Hall", [1, 1], [2, 2], "host", HAIKU, "red-carpet", "teal-panel", "idle"),
      room("library", "Library", [0, 0], [1, 1], "steward", HAIKU, "wood-floor", "wallpaper"),
      room("control-room", "Control Room", [1, 0], [2, 1], "steward", HAIKU, "stone-tile", "teal-panel"),
      room("comms-room", "Comms Room", [3, 0], [1, 1], "envoy", HAIKU, "pale-stone", "wallpaper"),
      room("kitchen", "Kitchen", [0, 1], [1, 2], "maker", OPUS, "stone-tile", "pale-stone"),
      room("game-room", "Game Room", [3, 1], [1, 2], "maker", OPUS, "red-carpet", "wallpaper"),
      room("garage", "Garage", [0, 3], [1, 1], "maker", OPUS, "pale-stone", "stone-tile"),
      room("workshop", "Workshop", [1, 3], [2, 1], "maker", OPUS, "wood-floor", "pale-stone"),
      room("spare-room", "Spare Room", [3, 3], [1, 1], "checker", HAIKU, "wood-floor", "wallpaper"),
      room("attic", "Attic", [4, 0], [1, 1], "scout", HAIKU, "wood-floor", "roof-shingle", "dark", "round"),
    ],
    doors: [
      { a: "library", b: "control-room", cell: [0, 0], side: "e" },
      { a: "control-room", b: "hall", cell: [1, 0], side: "s" },
      { a: "comms-room", b: "control-room", cell: [3, 0], side: "w" },
      { a: "kitchen", b: "hall", cell: [0, 1], side: "e" },
      { a: "game-room", b: "hall", cell: [3, 1], side: "w" },
      { a: "garage", b: "kitchen", cell: [0, 3], side: "n" },
      { a: "workshop", b: "hall", cell: [1, 3], side: "n" },
      { a: "spare-room", b: "game-room", cell: [3, 3], side: "n" },
      { a: "attic", b: "comms-room", cell: [4, 0], side: "w" },
    ],
    free_slots: [
      [0, -1], [1, -1], [2, -1], [3, -1], [4, -1],
      [-1, 0], [5, 0], [-1, 1], [4, 1], [-1, 2],
      [4, 2], [-1, 3], [4, 3], [0, 4], [1, 4], [2, 4], [3, 4],
    ],
  };
}
