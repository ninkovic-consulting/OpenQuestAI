// Mock mode's next-run arithmetic, in the browser's local time. Good enough to
// make the list believable; the daemon's own (vision/scheduler/schedule.py)
// is the real one, with the daylight-saving rules.

import { WEEKDAYS, type Schedule } from "./automation-types";

const MINUTE = 60;
const CRON_SEARCH_MINUTES = 366 * 24 * 60;
const CRON_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const CRON_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

/** The first run after `after` (Unix seconds), or null. */
export function mockNextRun(s: Schedule, after: number, anchor: number): number | null {
  switch (s.kind) {
    case "once": {
      const at = localSeconds(s.at);
      return at !== null && at > after ? at : null;
    }
    case "interval": {
      const period = s.every * (s.unit === "hours" ? 3600 : 60);
      return anchor + Math.max(1, Math.floor((after - anchor) / period) + 1) * period;
    }
    case "daily":
    case "weekly": {
      const [h = 0, m = 0] = s.time.split(":").map(Number);
      const allowed = s.kind === "daily" ? null : new Set(s.days.map((d) => (WEEKDAYS.indexOf(d) + 1) % 7));
      const day = new Date(after * 1000);
      for (let i = 0; i < 8; i++) {
        const at = new Date(day.getFullYear(), day.getMonth(), day.getDate() + i, h, m).getTime() / 1000;
        if (at > after && (!allowed || allowed.has(new Date(at * 1000).getDay()))) return at;
      }
      return null;
    }
    case "cron":
      return cronNext(s.expr, after);
  }
}

/** "2026-11-13T09:00" as local Unix seconds. */
export function localSeconds(at: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(at);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6] ?? 0)).getTime() / 1000;
}

/** Whether a cron line reads; the mock refuses what it cannot read. */
export function cronReads(expr: string): boolean {
  return cronFields(expr) !== null;
}

function cronNext(expr: string, after: number): number | null {
  const fields = cronFields(expr);
  if (!fields) return null;
  const [minutes, hours, days, months, weekdays] = fields;
  let t = (Math.floor(after / MINUTE) + 1) * MINUTE;
  for (let i = 0; i < CRON_SEARCH_MINUTES; i++, t += MINUTE) {
    const d = new Date(t * 1000);
    const dayOk = days.size === 31 || weekdays.size === 7 ? days.has(d.getDate()) && weekdays.has(d.getDay()) : days.has(d.getDate()) || weekdays.has(d.getDay());
    if (minutes.has(d.getMinutes()) && hours.has(d.getHours()) && months.has(d.getMonth() + 1) && dayOk) return t;
  }
  return null;
}

type Fields = [Set<number>, Set<number>, Set<number>, Set<number>, Set<number>];

function cronFields(expr: string): Fields | null {
  const parts = expr.trim().toLowerCase().split(/\s+/);
  if (parts.length !== 5) return null;
  const ranges: [number, number, string[], number][] = [
    [0, 59, [], 0],
    [0, 23, [], 0],
    [1, 31, [], 0],
    [1, 12, CRON_MONTHS, 1],
    [0, 7, CRON_DAYS, 0],
  ];
  const out: Set<number>[] = [];
  for (const [i, text] of parts.entries()) {
    const [low, high, names, first] = ranges[i] ?? [0, 0, [], 0];
    const set = field(text, low, high, names, first);
    if (!set) return null;
    out.push(i === 4 ? new Set([...set].map((d) => d % 7)) : set);
  }
  return out as Fields;
}

function field(text: string, low: number, high: number, names: string[], first: number): Set<number> | null {
  const set = new Set<number>();
  const value = (v: string): number => (names.includes(v) ? names.indexOf(v) + first : /^\d+$/.test(v) ? Number(v) : NaN);
  for (const part of text.split(",")) {
    const m = /^(\*|[a-z0-9]+(?:-[a-z0-9]+)?)(?:\/(\d+))?$/.exec(part);
    if (!m || !m[1]) return null;
    const step = m[2] ? Number(m[2]) : 1;
    const [a = "", b] = m[1].split("-");
    const start = m[1] === "*" ? low : value(a);
    const end = m[1] === "*" ? high : b !== undefined ? value(b) : m[2] ? high : start;
    if (!(step >= 1) || !(start >= low) || !(end <= high) || end < start) return null;
    for (let v = start; v <= end; v += step) set.add(v);
  }
  return set;
}
