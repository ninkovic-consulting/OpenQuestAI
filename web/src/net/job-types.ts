// The job board as `/api/jobs` and the `job.changed` and `agent.state` events
// carry it. Mirrors vision/jobs/model.py and vision/core/events.py; the daemon
// is the source of truth.

export type JobStatus = "queued" | "working" | "done" | "failed" | "cancelled";
export const JOB_STATUSES: readonly JobStatus[] = ["queued", "working", "done", "failed", "cancelled"];

/** What a resident is doing: nothing, a job, or a job blocked on a request for the owner's yes. */
export type AgentWork = "idle" | "working" | "waiting";
export const AGENT_WORK: readonly AgentWork[] = ["idle", "working", "waiting"];

/** One line of a job's record. `kind` is started, tool, progress, request or finished. */
export interface JobStep {
  ts: number;
  kind: string;
  text: string;
}

/** A job as `job.changed` and each row of `GET /api/jobs` carry it. Times are Unix seconds. */
export interface Job {
  id: string;
  title: string;
  agent: string;
  room: string | null;
  status: JobStatus;
  /** `host`, `owner` (started from the window) or the id of the resident whose request it is. */
  asked_by: string;
  /** The asking resident's job, for a request between residents. */
  parent: string | null;
  created_at: number;
  started_at: number | null;
  ended_at: number | null;
  /** A tool asked for a yes during the work and nobody gave one. */
  needed_approval: boolean;
  /** The model it ran on, once it has started; an older daemon leaves both out. */
  model?: string;
  /** It ran on the local model (offline mode, or Claude could not be used). */
  local?: boolean;
  last_step: JobStep | null;
}

/** `GET /api/jobs/{id}`: the summary with the brief, the outcome and every step. */
export interface JobDetails extends Job {
  brief: string;
  careful: boolean;
  /** Where the host was asked for it: text, voice, phone, automation, window; empty otherwise. */
  via: string;
  result: string;
  error: string;
  cost_usd: number;
  steps: JobStep[];
}

export interface AgentStatus {
  state: AgentWork;
  job: string | null;
}

export interface JobLimits {
  max_running: number;
  max_queued: number;
  max_steps: number;
  job_timeout_s: number;
  max_job_usd: number;
  max_asks: number;
  brief_max: number;
  title_max: number;
}

/** `GET /api/jobs`: jobs newest first and every resident's state, idle ones included. */
export interface JobList {
  jobs: Job[];
  agents: Record<string, AgentStatus>;
  limits: JobLimits;
}

/** The body of `POST /api/jobs`. */
export interface NewJob {
  agent: string;
  brief: string;
  room?: string;
  title?: string;
  careful?: boolean;
}

/** What `POST /api/jobs` answers: the job, and whether it started at once or waits its turn. */
export interface Started {
  job: Job;
  started: boolean;
}

/** A job that has not ended. */
export const isOpen = (status: JobStatus): boolean => status === "queued" || status === "working";
