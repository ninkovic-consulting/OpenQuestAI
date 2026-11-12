import { describe, expect, it } from "vitest";
import { asAutomation, asAutomationList } from "../../net/automation-guards";
import type { Automation, AutomationLimits, Schedule } from "../../net/automation-types";
import { MockAutomations } from "../../net/mock-automations";
import { mockNextRun } from "../../net/mock-schedule";
import { initialState, reduce } from "../../net/store";
import { bodyFrom, editFrom, patchFrom, resultWords, stateWords } from "./automation-edit";
import { draftFrom, scheduleFrom, scheduleWords, whenWords } from "./schedule-edit";

const LIMITS: AutomationLimits = { max_automations: 50, name_max: 60, instruction_max: 1000 };
const NOW = new Date(2026, 10, 12, 14, 3);
const secs = (d: Date): number => d.getTime() / 1000;

function automation(more: Partial<Automation> = {}): Automation {
  return {
    id: "a1",
    name: "Morning",
    instruction: "Read me the weather.",
    schedule: { kind: "daily", time: "09:00" },
    speak: true,
    paused: false,
    finished: false,
    next_run: secs(new Date(2026, 10, 13, 9, 0)),
    created_at: 0,
    updated_at: 0,
    anchor: 0,
    results: [],
    words: "every day at 09:00",
    running: false,
    ...more,
  };
}

describe("schedules in words", () => {
  const cases: [Schedule, string][] = [
    [{ kind: "once", at: "2026-11-13T09:00" }, "once on Fri 13 Nov 2026 at 09:00"],
    [{ kind: "once", at: "2026-11-12T14:23:20" }, "once on Thu 12 Nov 2026 at 14:23"],
    [{ kind: "daily", time: "07:30" }, "every day at 07:30"],
    [{ kind: "weekly", days: ["mon", "tue", "wed", "thu", "fri"], time: "09:00" }, "every weekday at 09:00"],
    [{ kind: "weekly", days: ["sat", "sun"], time: "10:00" }, "every weekend day at 10:00"],
    [{ kind: "weekly", days: ["mon", "wed", "fri"], time: "18:00" }, "every Mon, Wed and Fri at 18:00"],
    [{ kind: "weekly", days: ["sat"], time: "10:00" }, "every Sat at 10:00"],
    [{ kind: "interval", every: 1, unit: "hours" }, "every hour"],
    [{ kind: "interval", every: 20, unit: "minutes" }, "every 20 minutes"],
    [{ kind: "cron", expr: "0 9 * * 1-5" }, "on the cron line 0 9 * * 1-5"],
  ];
  it.each(cases)("%j reads as %s", (schedule, words) => {
    expect(scheduleWords(schedule)).toBe(words);
  });

  it("says when as people do", () => {
    const now = secs(NOW);
    expect(whenWords(now + 30, now)).toBe("any moment now");
    expect(whenWords(now + 60, now)).toBe("in 1 minute");
    expect(whenWords(now + 20 * 60, now)).toBe("in 20 minutes");
    expect(whenWords(secs(new Date(2026, 10, 12, 18, 0)), now)).toBe("today at 18:00");
    expect(whenWords(secs(new Date(2026, 10, 13, 9, 0)), now)).toBe("tomorrow at 09:00");
    expect(whenWords(secs(new Date(2026, 10, 16, 9, 0)), now)).toBe("Mon 16 Nov at 09:00");
    expect(whenWords(secs(new Date(2027, 0, 4, 9, 0)), now)).toBe("Mon 4 Jan 2027 at 09:00");
  });
});

describe("the schedule builder", () => {
  it("round-trips every kind", () => {
    const all: Schedule[] = [
      { kind: "once", at: "2026-11-13T09:00" },
      { kind: "daily", time: "07:30" },
      { kind: "weekly", days: ["mon", "fri"], time: "09:00" },
      { kind: "interval", every: 2, unit: "hours" },
      { kind: "cron", expr: "15 9 1 * *" },
    ];
    for (const s of all) expect(scheduleFrom(draftFrom(s, NOW), NOW)).toEqual({ ok: true, schedule: s });
  });

  it("starts a new one as every day at nine, and a once at the next nine o'clock", () => {
    const d = draftFrom(null, NOW);
    expect(scheduleFrom(d, NOW)).toEqual({ ok: true, schedule: { kind: "daily", time: "09:00" } });
    expect(scheduleFrom({ ...d, kind: "once" }, NOW)).toEqual({ ok: true, schedule: { kind: "once", at: "2026-11-13T09:00" } });
    const early = new Date(2026, 10, 12, 7, 0);
    expect(scheduleFrom({ ...draftFrom(null, early), kind: "once" }, early)).toEqual({ ok: true, schedule: { kind: "once", at: "2026-11-12T09:00" } });
  });

  it("refuses what the daemon would, with a reason", () => {
    const d = draftFrom(null, NOW);
    expect(scheduleFrom({ ...d, kind: "once", date: "2026-11-12", time: "14:00" }, NOW)).toEqual({ ok: false, message: "That time has already passed." });
    expect(scheduleFrom({ ...d, kind: "weekly", days: [] }, NOW)).toEqual({ ok: false, message: "Choose at least one day." });
    expect(scheduleFrom({ ...d, kind: "interval", every: "0" }, NOW).ok).toBe(false);
    expect(scheduleFrom({ ...d, kind: "interval", every: "1.5" }, NOW).ok).toBe(false);
    expect(scheduleFrom({ ...d, kind: "interval", every: "9000", unit: "hours" }, NOW)).toEqual({ ok: false, message: "An interval can be at most a year." });
    expect(scheduleFrom({ ...d, kind: "daily", time: "25:00" }, NOW).ok).toBe(false);
    expect(scheduleFrom({ ...d, kind: "cron", expr: "0 9 * *" }, NOW).ok).toBe(false);
  });

  it("puts weekdays in week order and pads the hour", () => {
    const d = { ...draftFrom(null, NOW), kind: "weekly" as const, days: ["fri" as const, "mon" as const], time: "9:05" };
    expect(scheduleFrom(d, NOW)).toEqual({ ok: true, schedule: { kind: "weekly", days: ["mon", "fri"], time: "09:05" } });
  });
});

describe("the automation form", () => {
  it("collects every problem at once", () => {
    const edit = { ...editFrom(null, NOW), name: " ", instruction: "x".repeat(1001) };
    expect(bodyFrom(edit, LIMITS, NOW)).toEqual({
      ok: false,
      errors: [
        { field: "name", message: "Give it a name." },
        { field: "instruction", message: "At most 1000 characters; this has 1001." },
      ],
    });
  });

  it("sends only what changed, so the schedule keeps its count", () => {
    const before = automation();
    const edit = editFrom(before, NOW);
    edit.name = "  Weather   report ";
    const built = bodyFrom(edit, LIMITS, NOW);
    expect(built.ok && patchFrom(before, built.body)).toEqual({ name: "Weather report" });
    edit.schedule.kind = "interval";
    const again = bodyFrom(edit, LIMITS, NOW);
    expect(again.ok && patchFrom(before, again.body)).toEqual({ name: "Weather report", schedule: { kind: "interval", every: 30, unit: "minutes" } });
  });

  it("words each state and the last result", () => {
    const now = secs(NOW);
    expect(stateWords(automation(), now)).toEqual({ tone: "ok", text: "Next tomorrow at 09:00" });
    expect(stateWords(automation({ paused: true, next_run: null }), now).text).toBe("Paused");
    expect(stateWords(automation({ finished: true, next_run: null }), now).text).toBe("Finished; it ran once");
    expect(stateWords(automation({ running: true }), now)).toEqual({ tone: "warn", text: "Running now" });
    expect(resultWords(undefined)).toBeNull();
    const asked = resultWords({ started_at: secs(new Date(2026, 10, 12, 9, 0)), ended_at: 0, status: "needed_approval", reply: "Nobody answered.", trigger: "schedule" });
    expect(asked).toEqual({ tone: "warn", text: "Needed your approval; nothing that asks first was done, 12 Nov 2026, 09:00: Nobody answered." });
    const manual = resultWords({ started_at: secs(new Date(2026, 10, 12, 9, 0)), ended_at: 0, status: "ok", reply: "", trigger: "manual" });
    expect(manual?.text).toBe("Done, 12 Nov 2026, 09:00 (run now)");
  });
});

describe("automations on the wire", () => {
  it("narrows the daemon's shapes", () => {
    expect(asAutomation(automation())).not.toBeNull();
    expect(asAutomation({ ...automation(), schedule: { kind: "weekly", days: ["funday"], time: "09:00" } })).toBeNull();
    expect(asAutomationList({ automations: [automation()], limits: LIMITS, timezone: "Europe/Berlin", now: 1 })).not.toBeNull();
    expect(asAutomationList({ automations: [{}], limits: LIMITS, timezone: "x", now: 1 })).toBeNull();
  });

  it("shows the running automation beside the state, and its name in the caption", () => {
    let s = initialState();
    s = reduce(s, { kind: "event", event: { type: "automation.started", ts: 1, data: { id: "a1", name: "Morning" } } });
    expect(s.automation).toEqual({ id: "a1", name: "Morning" });
    expect(s.caption).toEqual({ user: "Morning", source: "automation", reply: "", streaming: false });
    s = reduce(s, { kind: "event", event: { type: "vision.delta", ts: 2, data: { text: "Sunny." } } });
    expect(s.caption.reply).toBe("Sunny.");
    s = reduce(s, { kind: "event", event: { type: "automation.finished", ts: 3, data: { id: "a1", name: "Morning", status: "ok", reply: "Sunny." } } });
    expect(s.automation).toBeNull();
    const before = s.automationsRevision;
    s = reduce(s, { kind: "event", event: { type: "automation.changed", ts: 4, data: { id: "a1", change: "updated", automation: null } } });
    expect(s.automationsRevision).toBe(before + 1);
  });
});

describe("the mock's automations", () => {
  const silent = { changed: () => {}, perform: () => Promise.resolve({ status: "ok" as const, reply: "Done." }) };

  it("refuses like the daemon and keeps the list", async () => {
    const mock = new MockAutomations(silent);
    const start = await mock.list();
    expect(start.ok && start.value.automations.length).toBeGreaterThan(3);
    const twin = await mock.create({ name: "stretch", instruction: "x", schedule: { kind: "daily", time: "09:00" }, speak: true });
    expect(twin).toMatchObject({ ok: false, message: "There is already an automation called 'Stretch'." });
    const fast = await mock.create({ name: "Fast", instruction: "x", schedule: { kind: "interval", every: 0, unit: "minutes" }, speak: true });
    expect(fast.ok).toBe(false);
    const made = await mock.create({ name: "Tea", instruction: "Say the tea is ready.", schedule: { kind: "interval", every: 5, unit: "minutes" }, speak: false });
    expect(made.ok && made.value.words).toBe("every 5 minutes");
    if (!made.ok) return;
    const paused = await mock.update(made.value.id, { paused: true });
    expect(paused.ok && paused.value.next_run).toBeNull();
    expect((await mock.remove(made.value.id)).ok).toBe(true);
  });

  it("works out next runs for each kind", () => {
    const after = secs(NOW);
    expect(mockNextRun({ kind: "daily", time: "09:00" }, after, 0)).toBe(secs(new Date(2026, 10, 13, 9, 0)));
    expect(mockNextRun({ kind: "weekly", days: ["mon"], time: "09:00" }, after, 0)).toBe(secs(new Date(2026, 10, 16, 9, 0)));
    expect(mockNextRun({ kind: "interval", every: 10, unit: "minutes" }, after, after - 25 * 60)).toBe(after + 5 * 60);
    expect(mockNextRun({ kind: "cron", expr: "0 9 28-31 * *" }, after, 0)).toBe(secs(new Date(2026, 10, 28, 9, 0)));
    expect(mockNextRun({ kind: "once", at: "2026-11-12T14:00" }, after, 0)).toBeNull();
  });
});
