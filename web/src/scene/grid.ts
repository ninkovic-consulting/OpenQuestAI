// Pure plan geometry, in grid units: which cell edges carry a wall, where the
// doors are, and where round towers stand. house.ts turns this into meshes.
//
// Grid: `x` runs east, `y` runs south; a room's `at` is its north-west cell.
// An edge is keyed by the cell it bounds: `h:x:y` is the north edge of cell
// (x, y) and `v:x:y` is its west edge. Every edge exists once, so a wall
// shared by two rooms is built once.

import type { Cell, Plan, Room, Side } from "../net/types";

export type Axis = "h" | "v";

export interface Edge {
  key: string;
  axis: Axis;
  x: number;
  y: number;
  /** Room north of an `h` edge or west of a `v` edge; null is outside. */
  a: string | null;
  /** Room south of an `h` edge or east of a `v` edge; null is outside. */
  b: string | null;
  exterior: boolean;
  door: boolean;
}

/** Collinear edges with the same rooms on both sides, merged into one wall. */
export interface WallRun {
  axis: Axis;
  /** The fixed coordinate: y for `h` runs, x for `v` runs. */
  line: number;
  from: number;
  to: number;
  a: string | null;
  b: string | null;
  exterior: boolean;
  /** Door centres along the run, in grid units. */
  doors: number[];
}

export interface Tower {
  room: Room;
  /** Centre, in grid units. */
  cx: number;
  cy: number;
  /** Radius, in grid units. */
  radius: number;
  doorSides: Side[];
}

export const cellKey = (x: number, y: number): string => `${x},${y}`;

export function roomCells(room: Room): Cell[] {
  const cells: Cell[] = [];
  for (let dy = 0; dy < room.size[1]; dy++)
    for (let dx = 0; dx < room.size[0]; dx++) cells.push([room.at[0] + dx, room.at[1] + dy]);
  return cells;
}

export function cellOwners(plan: Plan): Map<string, Room> {
  const owners = new Map<string, Room>();
  for (const room of plan.rooms) for (const [x, y] of roomCells(room)) owners.set(cellKey(x, y), room);
  return owners;
}

/** The edge on a given side of a cell. */
export function edgeOf(cell: Cell, side: Side): { key: string; axis: Axis; x: number; y: number } {
  const [x, y] = cell;
  switch (side) {
    case "n":
      return { key: `h:${x}:${y}`, axis: "h", x, y };
    case "s":
      return { key: `h:${x}:${y + 1}`, axis: "h", x, y: y + 1 };
    case "w":
      return { key: `v:${x}:${y}`, axis: "v", x, y };
    case "e":
      return { key: `v:${x + 1}:${y}`, axis: "v", x: x + 1, y };
  }
}

const SIDES: readonly Side[] = ["n", "e", "s", "w"];
const STEP: Record<Side, Cell> = { n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] };

/** Every wall edge of the plan. Round rooms build towers, not edges, but rect rooms still wall them off. */
export function wallEdges(plan: Plan): Map<string, Edge> {
  const owners = cellOwners(plan);
  const doorKeys = new Set(plan.doors.map((d) => edgeOf(d.cell, d.side).key));
  const edges = new Map<string, Edge>();
  for (const room of plan.rooms) {
    if (room.shape === "round") continue;
    for (const cell of roomCells(room)) {
      for (const side of SIDES) {
        const [dx, dy] = STEP[side];
        const other = owners.get(cellKey(cell[0] + dx, cell[1] + dy)) ?? null;
        if (other?.id === room.id) continue;
        const { key, axis, x, y } = edgeOf(cell, side);
        if (edges.has(key)) continue;
        const forward = side === "s" || side === "e";
        edges.set(key, {
          key,
          axis,
          x,
          y,
          a: forward ? room.id : (other?.id ?? null),
          b: forward ? (other?.id ?? null) : room.id,
          exterior: other === null || other.shape === "round",
          door: doorKeys.has(key),
        });
      }
    }
  }
  return edges;
}

/** Merge edges into straight wall runs, keeping door centres. */
export function wallRuns(plan: Plan): WallRun[] {
  const sorted = [...wallEdges(plan).values()].sort((p, q) =>
    p.axis !== q.axis ? (p.axis < q.axis ? -1 : 1) : lineOf(p) - lineOf(q) || posOf(p) - posOf(q),
  );
  const runs: WallRun[] = [];
  for (const edge of sorted) {
    const line = lineOf(edge);
    const pos = posOf(edge);
    const last = runs[runs.length - 1];
    const joins =
      last !== undefined &&
      last.axis === edge.axis &&
      last.line === line &&
      last.to === pos &&
      last.a === edge.a &&
      last.b === edge.b;
    const run = joins
      ? last
      : { axis: edge.axis, line, from: pos, to: pos, a: edge.a, b: edge.b, exterior: edge.exterior, doors: [] };
    run.to = pos + 1;
    if (edge.door) run.doors.push(pos + 0.5);
    if (!joins) runs.push(run);
  }
  return runs;
}

const lineOf = (e: Edge): number => (e.axis === "h" ? e.y : e.x);
const posOf = (e: Edge): number => (e.axis === "h" ? e.x : e.y);

/** Round rooms: a tower inscribed in the room's cells, with its door sides. */
export function towers(plan: Plan): Tower[] {
  const doorKeys = new Set(plan.doors.map((d) => edgeOf(d.cell, d.side).key));
  return plan.rooms
    .filter((r) => r.shape === "round")
    .map((room) => {
      const doorSides = SIDES.filter((side) => roomCells(room).some((c) => doorKeys.has(edgeOf(c, side).key)));
      return {
        room,
        cx: room.at[0] + room.size[0] / 2,
        cy: room.at[1] + room.size[1] / 2,
        radius: Math.min(room.size[0], room.size[1]) / 2,
        doorSides,
      };
    });
}

/** Grid-space bounds of the whole house. */
export function planBounds(plan: Plan): { minX: number; minY: number; maxX: number; maxY: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const r of plan.rooms) {
    minX = Math.min(minX, r.at[0]);
    minY = Math.min(minY, r.at[1]);
    maxX = Math.max(maxX, r.at[0] + r.size[0]);
    maxY = Math.max(maxY, r.at[1] + r.size[1]);
  }
  return { minX, minY, maxX, maxY };
}
