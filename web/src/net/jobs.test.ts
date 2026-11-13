import { describe, expect, it } from "vitest";
import { asJob, asJobDetails, asJobList, asStarted } from "./job-guards";
import type { Job, JobList } from "./job-types";
import { samplePlan } from "./sample-plan";
import { initialState, reduce, type Action, type ViewState } from "./store";
import { asOutbound, type GateRequest, type OutboundData, type OutboundEvent, type OutboundType } from "./types";

const job = (more: Partial<Job> = {}): Job => ({
  id: "j1",
  title: "Run the tests",
  agent: "maker",
  room: "workshop",
  status: "working",
  asked_by: "host",
  parent: null,
  created_at: 100,
  started_at: 101,
  ended_at: null,
  needed_approval: false,
  last_step: { ts: 101, kind: "started", text: "Tink started in the Workshop." },
  ...more,
});

const limits = { max_running: 2, max_queued: 20, max_steps: 40, job_timeout_s: 900, max_job_usd: 1, max_asks: 3, brief_max: 8000, title_max: 80 };

function ev<K extends OutboundType>(type: K, data: OutboundData[K]): Action {
  return { kind: "event", event: { type, ts: 1, data } as OutboundEvent };
}

const run = (...actions: Action[]): ViewState => actions.reduce(reduce, { ...initialState(), plan: samplePlan() });

describe("job guards", () => {
  it("accept a job in the job.changed shape and refuse a wrong status or a missing field", () => {
    expect(asJob(job())).not.toBeNull();
    expect(asJob(job({ status: "paused" as Job["status"] }))).toBeNull();
    const { room: _room, ...noRoom } = job();
    expect(asJob(noRoom)).toBeNull();
    expect(asJob(job({ last_step: { ts: 1, kind: "tool" } as Job["last_step"] }))).toBeNull();
  });

  it("narrow details, lists and the start answer", () => {
    const details = { ...job(), brief: "b", careful: false, via: "window", result: "", error: "", cost_usd: 0.01, steps: [] };
    expect(asJobDetails(details)).not.toBeNull();
    expect(asJobDetails({ ...details, steps: [{ ts: 1 }] })).toBeNull();
    const list: JobList = { jobs: [job()], agents: { maker: { state: "working", job: "j1" } }, limits };
    expect(asJobList(list)).not.toBeNull();
    expect(asJobList({ ...list, agents: { maker: { state: "asleep", job: null } } })).toBeNull();
    expect(asJobList({ ...list, limits: { ...limits, brief_max: "8000" } })).toBeNull();
    expect(asStarted({ job: job(), started: true })).not.toBeNull();
    expect(asStarted({ job: job() })).toBeNull();
  });

  it("drop job events whose data the window cannot use", () => {
    expect(asOutbound({ type: "job.changed", ts: 1, data: job() })?.type).toBe("job.changed");
    expect(asOutbound({ type: "job.changed", ts: 1, data: { id: "j1" } })).toBeNull();
    expect(asOutbound({ type: "agent.state", ts: 1, data: { agent: "maker", state: "waiting", job: "j1" } })).not.toBeNull();
    expect(asOutbound({ type: "agent.state", ts: 1, data: { agent: "maker", state: "busy", job: null } })).toBeNull();
  });

  it("take gate requests with or without the resident's fields", () => {
    const gate = { id: "g", tool: "shell", summary: "s", detail: "d", expires_at: 1 };
    expect(asOutbound({ type: "gate.request", ts: 1, data: gate })).not.toBeNull();
    expect(asOutbound({ type: "gate.request", ts: 1, data: { ...gate, agent: "maker", agent_name: "Tink", job: "j1" } })).not.toBeNull();
    expect(asOutbound({ type: "gate.request", ts: 1, data: { ...gate, agent: null, agent_name: null, job: null } })).not.toBeNull();
    expect(asOutbound({ type: "gate.request", ts: 1, data: { ...gate, agent: 7 } })).toBeNull();
  });
});

describe("the store's job board", () => {
  it("is seeded by the list and kept current by events", () => {
    const list: JobList = { jobs: [job({ status: "queued", started_at: null })], agents: { maker: { state: "idle", job: null } }, limits };
    const s = run({ kind: "jobs", list }, ev("job.changed", job()), ev("agent.state", { agent: "maker", state: "waiting", job: "j1" }));
    expect(s.jobs["j1"]?.status).toBe("working");
    expect(s.agents["maker"]).toEqual({ state: "waiting", job: "j1" });
  });

  it("a fresh list replaces the board", () => {
    const s = run(ev("job.changed", job()), { kind: "jobs", list: { jobs: [], agents: {}, limits } });
    expect(s.jobs).toEqual({});
  });

  it("a job that ends here becomes the host's next unannounced turn, labelled with the resident and title", () => {
    let s = run(ev("job.changed", job()), ev("job.changed", job({ status: "done", ended_at: 120 })));
    expect(s.reports).toEqual(["j1"]);
    s = reduce(s, ev("state.changed", { state: "thinking", brain: "claude" }));
    expect(s.caption).toEqual({ user: "Run the tests", source: "job", agent: "Tink", reply: "", streaming: false });
    expect(s.reports).toEqual([]);
  });

  it("a typed turn is not taken for a report, and a request between residents is never reported", () => {
    let s = run(
      ev("job.changed", job({ id: "c1", parent: "j0", asked_by: "envoy" })),
      ev("job.changed", job({ id: "c1", parent: "j0", asked_by: "envoy", status: "done" })),
    );
    expect(s.reports).toEqual([]);
    s = run(ev("job.changed", job({ status: "failed" })), ev("user.utterance", { text: "hi", source: "text" }), ev("state.changed", { state: "thinking", brain: "claude" }));
    expect(s.caption.source).toBe("text");
    expect(s.reports).toEqual(["j1"]);
  });

  it("an ended job seen again is not reported twice", () => {
    const done = job({ status: "done" });
    const s = run(ev("job.changed", job()), ev("job.changed", done), ev("job.changed", done));
    expect(s.reports).toEqual(["j1"]);
  });
});

describe("the gate queue", () => {
  const gate = (id: string, more: Partial<GateRequest> = {}): GateRequest => ({ id, tool: "shell", summary: id, detail: "", expires_at: 1, ...more });

  it("keeps requests in the order they arrived, oldest first", () => {
    const s = run(ev("gate.request", gate("a")), ev("gate.request", gate("b")), ev("gate.request", gate("c")));
    expect(s.gates.map((g) => g.id)).toEqual(["a", "b", "c"]);
    expect(reduce(s, ev("gate.resolved", { id: "a", decision: "allow" })).gates.map((g) => g.id)).toEqual(["b", "c"]);
  });

  it("a request announced again keeps its place", () => {
    const s = run(ev("gate.request", gate("a")), ev("gate.request", gate("b")), ev("gate.request", gate("a", { summary: "again" })));
    expect(s.gates.map((g) => [g.id, g.summary])).toEqual([
      ["a", "again"],
      ["b", "b"],
    ]);
  });
});
