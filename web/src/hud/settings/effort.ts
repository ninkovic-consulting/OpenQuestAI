// Thinking levels, apart from the DOM: which levels a model takes, and where a
// level goes when the model changes to one that does not take it.

import { EFFORTS } from "../../net/brain-types";
import type { ModelListing } from "../../net/settings-types";
import type { Plan } from "../../net/types";
import { modelShort } from "../agent-choice";

/**
 * The levels `model` takes, lowest first: the Claude model list first, then the
 * house's table, else all of them (the daemon offers a model it does not know every level).
 */
export function levelsFor(model: string, listing: ModelListing | null, plan: Plan | null): readonly string[] {
  return listing?.models.find((m) => m.id === model)?.efforts ?? plan?.effort_levels[model] ?? EFFORTS;
}

/**
 * The level to use when `wanted` may not be taken: `wanted` itself, else the
 * nearest lower one the model takes, else its lowest. Null when it takes none.
 * The daemon does the same when it sends a request.
 */
export function fallbackLevel(levels: readonly string[], wanted: string): string | null {
  if (levels.includes(wanted)) return wanted;
  const at = EFFORTS.indexOf(wanted);
  const lower = levels.filter((l) => EFFORTS.indexOf(l) <= at);
  return lower[lower.length - 1] ?? levels[0] ?? null;
}

/** The sentence shown when a model change moved the level; null when it stayed. */
export function droppedWords(model: string, before: string, after: string | null): string | null {
  if (after === null || after === before) return null;
  return `${modelShort(model)} does not take ${before}, so the level is now ${after}.`;
}

/** The help under the levels. */
export const EFFORT_HELP = "A higher level thinks longer, answers more slowly and costs more. Local models ignore it.";
