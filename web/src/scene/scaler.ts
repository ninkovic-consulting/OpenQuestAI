// The automatic resolution scaler. It lowers the scene's pixel ratio a step
// when frames keep arriving late and raises it a step when they have long
// been on time. A level that once failed is retried only after a hold that
// doubles every time it fails again, so a load near the edge settles instead
// of flipping between two sizes. `easeRatio` walks the applied ratio toward
// its target in small steps, so no change shows as a pop.

/** Shrinks (and grows) the scale by this factor per step. */
export const STEP = 0.85;
/** A frame is late when it takes more than this share of the budget. */
export const LATE_SHARE = 1.25;
/** Late frames, net of on-time ones, that bring a step down. */
export const LATE_FRAMES = 12;
/** On-time frames in a row that bring a step up. */
export const ON_TIME_FRAMES = 90;
/** Frames ignored after any step, while the new size settles. */
export const COOLDOWN_FRAMES = 30;
/** Frames before a level that failed is tried again, at first; it doubles with each failure there, so retries soon all but stop. */
export const HOLD_FRAMES = 600;
/**
 * A frame this long says nothing about the graphics chip: the page stalled, or
 * the window is in the background and its ticks are held back. Fewer pixels
 * would not have helped, so it is not counted either way.
 */
export const STALL_MS = 250;

export interface ScalerState {
  /** Share of the quality level's pixel ratio drawn, from `min` to 1. */
  scale: number;
  late: number;
  onTime: number;
  cooldown: number;
  /** The lowest scale that proved too slow; Infinity when none. */
  ceiling: number;
  /** Frames left before the ceiling may be tried again. */
  holdLeft: number;
  /** The hold the next failure at the ceiling starts. */
  hold: number;
}

export const FRESH: ScalerState = { scale: 1, late: 0, onTime: 0, cooldown: 0, ceiling: Infinity, holdLeft: 0, hold: HOLD_FRAMES };

/** The state after one frame that took `frameMs` against a budget of `budgetMs`, with the scale kept within [min, 1]. */
export function scaleStep(s: ScalerState, frameMs: number, budgetMs: number, min: number): ScalerState {
  const next = { ...s, holdLeft: Math.max(0, s.holdLeft - 1) };
  if (next.scale < min) next.scale = min;
  if (next.cooldown > 0) {
    next.cooldown -= 1;
    return next;
  }
  if (frameMs >= STALL_MS) return next;
  const late = frameMs > budgetMs * LATE_SHARE;
  next.late = late ? next.late + 1 : Math.max(0, next.late - 1);
  next.onTime = frameMs <= budgetMs ? next.onTime + 1 : 0;

  if (next.late >= LATE_FRAMES && next.scale > min) {
    const failedAtCeiling = next.scale >= next.ceiling - 1e-6;
    const hold = failedAtCeiling ? next.hold * 2 : next.hold;
    return { ...next, scale: Math.max(min, next.scale * STEP), ceiling: next.scale, hold, holdLeft: hold, late: 0, onTime: 0, cooldown: COOLDOWN_FRAMES };
  }
  if (next.onTime >= ON_TIME_FRAMES && next.scale < 1) {
    const up = Math.min(1, next.scale / STEP);
    if (up >= next.ceiling - 1e-6 && next.holdLeft > 0) return next;
    return { ...next, scale: up, late: 0, onTime: 0, cooldown: COOLDOWN_FRAMES };
  }
  if (next.onTime >= ON_TIME_FRAMES && next.scale >= next.ceiling - 1e-6) {
    // The level that once failed has held: forget it, and start the next hold afresh.
    return { ...next, ceiling: Infinity, hold: HOLD_FRAMES, onTime: 0 };
  }
  return next;
}

/** Largest change of the applied pixel ratio in one step. */
export const EASE_STEP = 0.125;

/** The applied pixel ratio one step closer to `target`. */
export function easeRatio(current: number, target: number): number {
  const d = target - current;
  if (Math.abs(d) <= EASE_STEP) return target;
  return current + Math.sign(d) * EASE_STEP;
}
