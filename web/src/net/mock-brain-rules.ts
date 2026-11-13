// The rules the daemon applies to offline mode, the local model and the
// thinking levels (vision/settings/values.py, local_models.py and service.py),
// as pure functions over what the pretend daemon holds.

import type { FieldError, Json } from "./settings-types";
import { effortProblem } from "./mock-effort";
import { MockLocal } from "./mock-local";

export const HF_REPO = /^[A-Za-z0-9][\w.-]{0,95}\/[\w.-]{1,95}$/;
export const SERVER_URL = /^https?:\/\/[A-Za-z0-9.\-[\]:]+(\/[\w./-]*)?$/;

/** The fields these rules own. */
export const BRAIN_FIELDS: ReadonlySet<string> = new Set(["models.offline", "models.local", "models.local_backend", "models.local_server", "models.talk_effort", "models.heavy_effort"]);

/** What the rules need to know of the pretend daemon. */
export interface BrainState {
  talk: string;
  heavy: string;
  talkEffort: string;
  heavyEffort: string;
  offline: boolean;
  backend: string;
  local: string;
  server: string;
}

/** Why one value is not acceptable by itself, in the daemon's words. */
export function valueProblem(field: string, value: Json): string | null {
  switch (field) {
    case "models.offline":
      return typeof value === "boolean" ? null : "Send true or false.";
    case "models.local_backend":
      return value === "mlx" || value === "openai" ? null : "The local backend is mlx (inside the app) or openai (a local server).";
    case "models.local_server":
      return typeof value === "string" && SERVER_URL.test(value.trim()) ? null : "The server address is an http:// or https:// address, like http://127.0.0.1:1234/v1.";
    case "models.local":
      return typeof value === "string" && value.trim() !== "" ? null : "Name the local model.";
    default:
      return typeof value === "string" ? null : "An effort level is one of low, medium, high, xhigh, max.";
  }
}

/** The state after a patch of these fields. */
export function applied(now: BrainState, fields: readonly (readonly [string, Json])[]): BrainState {
  const next = { ...now };
  for (const [field, value] of fields) {
    if (field === "models.talk") next.talk = String(value);
    else if (field === "models.heavy") next.heavy = String(value);
    else if (field === "models.talk_effort") next.talkEffort = String(value);
    else if (field === "models.heavy_effort") next.heavyEffort = String(value);
    else if (field === "models.offline") next.offline = value === true;
    else if (field === "models.local") next.local = String(value).trim();
    else if (field === "models.local_backend") next.backend = String(value);
    else if (field === "models.local_server") next.server = String(value).trim().replace(/\/$/, "");
  }
  return next;
}

/**
 * The problems of the whole change that no one value shows: the host's levels
 * must be ones its models take, an MLX model must be a Hugging Face repo, and
 * offline mode needs its model here (MLX) or its server answering with it.
 */
export function brainProblems(before: BrainState, after: BrainState, local: MockLocal): FieldError[] {
  const errors: FieldError[] = [];
  for (const [field, model, level] of [
    ["models.talk_effort", after.talk, after.talkEffort],
    ["models.heavy_effort", after.heavy, after.heavyEffort],
  ] as const) {
    const message = effortProblem(model, level);
    if (message) errors.push({ field, message });
  }
  if (after.backend === "mlx" && !HF_REPO.test(after.local)) {
    return [...errors, { field: "models.local", message: "On this Mac (mlx) the local model is a Hugging Face repo, like mlx-community/Qwen3-4B-Instruct-2507-4bit." }];
  }
  const moved = before.backend !== after.backend || before.local !== after.local || before.server !== after.server;
  if (!after.offline || (before.offline && !moved)) return errors;
  const field = before.offline ? "models.local" : "models.offline";
  if (after.backend === "mlx") {
    if (!local.onDisk(after.local)) {
      errors.push({
        field,
        message: `Offline mode needs the local model on this Mac, and ${after.local} is not downloaded yet. Download it under Models while online, then turn offline mode on.`,
      });
    }
    return errors;
  }
  const found = MockLocal.testServer(after.server);
  if (!found.ok) errors.push({ field, message: `Offline mode needs the local server. ${found.message}` });
  else if (!found.models.includes(after.local)) errors.push({ field, message: `The server at ${after.server} has no model called ${after.local}. It has: ${found.models.join(", ")}.` });
  return errors;
}
