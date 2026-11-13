// The local model in memory, in words: loading, reading a long prompt before
// the first word, in memory (and how much it holds), or a load that failed.
// The offline block, the local model block and the state line say the same.

import type { BrainMode } from "../../net/brain-types";
import type { Tone } from "./fields";
import { formatBytes } from "./format";

export interface LoadLine {
  tone: Tone;
  text: string;
}

/** A short word for the state line while something is in the way of the first word; null otherwise. */
export function loadMark(mode: BrainMode): string | null {
  if (mode.local_backend !== "mlx") return null;
  if (mode.local_state === "loading") return "loading";
  if (mode.local_reading) return "reading";
  if (mode.local_state === "failed") return "not loaded";
  return null;
}

/** The model's state in one line; null for a model on a server, which loads its own. */
export function loadLine(mode: BrainMode, title: string): LoadLine | null {
  if (mode.local_backend !== "mlx" || mode.local_state === undefined) return null;
  if (mode.local_reading) {
    const [done, total] = mode.local_reading;
    return { tone: "idle", text: `Reading the conversation before the first word: ${done.toLocaleString("en")} of ${total.toLocaleString("en")} tokens.` };
  }
  switch (mode.local_state) {
    case "loading":
      return { tone: "idle", text: `Loading ${title} into memory. A message sent now waits for it.` };
    case "failed":
      return { tone: "bad", text: mode.local_problem ?? `${title} could not be loaded.` };
    case "ready": {
      const kept = mode.local_cache_bytes ? `, and ${formatBytes(mode.local_cache_bytes)} of conversation already read` : "";
      const size = mode.local_bytes ? `${formatBytes(mode.local_bytes)} of memory` : "memory";
      return { tone: "ok", text: `In memory and ready: ${size}${kept}.` };
    }
    default:
      return mode.offline
        ? { tone: "idle", text: `${title} is not in memory yet.` }
        : { tone: "idle", text: "Not in memory now: it loads for the first message it answers, which waits a few seconds for it." };
  }
}
