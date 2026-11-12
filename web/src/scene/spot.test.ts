import { describe, expect, it } from "vitest";
import { FloorGrid, type FloorShape } from "./floor";
import { chooseSpot, SPOT_NEEDS, type Point, type Spot, type SpotNeeds } from "./spot";

const CELL_M = 4;

function rect(cols: number, rows: number): FloorShape & { kind: "rect" } {
  return { kind: "rect", x0: 0.08, z0: 0.08, x1: cols * CELL_M - 0.08, z1: rows * CELL_M - 0.08 };
}

function needs(shape: FloorShape, doors: Point[], focus: Point | null = null): SpotNeeds {
  const centre = shape.kind === "rect" ? { x: (shape.x0 + shape.x1) / 2, z: (shape.z0 + shape.z1) / 2 } : { x: shape.cx, z: shape.cz };
  return { ...SPOT_NEEDS, doors, focus, centre };
}

/** A box of furniture: its footprint is blocked from the floor to `top`. */
function furniture(grid: FloorGrid, x0: number, z0: number, x1: number, z1: number, top = 0.8): void {
  // Two triangles of the top face, as the merged boxes carry them.
  grid.blockTriangles([x0, top, z0, x1, top, z0, x1, top, z1, x0, top, z0, x1, top, z1, x0, top, z1], null);
}

/** Distance from a spot to the nearest blocked cell's edge. */
function clearance(grid: FloorGrid, at: Point): number {
  let best = Infinity;
  for (let row = 0; row < grid.rows; row++)
    for (let col = 0; col < grid.cols; col++) {
      if (!grid.blocked[row * grid.cols + col]) continue;
      const [x, z] = grid.centre(col, row);
      best = Math.min(best, Math.hypot(Math.max(0, Math.abs(x - at.x) - 0.05), Math.max(0, Math.abs(z - at.z) - 0.05)));
    }
  return best;
}

function inside(shape: FloorShape, at: Point): boolean {
  return shape.kind === "rect"
    ? at.x > shape.x0 && at.x < shape.x1 && at.z > shape.z0 && at.z < shape.z1
    : Math.hypot(at.x - shape.cx, at.z - shape.cz) < shape.r;
}

function facingPoint(spot: Spot, target: Point): number {
  const want = Math.atan2(target.x - spot.x, target.z - spot.z);
  return Math.abs(Math.atan2(Math.sin(want - spot.facing), Math.cos(want - spot.facing)));
}

describe("chooseSpot", () => {
  it("stands clear of the walls, the door and the room's middle, facing into the room", () => {
    const shape = rect(1, 1);
    const grid = new FloorGrid(shape);
    const door = { x: 0, z: 2 };
    const n = needs(shape, [door]);
    const spot = chooseSpot(grid, n);
    expect(clearance(grid, spot)).toBeGreaterThanOrEqual(SPOT_NEEDS.body);
    expect(Math.hypot(spot.x - door.x, spot.z - door.z)).toBeGreaterThanOrEqual(SPOT_NEEDS.doorClear);
    expect(Math.hypot(spot.x - n.centre.x, spot.z - n.centre.z)).toBeGreaterThanOrEqual(SPOT_NEEDS.middleClear);
    // Away from the west door, so on the east side, looking back across the room.
    expect(spot.x).toBeGreaterThan(n.centre.x);
    expect(facingPoint(spot, n.centre)).toBeLessThan(1e-6);
  });

  it("works at the main piece: close to it, clear of it, facing it", () => {
    const shape = rect(2, 1);
    const grid = new FloorGrid(shape);
    furniture(grid, 2, 1.5, 6, 2.5);
    const focus = { x: 3, z: 2 };
    const spot = chooseSpot(grid, needs(shape, [{ x: 8, z: 2 }], focus));
    const gap = clearance(grid, spot);
    expect(gap).toBeGreaterThanOrEqual(SPOT_NEEDS.body);
    expect(gap).toBeLessThan(SPOT_NEEDS.body + 0.15);
    expect(Math.abs(spot.x - focus.x)).toBeLessThan(0.2);
    expect(facingPoint(spot, focus)).toBeLessThan(1e-6);
  });

  it("ignores what lies on the floor and what hangs overhead", () => {
    const grid = new FloorGrid(rect(1, 1));
    const before = Array.from(grid.blocked);
    furniture(grid, 0.5, 0.5, 3.5, 3.5, 0.02);
    furniture(grid, 0.5, 0.5, 3.5, 3.5, 2.4);
    expect(Array.from(grid.blocked)).toEqual(before);
  });

  it("keeps out of a second figure's way", () => {
    const shape = rect(1, 1);
    const n = needs(shape, [{ x: 0, z: 2 }]);
    const grid = new FloorGrid(shape);
    const first = chooseSpot(grid, n);
    grid.blockDisc(first.x, first.z, 0.35);
    const second = chooseSpot(grid, n);
    expect(Math.hypot(second.x - first.x, second.z - first.z)).toBeGreaterThanOrEqual(0.35 + SPOT_NEEDS.body);
  });

  it("stands inside the round tower, off its lamp and clear of its wall and door", () => {
    const shape: FloorShape = { kind: "round", cx: 18, cz: 2, r: 1.7 };
    const grid = new FloorGrid(shape);
    grid.blockDisc(18, 2, 0.55);
    const door = { x: 16, z: 2 };
    const spot = chooseSpot(grid, needs(shape, [door]));
    expect(inside(shape, spot)).toBe(true);
    expect(clearance(grid, spot)).toBeGreaterThanOrEqual(SPOT_NEEDS.body);
    expect(Math.hypot(spot.x - 18, spot.z - 2)).toBeLessThanOrEqual(1.7 - SPOT_NEEDS.body);
    expect(Math.hypot(spot.x - door.x, spot.z - door.z)).toBeGreaterThanOrEqual(SPOT_NEEDS.doorClear);
  });

  it("finds a clear spot in every extra room shape up to four cells, furnished or not", () => {
    for (const [cols, rows] of [[1, 1], [2, 1], [1, 2], [3, 1], [1, 3], [4, 1], [1, 4], [2, 2]] as const) {
      const shape = rect(cols, rows);
      for (const furnished of [false, true]) {
        const grid = new FloorGrid(shape);
        if (furnished) {
          furniture(grid, shape.x0, shape.z0, shape.x1, shape.z0 + 0.6);
          furniture(grid, shape.x0 + 0.1, shape.z1 - 0.6, shape.x0 + 0.6, shape.z1 - 0.1, 1.5);
        }
        const doors = [{ x: 0, z: 2 }, { x: cols * CELL_M - 2, z: rows * CELL_M }];
        const spot = chooseSpot(grid, needs(shape, doors, furnished ? { x: shape.x0 + 1, z: shape.z0 + 0.3 } : null));
        expect(inside(shape, spot), `${cols}x${rows}`).toBe(true);
        expect(clearance(grid, spot), `${cols}x${rows}`).toBeGreaterThanOrEqual(SPOT_NEEDS.body);
        for (const d of doors) expect(Math.hypot(spot.x - d.x, spot.z - d.z), `${cols}x${rows}`).toBeGreaterThanOrEqual(SPOT_NEEDS.doorClear);
      }
    }
  });

  it("relaxes its needs in a cramped room rather than standing in a wall", () => {
    const shape: FloorShape = { kind: "rect", x0: 0, z0: 0, x1: 0.8, z1: 0.8 };
    const grid = new FloorGrid(shape);
    const spot = chooseSpot(grid, needs(shape, [{ x: 0, z: 0.4 }]));
    expect(inside(shape, spot)).toBe(true);
    expect(clearance(grid, spot)).toBeGreaterThan(0.2);
  });
});

describe("FloorGrid", () => {
  it("blocks a wall face standing on a cell edge", () => {
    const grid = new FloorGrid(rect(1, 1));
    grid.blockTriangles([2, 0, 1, 2, 1, 1, 2, 1, 3], null);
    const col = Math.floor((2 - grid.x0) / 0.1);
    const row = Math.floor((2 - grid.z0) / 0.1);
    expect(grid.blocked[row * grid.cols + col]).toBe(1);
  });

  it("measures clearance to the nearest blocked cell", () => {
    const grid = new FloorGrid({ kind: "rect", x0: 0, z0: 0, x1: 3, z1: 3 });
    const clear = grid.clearance();
    expect(clear[15 * grid.cols + 15]).toBeCloseTo(1.45, 5);
    expect(clear[0]).toBeCloseTo(0.05, 5);
    grid.blockDisc(1.5, 1.5, 0.1);
    expect(grid.clearance()[15 * grid.cols + 18]).toBeCloseTo(0.25, 5);
  });
});
