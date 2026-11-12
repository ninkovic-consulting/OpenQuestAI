// Mock mode's automations: a believable list, checked the way the daemon
// checks it, with runs played through the mock daemon's caption.

import { scheduleWords } from "../hud/settings/schedule-edit";
import { isSchedule } from "./automation-guards";
import type { Automation, AutomationBody, AutomationList, AutomationPatch, RunResult, RunStatus, Schedule } from "./automation-types";
import { cronReads, localSeconds, mockNextRun } from "./mock-schedule";
import { ok, refused, type Result } from "./settings-api";
import type { AutomationsApi } from "./automations-api";

const LIMITS = { max_automations: 50, name_max: 60, instruction_max: 1000 };

/** What the mock automations need from the mock daemon. */
export interface MockRunner {
  /** Announce a change, as `automation.changed` would. */
  changed(id: string): void;
  /** Play a run through the caption; answers its status and reply. */
  perform(a: Automation): Promise<{ status: RunStatus; reply: string }>;
}

const now = (): number => Date.now() / 1000;

export class MockAutomations implements AutomationsApi {
  private items: Automation[] = seed(now());
  private count = 0;

  constructor(private readonly runner: MockRunner) {}

  list(): Promise<Result<AutomationList>> {
    return Promise.resolve(ok(structuredClone({ automations: this.items, limits: LIMITS, timezone: "Europe/Berlin", now: now() })));
  }

  create(body: AutomationBody): Promise<Result<Automation>> {
    if (this.items.length >= LIMITS.max_automations) return no(`There are already ${LIMITS.max_automations} automations, the most allowed. Delete one first.`);
    const problem = this.check(body, null);
    if (problem) return no(problem);
    const t = now();
    const a: Automation = { id: `mock${++this.count}`, ...body, paused: false, finished: false, next_run: null, created_at: t, updated_at: t, anchor: t, results: [], words: "", running: false };
    plan(a, t);
    this.items.push(a);
    this.runner.changed(a.id);
    return Promise.resolve(ok(structuredClone(a)));
  }

  update(id: string, patch: AutomationPatch): Promise<Result<Automation>> {
    const a = this.items.find((x) => x.id === id);
    if (!a) return no(`There is no automation called '${id}'.`);
    const problem = this.check(patch, a);
    if (problem) return no(problem);
    const t = now();
    if (patch.schedule && JSON.stringify(patch.schedule) !== JSON.stringify(a.schedule)) Object.assign(a, { schedule: patch.schedule, anchor: t, finished: false });
    Object.assign(a, { ...patch, schedule: a.schedule, updated_at: t });
    plan(a, t);
    this.runner.changed(a.id);
    return Promise.resolve(ok(structuredClone(a)));
  }

  remove(id: string): Promise<Result<null>> {
    const before = this.items.length;
    this.items = this.items.filter((a) => a.id !== id);
    if (this.items.length === before) return no(`There is no automation called '${id}'.`);
    this.runner.changed(id);
    return Promise.resolve(ok(null));
  }

  run(id: string): Promise<Result<Automation>> {
    const a = this.items.find((x) => x.id === id);
    if (!a) return no(`There is no automation called '${id}'.`);
    if (!a.running) void this.play(a);
    return Promise.resolve(ok(structuredClone(a)));
  }

  /** Start over: no automations. */
  clear(): void {
    this.items = [];
    this.runner.changed("");
  }

  private async play(a: Automation): Promise<void> {
    const started = now();
    a.running = true;
    this.runner.changed(a.id);
    const { status, reply } = await this.runner.perform(a);
    a.running = false;
    a.results = [...a.results, { started_at: started, ended_at: now(), status, reply: reply.slice(0, 200), trigger: "manual" } satisfies RunResult].slice(-5);
    this.runner.changed(a.id);
  }

  private check(body: Partial<AutomationBody>, current: Automation | null): string | null {
    if (body.name !== undefined) {
      const name = body.name.trim();
      if (!name || name.length > LIMITS.name_max) return `The name must be 1 to ${LIMITS.name_max} characters.`;
      const clash = this.items.find((x) => x.name.toLowerCase() === name.toLowerCase());
      if (clash && clash !== current) return `There is already an automation called '${clash.name}'.`;
    }
    if (body.instruction !== undefined && (!body.instruction.trim() || body.instruction.trim().length > LIMITS.instruction_max))
      return `The instruction must be 1 to ${LIMITS.instruction_max} characters.`;
    if (body.schedule !== undefined) return scheduleProblem(body.schedule);
    return null;
  }
}

const no = <T>(message: string): Promise<Result<T>> => Promise.resolve(refused(message));

function scheduleProblem(s: Schedule): string | null {
  if (!isSchedule(s)) return "That is not a schedule.";
  if (s.kind === "interval" && (!Number.isInteger(s.every) || s.every < 1)) return "An interval's every must be a whole number, 1 or more.";
  if (s.kind === "cron" && !cronReads(s.expr)) return `The cron line '${s.expr}' is not something cron understands.`;
  if (s.kind === "once" && (localSeconds(s.at) ?? 0) <= now()) return `${s.at} has already passed.`;
  return null;
}

function plan(a: Automation, t: number): void {
  a.words = scheduleWords(a.schedule);
  a.next_run = a.paused || a.finished ? null : mockNextRun(a.schedule, t, a.anchor);
}

function seed(t: number): Automation[] {
  const day = 86_400;
  const tomorrow = new Date((t + day) * 1000);
  const at = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, "0")}-${String(tomorrow.getDate()).padStart(2, "0")}T08:15`;
  const make = (id: string, name: string, instruction: string, schedule: Schedule, more: Partial<Automation> = {}): Automation => {
    const a: Automation = { id, name, instruction, schedule, speak: true, paused: false, finished: false, next_run: null, created_at: t - 9 * day, updated_at: t - 2 * day, anchor: t - 9 * day, results: [], words: "", running: false, ...more };
    plan(a, t);
    return a;
  };
  const result = (ago: number, status: RunStatus, reply: string): RunResult => ({ started_at: t - ago, ended_at: t - ago + 6, status, reply, trigger: "schedule" });
  return [
    make("a1b2c3d4", "Morning briefing", "Tell the user the weather and the first three things in their calendar.", { kind: "weekly", days: ["mon", "tue", "wed", "thu", "fri"], time: "08:30" }, {
      results: [result(day, "ok", "Good morning. Light rain until ten, then dry and 11 degrees. First up: the design review at 10:00.")],
    }),
    make("b2c3d4e5", "Stretch", "Remind the user to stand up and stretch.", { kind: "interval", every: 50, unit: "minutes" }, {
      speak: false,
      results: [result(40 * 60, "ok", "Time to stand up and stretch for a minute.")],
    }),
    make("c3d4e5f6", "Tidy downloads", "Move files older than a month from Downloads to the Archive folder.", { kind: "daily", time: "18:00" }, {
      results: [result(day - 3600, "needed_approval", "I wanted to run a shell command to move the files, but nobody answered, so nothing was moved.")],
    }),
    make("d4e5f6a7", "Dentist", "Remind the user that the dentist appointment is at 09:30.", { kind: "once", at }),
    make("e5f6a7b8", "Water the plants", "Remind the user to water the plants on the balcony.", { kind: "weekly", days: ["sat"], time: "10:00" }, {
      paused: true,
      results: [result(8 * day, "missed", "Missed by 190 minutes while the assistant was off.")],
    }),
    make("f6a7b8c9", "Month-end invoices", "Remind the user to send this month's invoices.", { kind: "cron", expr: "0 9 28-31 * *" }),
  ];
}
