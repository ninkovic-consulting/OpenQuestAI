// Mock mode's thinking levels, with the daemon's rules (vision/core/effort.py):
// Haiku 4.5 takes none, Opus 4.6 and Sonnet 4.6 take all but
// xhigh, every other model all five.

import { EFFORTS } from "./brain-types";

const NO_XHIGH = EFFORTS.filter((l) => l !== "xhigh");
const BY_PREFIX: readonly (readonly [string, readonly string[]])[] = [
  ["claude-haiku-4-5", []],
  ["claude-opus-4-6", NO_XHIGH],
  ["claude-sonnet-4-6", NO_XHIGH],
];

/** The levels a model takes, lowest first. */
export function mockLevels(model: string): string[] {
  return [...(BY_PREFIX.find(([prefix]) => model.startsWith(prefix))?.[1] ?? EFFORTS)];
}

/**
 * Why a model cannot run at a level, in the daemon's words; null when it can.
 * A model that takes no levels accepts any (it sends none), so the window shows no control for it.
 */
export function effortProblem(model: string, level: string): string | null {
  if (!EFFORTS.includes(level)) return `An effort level is one of ${EFFORTS.join(", ")}.`;
  const levels = mockLevels(model);
  if (levels.length === 0 || levels.includes(level)) return null;
  return `${model} does not take effort ${level}; it takes ${levels.join(", ")}.`;
}

/** The plan's `effort_levels` for these models. */
export function levelTable(models: readonly string[]): Record<string, string[]> {
  return Object.fromEntries([...new Set(models)].map((m) => [m, mockLevels(m)]));
}
