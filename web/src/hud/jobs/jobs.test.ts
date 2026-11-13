import { describe, expect, it } from "vitest";
import type { Job } from "../../net/job-types";
import { samplePlan } from "../../net/sample-plan";
import { initialState } from "../../net/store";
import type { GateRequest } from "../../net/types";
import { entryLabel } from "../caption";
import { reportOf } from "../chat/history";
import { OVERLAYS, routeKey } from "../chat/keys";
import { gateCard } from "../gate";
import { carefulNote, newJobBody, roomChoices } from "./form";
import { duration, jobRows, namesFrom, runningCount, timeWords, whoWhere } from "./model";

const job = (id: string, more: Partial<Job> = {}): Job => ({
  id,
  title: id,
  agent: "maker",
  room: "workshop",
  status: "done",
  asked_by: "host",
  parent: null,
  created_at: 0,
  started_at: null,
  ended_at: null,
  needed_approval: false,
  last_step: null,
  ...more,
});

describe("the jobs list", () => {
  it("is newest first, with each request between residents under its job, oldest request first", () => {
    const jobs = {
      a: job("a", { created_at: 10 }),
      b: job("b", { created_at: 30 }),
      c2: job("c2", { created_at: 50, parent: "a", asked_by: "maker" }),
      c1: job("c1", { created_at: 40, parent: "a", asked_by: "maker" }),
      orphan: job("orphan", { created_at: 20, parent: "gone" }),
    };
    expect(jobRows(jobs).map((r) => `${r.job.id}:${r.depth}`)).toEqual(["b:0", "orphan:0", "a:0", "c1:1", "c2:1"]);
  });

  it("counts the jobs working now, requests included", () => {
    expect(runningCount({ a: job("a", { status: "working" }), b: job("b", { status: "queued" }), c: job("c", { status: "working", parent: "a" }) })).toBe(2);
  });

  it("says who works where, also in another resident's room", () => {
    const names = namesFrom(samplePlan());
    expect(whoWhere(job("a", { agent: "checker", room: "workshop" }), names)).toBe("Tock, in the Workshop");
    expect(whoWhere(job("a", { room: null }), names)).toBe("Tink");
  });

  it("puts times in words", () => {
    expect(duration(40)).toBe("40 s");
    expect(duration(13 * 60)).toBe("13 min");
    expect(duration(125 * 60)).toBe("2 h 5 min");
    const start = new Date(2026, 10, 13, 14, 2).getTime() / 1000;
    expect(timeWords(job("a", { status: "working", started_at: start }), start + 240)).toBe("since 14:02 · 4 min");
  });
});

describe("the new-job form", () => {
  it("offers every room but the Hall, the resident's own first", () => {
    const { own, others } = roomChoices(samplePlan(), "checker");
    expect(own.map((r) => r.id)).toEqual(["spare-room"]);
    expect(others.map((r) => r.id)).not.toContain("hall");
    expect(others.map((r) => r.id)).toContain("workshop");
  });

  it("sends no room on the default and leaves out empty optional fields; the brief goes for the daemon to judge", () => {
    expect(newJobBody({ agent: "maker", room: "", brief: "  ", title: " ", careful: false })).toEqual({ agent: "maker", brief: "" });
    expect(newJobBody({ agent: "checker", room: "workshop", brief: " Check it ", title: " Check ", careful: true })).toEqual({
      agent: "checker",
      room: "workshop",
      brief: "Check it",
      title: "Check",
      careful: true,
    });
  });

  it("says what careful does for the agent", () => {
    const plan = samplePlan();
    expect(carefulNote(plan.agents.find((a) => a.id === "checker"))).toContain("claude-opus-5-5");
    expect(carefulNote(plan.agents.find((a) => a.id === "maker"))).toContain("no heavier model");
  });
});

describe("the gate card", () => {
  const gate = (id: string, more: Partial<GateRequest> = {}): GateRequest => ({ id, tool: "shell", summary: "Run a program", detail: "", expires_at: 1, ...more });

  it("shows the oldest request, names who asks and where, and counts the rest", () => {
    const s = {
      ...initialState(),
      plan: samplePlan(),
      jobs: { j1: job("j1", { room: "workshop", agent: "checker" }) },
      gates: [gate("a", { agent: "checker", agent_name: "Tock", job: "j1", summary: "Tock, in the Workshop: run npm test" }), gate("b"), gate("c")],
    };
    expect(gateCard(s)).toMatchObject({ who: "Tock, in the Workshop", summary: "Run npm test", more: 2 });
    expect(gateCard({ ...s, gates: [gate("b")] })).toMatchObject({ who: "", summary: "Run a program", more: 0 });
    expect(gateCard({ ...s, gates: [] })).toBeNull();
  });
});

describe("job reports in the thread", () => {
  it("read the resident and the title from the report's first line", () => {
    expect(reportOf('Tink finished job 3f2a91c0, "Run the tests".\nTink\'s result:\nok')).toEqual({ agent: "Tink", title: "Run the tests" });
    expect(reportOf("Tock's job 1a2b, \"Check it\", failed: it broke")).toEqual({ agent: "Tock", title: "Check it" });
    expect(reportOf("Hello")).toBeNull();
  });

  it("are labelled as a report on the resident's job", () => {
    expect(entryLabel("job", "Tink")).toBe("Job report · Tink");
    expect(entryLabel("automation")).toBe("Automation");
  });
});

describe("keys while the Jobs panel is open", () => {
  it("the panel counts as an overlay, so the message field takes no keys and Escape steps back", () => {
    expect(OVERLAYS).toContain(".jobs:not([hidden])");
    const press = { key: "h", code: "KeyH", shift: false, ctrl: false, meta: false, alt: false, composing: false };
    const open = { focus: "other" as const, overlay: true, fieldEmpty: true, speaking: false };
    expect(routeKey(press, open)).toEqual({ kind: "none" });
    expect(routeKey({ ...press, key: " ", code: "Space" }, open)).toEqual({ kind: "none" });
    expect(routeKey({ ...press, key: "Escape", code: "Escape" }, open)).toEqual({ kind: "step-back" });
  });
});
