// The schedule builder's logic, apart from the DOM: a draft of every field the
// builder shows, the schedule it makes, and schedules in words. The words
// match the daemon's (vision/scheduler/words.py).

import { WEEKDAYS, type Schedule, type ScheduleKind, type Weekday } from "../../net/automation-types";

export interface ScheduleDraft {
  kind: ScheduleKind;
  /** once: YYYY-MM-DD. */
  date: string;
  /** once, daily and weekly: HH:MM. */
  time: string;
  days: Weekday[];
  every: string;
  unit: "minutes" | "hours";
  expr: string;
}

export const KIND_LABELS: Record<ScheduleKind, string> = {
  once: "Once",
  daily: "Every day",
  weekly: "On days",
  interval: "Every…",
  cron: "Cron",
};

const DAY_SHORT: Record<Weekday, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAY_OF_DATE = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const HHMM = /^([01]?\d|2[0-3]):([0-5]\d)$/;
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const MAX_PERIOD_MINUTES = 366 * 24 * 60;

const pad = (n: number): string => String(n).padStart(2, "0");
export const dateOf = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const timeOf = (d: Date): string => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

/**
 * The builder's fields for a schedule. A new one starts as every day at 09:00;
 * switched to once, that is the next 09:00, today or tomorrow.
 */
export function draftFrom(schedule: Schedule | null, now: Date): ScheduleDraft {
  const nine = new Date(now.getFullYear(), now.getMonth(), now.getDate() + (now.getHours() < 9 ? 0 : 1));
  const draft: ScheduleDraft = { kind: "daily", date: dateOf(nine), time: "09:00", days: ["mon", "tue", "wed", "thu", "fri"], every: "30", unit: "minutes", expr: "0 9 * * 1-5" };
  if (!schedule) return draft;
  switch (schedule.kind) {
    case "once": {
      const [date = draft.date, time = ""] = schedule.at.split("T");
      return { ...draft, kind: "once", date, time: time.slice(0, 5) || draft.time };
    }
    case "daily":
      return { ...draft, kind: "daily", time: schedule.time };
    case "weekly":
      return { ...draft, kind: "weekly", days: [...schedule.days], time: schedule.time };
    case "interval":
      return { ...draft, kind: "interval", every: String(schedule.every), unit: schedule.unit };
    case "cron":
      return { ...draft, kind: "cron", expr: schedule.expr };
  }
}

export type Built = { ok: true; schedule: Schedule } | { ok: false; message: string };

/** The schedule the builder's fields make, or why they make none. `now` refuses a once in the past. */
export function scheduleFrom(d: ScheduleDraft, now: Date): Built {
  const bad = (message: string): Built => ({ ok: false, message });
  const time = HHMM.exec(d.time.trim());
  const hhmm = time ? `${pad(Number(time[1]))}:${time[2]}` : null;
  switch (d.kind) {
    case "once": {
      const day = DATE.exec(d.date.trim());
      if (!day) return bad("Choose a date.");
      if (!hhmm) return bad("Choose a time, such as 09:00.");
      const at = `${d.date.trim()}T${hhmm}`;
      const when = new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]), Number(hhmm.slice(0, 2)), Number(hhmm.slice(3)));
      if (when.getTime() <= now.getTime()) return bad("That time has already passed.");
      return { ok: true, schedule: { kind: "once", at } };
    }
    case "daily":
      return hhmm ? { ok: true, schedule: { kind: "daily", time: hhmm } } : bad("Choose a time, such as 09:00.");
    case "weekly": {
      if (!hhmm) return bad("Choose a time, such as 09:00.");
      const days = WEEKDAYS.filter((w) => d.days.includes(w));
      return days.length > 0 ? { ok: true, schedule: { kind: "weekly", days, time: hhmm } } : bad("Choose at least one day.");
    }
    case "interval": {
      const every = Number(d.every.trim());
      if (!/^\d+$/.test(d.every.trim()) || every < 1) return bad("Every must be a whole number, 1 or more; nothing runs more often than once a minute.");
      if (every * (d.unit === "hours" ? 60 : 1) > MAX_PERIOD_MINUTES) return bad("An interval can be at most a year.");
      return { ok: true, schedule: { kind: "interval", every, unit: d.unit } };
    }
    case "cron": {
      const expr = d.expr.trim().split(/\s+/).join(" ");
      return expr.split(" ").length === 5 ? { ok: true, schedule: { kind: "cron", expr } } : bad("A cron line has five fields: minute, hour, day of month, month, day of week.");
    }
  }
}

/** "every weekday at 09:00", "once on Fri 13 Nov 2026 at 09:00", "every 20 minutes". */
export function scheduleWords(s: Schedule): string {
  switch (s.kind) {
    case "once": {
      const [date = "", time = ""] = s.at.split("T");
      const m = DATE.exec(date);
      if (!m) return `once at ${s.at}`;
      const weekday = WEEKDAY_OF_DATE[new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))).getUTCDay()] ?? "";
      return `once on ${weekday} ${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? ""} ${m[1]} at ${time.slice(0, 5)}`;
    }
    case "daily":
      return `every day at ${s.time}`;
    case "weekly":
      return `${daysWords(s.days)} at ${s.time}`;
    case "interval":
      return s.every === 1 ? `every ${s.unit.slice(0, -1)}` : `every ${s.every} ${s.unit}`;
    case "cron":
      return `on the cron line ${s.expr}`;
  }
}

function daysWords(days: readonly Weekday[]): string {
  const sorted = WEEKDAYS.filter((w) => days.includes(w));
  const key = sorted.join(",");
  if (key === WEEKDAYS.join(",")) return "every day";
  if (key === "mon,tue,wed,thu,fri") return "every weekday";
  if (key === "sat,sun") return "every weekend day";
  const names = sorted.map((w) => DAY_SHORT[w]);
  const last = names.pop() ?? "";
  return `every ${names.length > 0 ? `${names.join(", ")} and ${last}` : last}`;
}

/**
 * When a time comes, in the browser's (the Mac's) local time, as people say it:
 * "in 4 minutes", "today at 09:00", "tomorrow at 09:00", "Fri 13 Nov at 09:00".
 */
export function whenWords(at: number, now: number): string {
  const seconds = at - now;
  if (seconds < 60) return "any moment now";
  if (seconds < 3600) {
    const minutes = Math.round(seconds / 60);
    return `in ${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  const then = new Date(at * 1000);
  const today = new Date(now * 1000);
  const days = Math.round((startOfDay(then) - startOfDay(today)) / 86_400_000);
  const clock = timeOf(then);
  if (days === 0) return `today at ${clock}`;
  if (days === 1) return `tomorrow at ${clock}`;
  const date = `${WEEKDAY_OF_DATE[then.getDay()] ?? ""} ${then.getDate()} ${MONTHS[then.getMonth()] ?? ""}`;
  return `${date}${then.getFullYear() !== today.getFullYear() ? ` ${then.getFullYear()}` : ""} at ${clock}`;
}

const startOfDay = (d: Date): number => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
