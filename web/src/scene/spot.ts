// Where a figure stands in its room and which way it faces. With a main
// piece of furniture it stands at the clear spot nearest to it, facing it;
// without one it stands well clear of walls and doors, facing into the room.
// The middle of the room stays clear too: the room's name hangs above it.

import type { FloorGrid } from "./floor";

export interface Point {
  x: number;
  z: number;
}

export interface Spot extends Point {
  /** Turn about the vertical, in radians; 0 faces south (+z), as the models do. */
  facing: number;
}

export interface SpotNeeds {
  /** Clear floor wanted all round the figure, in metres. */
  body: number;
  /** Door centres, kept clear so nobody stands in a doorway. */
  doors: readonly Point[];
  doorClear: number;
  /** Kept clear around the middle of the room, under its label. */
  middleClear: number;
  /** The main built piece, if the room has one. */
  focus: Point | null;
  /** The middle of the room. */
  centre: Point;
}

export const SPOT_NEEDS = { body: 0.45, doorClear: 1.3, middleClear: 1.0 } as const;

/** How far from the walls a figure without a piece to work at likes to stand. */
const ROOMY = 1.2;
/** How much clearance counts against distance from the doors, without a piece. */
const ROOMY_WEIGHT = 1.5;
const DOOR_CAP = 3;

/**
 * The spot for a figure on `grid`. When nothing meets the needs they are
 * relaxed step by step; a room with no clear floor at all gets its centre.
 */
export function chooseSpot(grid: FloorGrid, needs: SpotNeeds): Spot {
  const clear = grid.clearance();
  for (const k of [1, 0.75, 0.5]) {
    for (const d of [1, 0.6, 0]) {
      const best = pick(grid, clear, needs, { body: needs.body * k, door: needs.doorClear * d, middle: needs.middleClear * d });
      if (best) return face(best, needs);
    }
  }
  return face(needs.centre, needs);
}

function pick(grid: FloorGrid, clear: Float32Array, needs: SpotNeeds, min: { body: number; door: number; middle: number }): Point | null {
  let best: Point | null = null;
  let bestScore = -Infinity;
  for (let row = 0; row < grid.rows; row++)
    for (let col = 0; col < grid.cols; col++) {
      const c = clear[row * grid.cols + col] ?? 0;
      if (c < min.body) continue;
      const [x, z] = grid.centre(col, row);
      if (Math.hypot(needs.centre.x - x, needs.centre.z - z) < min.middle) continue;
      const door = Math.min(DOOR_CAP, ...needs.doors.map((d) => Math.hypot(d.x - x, d.z - z)));
      if (door < min.door) continue;
      const score = needs.focus
        ? -Math.hypot(needs.focus.x - x, needs.focus.z - z) + c * 1e-3
        : door + ROOMY_WEIGHT * Math.min(c, ROOMY);
      if (score > bestScore) {
        bestScore = score;
        best = { x, z };
      }
    }
  return best;
}

/** Face the piece, or the middle of the room; straight south when standing on the point itself. */
function face(at: Point, needs: SpotNeeds): Spot {
  const target = needs.focus ?? needs.centre;
  const dx = target.x - at.x;
  const dz = target.z - at.z;
  return { x: at.x, z: at.z, facing: Math.hypot(dx, dz) < 0.3 ? 0 : Math.atan2(dx, dz) };
}
