import { describe, expect, it } from "vitest";
import { BAND, fitSeat, SEAT_LIMITS, type ChairShape, type PoseShape, type Sample } from "./seat";

// A unit chair: cushion at 0.4, an upright backrest whose face is at z = -0.1,
// and a seat front at z = 0.42 below the cushion.
const chair: ChairShape = {
  seatTop: 0.4,
  centerX: 0,
  back: heights(0.43, 1, () => -0.1),
  front: heights(0.14, 0.39, () => 0.42),
};

/** A seated pose with its back `back` m behind the calves, the hips at x = 0.2. */
function pose(back: number): PoseShape {
  const body: Sample[] = [];
  for (let y = 0; y < 1.4; y += BAND) body.push({ y, z: y < 0.4 ? 0 : -back });
  return { footY: -0.02, seatY: 0.43, hipX: 0.2, body };
}

function heights(from: number, to: number, z: (y: number) => number): Sample[] {
  const out: Sample[] = [];
  for (let y = from; y < to; y += 0.02) out.push({ y, z: z(y) });
  return out;
}

describe("fitSeat", () => {
  it("sizes the chair so the hips rest on the cushion with the feet on the floor", () => {
    const fit = fitSeat(chair, pose(0.6));
    const cushion = chair.seatTop * fit.height;
    expect(cushion).toBeCloseTo(0.43 + 0.02 + SEAT_LIMITS.sink, 5);
    expect(fit.offset.y).toBeCloseTo(0.02, 5);
    expect(0.43 + fit.offset.y).toBeCloseTo(cushion - SEAT_LIMITS.sink, 5);
  });

  it("centres the hips on the seat", () => {
    expect(fitSeat(chair, pose(0.6)).offset.x).toBeCloseTo(-0.2, 5);
  });

  it("puts the back against the backrest when the seat is shallow enough", () => {
    const fit = fitSeat(chair, pose(0.7));
    expect(fit.depth).toBeCloseTo(fit.height, 5);
    expect(fit.backGap).toBe(0);
    // Back of the body sits `clearance` in front of the backrest.
    expect(fit.offset.z - 0.7).toBeCloseTo(-0.1 * fit.depth + SEAT_LIMITS.clearance, 5);
    // Calves stay in front of the seat.
    expect(fit.offset.z).toBeGreaterThanOrEqual(0.42 * fit.depth + SEAT_LIMITS.clearance - 1e-9);
  });

  it("makes the chair shallower for a pose meant for a shallow seat", () => {
    const fit = fitSeat(chair, pose(0.5));
    expect(fit.depth).toBeLessThan(fit.height);
    expect(fit.backGap).toBeLessThan(0.01);
    expect(fit.offset.z).toBeGreaterThanOrEqual(0.42 * fit.depth + SEAT_LIMITS.clearance - 1e-9);
  });

  it("keeps a believable depth and leaves the rest as a gap behind the back", () => {
    const fit = fitSeat(chair, pose(0.3));
    expect(fit.depth).toBeCloseTo(fit.height * SEAT_LIMITS.minDepthRatio, 2);
    expect(fit.backGap).toBeGreaterThan(0.05);
    expect(fit.offset.z).toBeCloseTo(0.42 * fit.depth + SEAT_LIMITS.clearance, 5);
  });

  it("clamps an implausible chair height and keeps the hips on the cushion", () => {
    const tall: PoseShape = { ...pose(0.6), seatY: 0.7 };
    const fit = fitSeat(chair, tall);
    expect(fit.height).toBe(SEAT_LIMITS.maxHeight);
    expect(0.7 + fit.offset.y).toBeCloseTo(chair.seatTop * fit.height - SEAT_LIMITS.sink, 5);
  });
});
