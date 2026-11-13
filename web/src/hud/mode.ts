// Offline mode in words, for the left panel and a job's detail.

import type { BrainMode } from "../net/brain-types";
import type { Job } from "../net/job-types";
import { modelShort } from "./agent-choice";

/** A local model's short name: the repo without its owner or its quantisation, "Qwen3-4B-Instruct-2507". */
export function localShort(model: string): string {
  return modelShort(model).replace(/-(?:MLX-)?\d+bit$|-MXFP4-Q8$/i, "");
}

/** The mark beside the state while offline mode is on; null otherwise. */
export function offlineMark(mode: BrainMode | null): string | null {
  return mode?.offline ? `offline · ${localShort(mode.local_model)}` : null;
}

/** What the mark says on hover. */
export function offlineTitle(mode: BrainMode): string {
  const tools = mode.local_tools === false ? " This model cannot use tools, so the agents cannot take jobs." : "";
  return `Offline mode: Claude is not answering. Everything runs on ${mode.local_model}, on this Mac, and nothing is sent to Anthropic.${tools}`;
}

/** The model a job ran on, by short name: "Opus 5.5", "Qwen3-4B-Instruct-2507". Null before the job has started. */
export function jobModelName(job: Pick<Job, "model" | "local">): string | null {
  if (!job.model) return null;
  return job.local ? localShort(job.model) : modelShort(job.model);
}
