import { describe, expect, it } from "vitest";
import { EASE_STEP, easeRatio, FRESH, scaleStep, STEP, type ScalerState } from "./scaler";

const BUDGET = 1000 / 60;
const VSYNC = 1000 / 120;
const MIN = 0.7;

/** A GPU whose frame cost grows with the pixels drawn; the next tick lands on the display's grid. */
const measured = (costAtFull: number, scale: number): number => Math.max(1, Math.ceil((costAtFull * scale * scale) / VSYNC)) * VSYNC;

/** Run `frames` frames at a steady cost; answers the scales seen and how often the direction reversed. */
function run(costAtFull: number | ((frame: number) => number), frames: number, from: ScalerState = FRESH): { s: ScalerState; reversals: number; changes: number } {
  let s = from;
  let last = 0;
  let reversals = 0;
  let changes = 0;
  for (let i = 0; i < frames; i++) {
    const cost = typeof costAtFull === "number" ? costAtFull : costAtFull(i);
    const before = s.scale;
    s = scaleStep(s, measured(cost, s.scale), BUDGET, MIN);
    const dir = Math.sign(s.scale - before);
    if (dir !== 0) {
      changes++;
      if (last !== 0 && dir !== last) reversals++;
      last = dir;
    }
  }
  return { s, reversals, changes };
}

describe("the resolution scaler", () => {
  it("leaves a scene that fits its budget alone", () => {
    const { s, changes } = run(12, 5000);
    expect(s.scale).toBe(1);
    expect(changes).toBe(0);
  });

  it("steps down when frames stay late, and stops at its floor", () => {
    const { s } = run(60, 2000);
    expect(s.scale).toBe(MIN);
  });

  it("steps down only as far as needed", () => {
    // 20 ms at full size: one step (×0.72 of the pixels) brings it to 14.4 ms.
    const { s } = run(20, 3000);
    expect(s.scale).toBeCloseTo(STEP);
  });

  it("does not flip between two sizes on a load near the edge", () => {
    const { reversals, s } = run(20, 40_000);
    expect(s.scale).toBeLessThan(1);
    // A few retries of the level that failed (up and back down: two reversals each), ever further apart.
    expect(reversals).toBeLessThanOrEqual(12);
    const later = run(20, 40_000, s);
    expect(later.reversals).toBeLessThanOrEqual(2);
  });

  it("ignores a single slow frame", () => {
    const { s } = run((i) => (i % 50 === 0 ? 100 : 10), 3000);
    expect(s.scale).toBe(1);
  });

  it("climbs back when the load goes away", () => {
    const heavy = run(40, 2000).s;
    expect(heavy.scale).toBeLessThan(1);
    const { s } = run(5, 20_000, heavy);
    expect(s.scale).toBe(1);
  });

  it("keeps within its floor even if the floor rises", () => {
    expect(scaleStep({ ...FRESH, scale: 0.5 }, 1, BUDGET, MIN).scale).toBe(MIN);
  });
});

describe("easing the pixel ratio", () => {
  it("moves in small steps and lands exactly", () => {
    let r = 2;
    const seen: number[] = [];
    while (r !== 1) {
      r = easeRatio(r, 1);
      seen.push(r);
    }
    expect(seen.length).toBe(Math.ceil(1 / EASE_STEP));
    expect(easeRatio(1.95, 2)).toBe(2);
  });
});
