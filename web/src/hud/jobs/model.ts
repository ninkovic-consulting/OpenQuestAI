// The Jobs panel's words and order, apart from the DOM.

import { isOpen, type Job, type JobStatus } from "../../net/job-types";
import type { Plan } from "../../net/types";

/** How many jobs are working now, requests between residents included. */
export function runningCount(jobs: Readonly<Record<string, Job>>): number {
  return Object.values(jobs).filter((j) => j.status === "working").length;
}

export interface JobRow {
  job: Job;
  /** 0 for a job of its own, 1 for a request one resident made of another, shown under it. */
  depth: 0 | 1;
}

/**
 * Jobs newest first, each followed by the requests it made (oldest first).
 * A request whose job is not in the list stands on its own.
 */
export function jobRows(jobs: Readonly<Record<string, Job>>): JobRow[] {
  const all = Object.values(jobs);
  const newest = (a: Job, b: Job): number => b.created_at - a.created_at;
  const tops = all.filter((j) => j.parent === null || jobs[j.parent] === undefined).sort(newest);
  return tops.flatMap((job) => [
    { job, depth: 0 as const },
    ...all
      .filter((c) => c.parent === job.id)
      .sort((a, b) => a.created_at - b.created_at)
      .map((c) => ({ job: c, depth: 1 as const })),
  ]);
}

export const STATUS_WORD: Record<JobStatus, string> = {
  queued: "waiting to start",
  working: "working",
  done: "done",
  failed: "failed",
  cancelled: "cancelled",
};

/** Words for the names the panel shows: agents and rooms by id. */
export interface Names {
  agent(id: string): string;
  room(id: string | null): string | null;
  /** The project name of the room, when it has one. */
  project(id: string | null): string | null;
}

export function namesFrom(plan: Plan | null): Names {
  return {
    agent: (id) => plan?.agents.find((a) => a.id === id)?.name ?? id,
    room: (id) => (id === null ? null : (plan?.rooms.find((r) => r.id === id)?.name ?? id)),
    project: (id) => (id === null ? null : (plan?.rooms.find((r) => r.id === id)?.project ?? null)),
  };
}

/** Who works on it and where: "Tock, in the Workshop", or the name alone without a room. */
export function whoWhere(job: Job, names: Names): string {
  const room = names.room(job.room);
  return room ? `${names.agent(job.agent)}, in the ${room}` : names.agent(job.agent);
}

/** Who asked for it: the host by name, "You" (started from this window), or the resident whose request it is. */
export function asker(job: Job, names: Names, host: string): string {
  if (job.asked_by === "owner") return "You";
  if (job.asked_by === "host") return host;
  return names.agent(job.asked_by);
}

/** "14:02" today, "Yesterday 14:02", else "12 Nov 14:02", in local time. */
export function clock(ts: number, now: number): string {
  const d = new Date(ts * 1000);
  const time = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const day = (t: Date): number => new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime();
  const days = Math.round((day(new Date(now * 1000)) - day(d)) / 86_400_000);
  if (days === 0) return time;
  if (days === 1) return `Yesterday ${time}`;
  return `${d.getDate()} ${d.toLocaleString("en-GB", { month: "short" })} ${time}`;
}

/** A span of time: "40 s", "13 min", "2 h 5 min". */
export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

/** When, in a few words: "since 14:02 · 4 min", "14:20 · took 13 min", "queued 14:01". */
export function timeWords(job: Job, now: number): string {
  if (job.status === "queued") return `queued ${clock(job.created_at, now)}`;
  if (job.status === "working") return `since ${clock(job.started_at ?? job.created_at, now)} · ${duration(now - (job.started_at ?? job.created_at))}`;
  const ended = job.ended_at ?? job.created_at;
  return job.started_at === null ? clock(ended, now) : `${clock(ended, now)} · took ${duration(ended - job.started_at)}`;
}

/** Cancel is offered while a job has not ended. */
export const cancellable = (job: Job): boolean => isOpen(job.status);
