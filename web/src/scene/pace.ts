// A resident at work paces: it works a while at its spot, turns, walks to a
// second spot in the room, works there, and walks back. `paceAt` gives the
// pose at any moment of that loop, so the figure's feet keep pace with the
// floor: it moves only while the walk clip plays, at the clip's own speed.

import type { Spot } from "./spot";

/** Seconds spent working at each end. */
export const DWELL_S = 4.5;
/** Seconds spent turning on the spot, at the start of each walk and each stay. */
export const TURN_S = 0.6;

export interface Pose {
  x: number;
  z: number;
  facing: number;
  /** True while the walk clip should play (walking, or stepping round to set off). */
  walking: boolean;
}

/** Turn from `a` toward `b` by the share `k`, the short way round. */
export function turnToward(a: number, b: number, k: number): number {
  const d = Math.atan2(Math.sin(b - a), Math.cos(b - a));
  return a + d * Math.min(1, Math.max(0, k));
}

const heading = (from: Spot, to: Spot): number => Math.atan2(to.x - from.x, to.z - from.z);

/** The pose `t` seconds into pacing between `a` and `b` at `speed` metres a second. */
export function paceAt(a: Spot, b: Spot, t: number, speed: number): Pose {
  const walkS = Math.hypot(b.x - a.x, b.z - a.z) / Math.max(0.01, speed);
  const leg = TURN_S + walkS;
  const period = 2 * (DWELL_S + leg);
  let u = ((t % period) + period) % period;
  const out = heading(a, b);
  const home = heading(b, a);
  if (u < DWELL_S) return { x: a.x, z: a.z, facing: turnToward(home, a.facing, u / TURN_S), walking: false };
  u -= DWELL_S;
  if (u < leg) return walk(a, b, a.facing, out, u, walkS);
  u -= leg;
  if (u < DWELL_S) return { x: b.x, z: b.z, facing: turnToward(out, b.facing, u / TURN_S), walking: false };
  u -= DWELL_S;
  return walk(b, a, b.facing, home, u, walkS);
}

/** Turn to set off, then walk from `from` to `to`. */
function walk(from: Spot, to: Spot, was: number, toward: number, u: number, walkS: number): Pose {
  if (u < TURN_S) return { x: from.x, z: from.z, facing: turnToward(was, toward, u / TURN_S), walking: true };
  const k = walkS > 0 ? (u - TURN_S) / walkS : 1;
  return { x: from.x + (to.x - from.x) * k, z: from.z + (to.z - from.z) * k, facing: toward, walking: true };
}
