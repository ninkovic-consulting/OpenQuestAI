// Automations as `/api/automations` serves them. Mirrors vision/scheduler/;
// the daemon is the source of truth.

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

/** A schedule as stored. Times are the Mac's local wall-clock time. */
export type Schedule =
  | { kind: "once"; at: string }
  | { kind: "daily"; time: string }
  | { kind: "weekly"; days: Weekday[]; time: string }
  | { kind: "interval"; every: number; unit: "minutes" | "hours" }
  | { kind: "cron"; expr: string };

export type ScheduleKind = Schedule["kind"];

export type RunStatus = "ok" | "failed" | "interrupted" | "needed_approval" | "missed";

export interface RunResult {
  started_at: number;
  ended_at: number;
  status: RunStatus;
  /** The start of the reply. */
  reply: string;
  trigger: "schedule" | "catch_up" | "manual";
}

export interface Automation {
  id: string;
  name: string;
  instruction: string;
  schedule: Schedule;
  /** True when the result is spoken; false when it is only shown. */
  speak: boolean;
  paused: boolean;
  /** A once-only automation that has run. */
  finished: boolean;
  /** Unix seconds; null while paused or finished. */
  next_run: number | null;
  created_at: number;
  updated_at: number;
  anchor: number;
  /** The last few runs, oldest first. */
  results: RunResult[];
  /** The daemon's own words for the schedule. */
  words: string;
  running: boolean;
}

export interface AutomationLimits {
  max_automations: number;
  name_max: number;
  instruction_max: number;
}

export interface AutomationList {
  automations: Automation[];
  limits: AutomationLimits;
  timezone: string;
  /** The daemon's clock, Unix seconds. */
  now: number;
}

/** The body of `POST /api/automations`; a `PATCH` sends any part of it. */
export interface AutomationBody {
  name: string;
  instruction: string;
  schedule: Schedule;
  speak: boolean;
}

export type AutomationPatch = Partial<AutomationBody> & { paused?: boolean };
