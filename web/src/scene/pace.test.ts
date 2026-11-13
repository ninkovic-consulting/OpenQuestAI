import { describe, expect, it } from "vitest";
import { samplePlan } from "../net/sample-plan";
import { FloorGrid } from "./floor";
import { DWELL_S, paceAt, TURN_S } from "./pace";
import { residenceOf } from "./residence";
import { choosePace, PACE, SPOT_NEEDS, type Spot } from "./spot";

const a: Spot = { x: 0, z: 0, facing: Math.PI };
const b: Spot = { x: 2, z: 0, facing: 0 };
const speed = 1;

describe("pacing", () => {
  it("works at the first spot facing its work, then turns and walks at the walk's speed", () => {
    const working = paceAt(a, b, TURN_S, speed);
    expect(working).toMatchObject({ x: 0, z: 0, walking: false });
    expect(Math.cos(working.facing)).toBeCloseTo(-1);
    const setOff = paceAt(a, b, DWELL_S + TURN_S / 2, speed);
    expect(setOff).toMatchObject({ x: 0, z: 0, walking: true });
    const half = paceAt(a, b, DWELL_S + TURN_S + 1, speed);
    expect(half.x).toBeCloseTo(1);
    expect(half.facing).toBeCloseTo(Math.PI / 2);
    expect(half.walking).toBe(true);
  });

  it("works at the other end, walks back, and loops", () => {
    const leg = TURN_S + 2;
    expect(paceAt(a, b, DWELL_S + leg + TURN_S, speed)).toMatchObject({ x: 2, z: 0, walking: false });
    const back = paceAt(a, b, 2 * DWELL_S + leg + TURN_S + 1, speed);
    expect(back.x).toBeCloseTo(1);
    expect(back.facing).toBeCloseTo(-Math.PI / 2);
    const period = 2 * (DWELL_S + leg);
    expect(paceAt(a, b, period + 1, speed)).toEqual(paceAt(a, b, 1, speed));
  });

  it("finds a clear second spot about the right distance away, and none in a cramped room", () => {
    const shape = { kind: "rect" as const, x0: 0, z0: 0, x1: 4, z1: 4 };
    const needs = { ...SPOT_NEEDS, doors: [], focus: null, centre: { x: 2, z: 2 } };
    const end = choosePace(new FloorGrid(shape), { x: 1, z: 1 }, needs);
    expect(end).not.toBeNull();
    const d = Math.hypot((end?.x ?? 0) - 1, (end?.z ?? 0) - 1);
    expect(d).toBeGreaterThanOrEqual(PACE.min);
    expect(d).toBeLessThanOrEqual(PACE.max);
    expect(choosePace(new FloorGrid({ kind: "rect", x0: 0, z0: 0, x1: 1.2, z1: 1.2 }), { x: 0.6, z: 0.6 }, needs)).toBeNull();
  });
});

describe("where a resident on a job stands", () => {
  const board = (room: string, state: "working" | "waiting" | "idle" = "working") => ({
    agents: { checker: { state, job: state === "idle" ? null : "j1" } },
    jobs: {
      j1: { id: "j1", title: "t", agent: "checker", room, status: "working" as const, asked_by: "host", parent: null, created_at: 0, started_at: 0, ended_at: null, needed_approval: false, last_step: null },
    },
  });

  it("is the job's room, even another resident's, and home again when idle", () => {
    const plan = samplePlan();
    expect(residenceOf(plan, "checker", {}, board("workshop"))).toMatchObject({ room: { id: "workshop" }, work: "working" });
    expect(residenceOf(plan, "checker", {}, board("workshop", "waiting"))?.work).toBe("waiting");
    expect(residenceOf(plan, "checker", {}, board("workshop", "idle"))).toMatchObject({ room: { id: "spare-room" }, work: "idle" });
  });
});
