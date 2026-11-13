// Narrowing job JSON (events and `/api/jobs` answers) to its types, or null
// when the shape is wrong. Like automation-guards.ts: check what the screen relies on.

import { AGENT_WORK, JOB_STATUSES, type AgentStatus, type Job, type JobDetails, type JobList, type JobStep, type Started } from "./job-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isIn = <T extends string>(values: readonly T[], v: unknown): v is T => typeof v === "string" && (values as readonly string[]).includes(v);
const strOrNull = (v: unknown): boolean => v === null || isStr(v);
const numOrNull = (v: unknown): boolean => v === null || isNum(v);

export function isJobStep(v: unknown): v is JobStep {
  return isObj(v) && isNum(v["ts"]) && isStr(v["kind"]) && isStr(v["text"]);
}

export function asJob(v: unknown): Job | null {
  const ok =
    isObj(v) &&
    isStr(v["id"]) &&
    v["id"] !== "" &&
    isStr(v["title"]) &&
    isStr(v["agent"]) &&
    strOrNull(v["room"]) &&
    isIn(JOB_STATUSES, v["status"]) &&
    isStr(v["asked_by"]) &&
    strOrNull(v["parent"]) &&
    isNum(v["created_at"]) &&
    numOrNull(v["started_at"]) &&
    numOrNull(v["ended_at"]) &&
    isBool(v["needed_approval"]) &&
    (v["last_step"] === null || isJobStep(v["last_step"]));
  return ok ? (v as unknown as Job) : null;
}

export function asJobDetails(v: unknown): JobDetails | null {
  const ok =
    asJob(v) !== null &&
    isObj(v) &&
    isStr(v["brief"]) &&
    isBool(v["careful"]) &&
    isStr(v["via"]) &&
    isStr(v["result"]) &&
    isStr(v["error"]) &&
    isNum(v["cost_usd"]) &&
    Array.isArray(v["steps"]) &&
    v["steps"].every(isJobStep);
  return ok ? (v as unknown as JobDetails) : null;
}

export function asAgentStatus(v: unknown): AgentStatus | null {
  return isObj(v) && isIn(AGENT_WORK, v["state"]) && strOrNull(v["job"]) ? (v as unknown as AgentStatus) : null;
}

/** `agent.state` event data: the agent's id with its status. */
export function asAgentState(v: unknown): (AgentStatus & { agent: string }) | null {
  return isObj(v) && isStr(v["agent"]) && v["agent"] !== "" && asAgentStatus(v) !== null ? (v as unknown as AgentStatus & { agent: string }) : null;
}

const LIMIT_KEYS = ["max_running", "max_queued", "max_steps", "job_timeout_s", "max_job_usd", "max_asks", "brief_max", "title_max"] as const;

export function asJobList(v: unknown): JobList | null {
  if (!isObj(v) || !Array.isArray(v["jobs"]) || !isObj(v["agents"])) return null;
  const limits = v["limits"];
  if (!isObj(limits) || !LIMIT_KEYS.every((k) => isNum(limits[k]))) return null;
  if (!v["jobs"].every((j) => asJob(j) !== null)) return null;
  if (!Object.values(v["agents"]).every((a) => asAgentStatus(a) !== null)) return null;
  return v as unknown as JobList;
}

/** `{job: ...}`, as `GET /api/jobs/{id}` answers. */
export function asOneJobDetails(v: unknown): JobDetails | null {
  return isObj(v) ? asJobDetails(v["job"]) : null;
}

/** `{job: ...}`, as a cancel answers. */
export function asOneJob(v: unknown): Job | null {
  return isObj(v) ? asJob(v["job"]) : null;
}

/** `{job, started}`, as `POST /api/jobs` answers. */
export function asStarted(v: unknown): Started | null {
  return isObj(v) && asJob(v["job"]) !== null && isBool(v["started"]) ? (v as unknown as Started) : null;
}

/** A `gate.request`'s optional resident fields: absent, null or text. */
export function gateFieldsOk(v: Obj): boolean {
  return ["agent", "agent_name", "job"].every((k) => v[k] === undefined || strOrNull(v[k]));
}
