import { describe, expect, it } from "vitest";
import { samplePlan } from "../net/sample-plan";
import type { Plan, Room } from "../net/types";
import { edgeOf, planBounds, roomCells, towers, wallEdges, wallRuns, type Edge } from "./grid";

const between = (edges: Map<string, Edge>, p: string | null, q: string | null): Edge[] =>
  [...edges.values()].filter((e) => (e.a === p && e.b === q) || (e.a === q && e.b === p));

function withObservatory(plan: Plan): Plan {
  const room: Room = {
    id: "observatory",
    name: "Observatory",
    kind: "extra",
    shape: "rect",
    at: [4, 1],
    size: [1, 1],
    agent: "scout",
    model: "claude-haiku-5-5",
    folders: [],
    tools: [],
    floor: "wood-floor",
    wall: "wallpaper",
    state: "idle",
  };
  return {
    ...plan,
    revision: plan.revision + 1,
    rooms: [...plan.rooms, room],
    doors: [...plan.doors, { a: "observatory", b: "game-room", cell: [4, 1], side: "w" }],
  };
}

describe("wall edges", () => {
  const plan = samplePlan();
  const edges = wallEdges(plan);

  it("builds a wall shared by two rooms once", () => {
    expect(between(edges, "library", "control-room")).toHaveLength(1);
    expect(between(edges, "control-room", "hall")).toHaveLength(2);
    expect(between(edges, "kitchen", "hall")).toHaveLength(2);
    const keys = [...edges.values()].map((e) => e.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("walls every rect cell side that faces another room or the outside, and nothing inside a room", () => {
    for (const room of plan.rooms.filter((r) => r.shape === "rect")) {
      for (const cell of roomCells(room)) {
        for (const side of ["n", "e", "s", "w"] as const) {
          const key = edgeOf(cell, side).key;
          const [dx, dy] = ({ n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] } as const)[side];
          const sameRoom = roomCells(room).some(([x, y]) => x === cell[0] + dx && y === cell[1] + dy);
          expect(edges.has(key), `${room.id} ${cell} ${side}`).toBe(!sameRoom);
        }
      }
    }
  });

  it("marks walls to the outside as exterior and walls between rooms as interior", () => {
    expect(edges.get("v:0:0")).toMatchObject({ a: null, b: "library", exterior: true });
    expect(edges.get("h:1:4")).toMatchObject({ a: "workshop", b: null, exterior: true });
    expect(edges.get("v:3:1")).toMatchObject({ a: "hall", b: "game-room", exterior: false });
  });

  it("puts doors exactly where the plan says", () => {
    const doors = [...edges.values()].filter((e) => e.door).map((e) => e.key).sort();
    const expected = plan.doors.map((d) => edgeOf(d.cell, d.side).key).sort();
    expect(doors).toEqual(expected);
    const run = wallRuns(plan).find((r) => r.axis === "v" && r.line === 1 && r.a === "library" && r.b === "control-room");
    expect(run).toMatchObject({ from: 0, to: 1, doors: [0.5] });
  });

  it("merges collinear edges into runs and keeps door centres along them", () => {
    const hallWorkshop = wallRuns(plan).find((r) => r.a === "hall" && r.b === "workshop");
    expect(hallWorkshop).toMatchObject({ axis: "h", line: 3, from: 1, to: 3, doors: [1.5] });
    const north = wallRuns(plan).filter((r) => r.axis === "h" && r.line === 0 && r.a === null);
    expect(north.map((r) => [r.from, r.to, r.b])).toEqual([
      [0, 1, "library"],
      [1, 3, "control-room"],
      [3, 4, "comms-room"],
    ]);
  });
});

describe("round rooms", () => {
  const plan = samplePlan();

  it("become a tower with its door side instead of edge walls", () => {
    const [tower, ...rest] = towers(plan);
    expect(rest).toHaveLength(0);
    expect(tower).toMatchObject({ cx: 4.5, cy: 0.5, radius: 0.5, doorSides: ["w"] });
    expect(tower?.room.id).toBe("attic");
  });

  it("is walled off by its rect neighbour with stone, and has no other edges", () => {
    const edges = wallEdges(plan);
    expect(edges.get("v:4:0")).toMatchObject({ a: "comms-room", b: "attic", exterior: true, door: true });
    expect(between(edges, "attic", null)).toHaveLength(0);
  });

  it("counts towards the footprint", () => {
    expect(planBounds(plan)).toEqual({ minX: 0, minY: 0, maxX: 5, maxY: 4 });
  });
});

describe("adding a room", () => {
  it("changes only the walls around the new room", () => {
    const before = wallEdges(samplePlan());
    const after = wallEdges(withObservatory(samplePlan()));
    const changed = new Set<string>();
    for (const key of new Set([...before.keys(), ...after.keys()])) {
      if (JSON.stringify(before.get(key)) !== JSON.stringify(after.get(key))) changed.add(key);
    }
    const around = new Set(["n", "e", "s", "w"].map((s) => edgeOf([4, 1], s as "n").key));
    expect(changed.size).toBeGreaterThan(0);
    for (const key of changed) expect(around.has(key), key).toBe(true);
    expect(before.get("v:4:1")).toMatchObject({ a: "game-room", b: null, exterior: true });
    expect(after.get("v:4:1")).toMatchObject({ a: "game-room", b: "observatory", exterior: false, door: true });
    expect(after.get("h:4:1")).toMatchObject({ a: "attic", b: "observatory", exterior: true });
  });
});
