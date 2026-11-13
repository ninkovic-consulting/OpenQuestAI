// Mock mode's job board: a few sample jobs, the daemon's checks for a new
// one, and each job played out with steps, the room's light, the agent's
// state and, for a job that runs a program, a request for the owner's yes.

import { hostAgentId } from "./plan";
import { isOpen, type AgentStatus, type Job, type JobDetails, type JobList, type JobStep, type NewJob, type Started } from "./job-types";
import { HAIKU, LOCAL_MODEL, OPUS } from "./mock-settings-data";
import { ok, refused, type Result } from "./settings-api";
import type { JobsApi } from "./jobs-api";
import type { OutboundData, OutboundType, Plan } from "./types";

const LIMITS = { max_running: 2, max_queued: 20, max_steps: 40, job_timeout_s: 900, max_job_usd: 1, max_asks: 3, brief_max: 8000, title_max: 80 };
const STEP_MS = 1400;
const GATE_S = 120;

/** What the mock board needs from the mock daemon. */
export interface MockBoardHost {
  emit<K extends OutboundType>(type: K, data: OutboundData[K]): void;
  plan(): Plan;
  /** The local model while offline mode is on, else null: jobs that start now run on it. */
  localModel(): string | null;
  /** A top-level job ended: the host reports it in a turn of its own. */
  report(job: JobDetails): void;
}

/** A program the job asks to run, with the lines the request shows. */
interface Ask {
  /** The tool's own words; the card puts the agent and the room in front, as the daemon does. */
  summary: string;
  detail: string;
  ran: string;
}

/** How a mock job plays out once started. */
interface Script {
  steps: string[];
  ask: Ask | null;
  after: string[];
  result: string;
}

const now = (): number => Date.now() / 1000;

export class MockJobs implements JobsApi {
  private items: JobDetails[];
  private agents: Record<string, AgentStatus> = {};
  private readonly scripts = new Map<string, Script>();
  /** Gate request id to the job waiting on it. */
  private readonly waiting = new Map<string, { job: JobDetails; ask: Ask; rest: Script }>();
  private count = 0;

  constructor(private readonly host: MockBoardHost) {
    this.items = seed(now());
    for (const a of host.plan().agents) if (a.id !== hostAgentId(host.plan())) this.agents[a.id] = { state: "idle", job: null };
    for (const j of this.items) if (j.status === "working") this.agents[j.agent] = { state: "working", job: j.id };
  }

  list(): Promise<Result<JobList>> {
    const jobs = [...this.items].sort((a, b) => b.created_at - a.created_at).map(summary);
    return Promise.resolve(ok(structuredClone({ jobs, agents: this.agents, limits: LIMITS })));
  }

  get(id: string): Promise<Result<JobDetails>> {
    const job = this.items.find((j) => j.id === id);
    return job ? Promise.resolve(ok(structuredClone(job))) : no(`There is no job ${id}.`);
  }

  start(body: NewJob): Promise<Result<Started>> {
    const made = this.handOff(body, "owner", "window");
    if (typeof made === "string") return no(made);
    return Promise.resolve(ok(structuredClone({ job: summary(made), started: made.status === "working" })));
  }

  cancel(id: string): Promise<Result<Job>> {
    const job = this.items.find((j) => j.id === id);
    if (!job) return no(`There is no job ${id}.`);
    if (!isOpen(job.status)) return no(`Job ${job.id} ('${job.title}') has already ended (${job.status}).`);
    for (const [gate, w] of this.waiting) if (w.job === job) this.resolveGate(gate, "deny");
    this.end(job, "cancelled", "", job.started_at === null ? "Cancelled before it started." : "Cancelled.");
    for (const child of this.items.filter((c) => c.parent === job.id && isOpen(c.status))) this.end(child, "cancelled", "", "Cancelled.");
    return Promise.resolve(ok(summary(job)));
  }

  /** Light the rooms of the jobs already working, as the daemon's state would show them. */
  announce(): void {
    for (const j of this.items) if (j.status === "working" && j.room) this.host.emit("room.state", { room: j.room, state: "active" });
  }

  /** The host hands a job over (mock mode's "ask tink ..."): one that runs the tests and needs a yes. */
  handOffFromHost(agent: string, room: string, brief: string): JobDetails | string {
    return this.handOff({ agent, room, brief }, "host", "text", {
      steps: ["Read README.md and package.json in ~/Projects/engine.", "The suite runs with vitest; running it needs the owner's yes."],
      ask: {
        summary: "Run the test suite in the engine project.",
        detail: "npm test -- --run --reporter=dot\nin ~/Projects/engine",
        ran: "Ran npm test -- --run --reporter=dot: 214 tests passed.",
      },
      after: ["Checked the date parser's tests: all twelve pass, including the day-month case."],
      result: "The engine's test suite passes: 214 tests, none failing. The date parser fix from this afternoon holds; the day-month case has its own test now.",
    });
  }

  /** The first job of a project the host just started, in its new room. */
  firstJob(agent: string, room: string, brief: string): JobDetails | string {
    return this.handOff({ agent, room, brief }, "host", "text");
  }

  /** The owner answered a request; true when it was one of the jobs'. */
  decide(gateId: string, decision: "allow" | "deny"): boolean {
    const w = this.waiting.get(gateId);
    if (!w) return false;
    this.resolveGate(gateId, decision);
    const { job, ask, rest } = w;
    this.step(job, "tool", decision === "allow" ? ask.ran : `${ask.detail.split("\n")[0]} (did not work: the owner said no)`);
    this.play(job, { ...rest, result: decision === "allow" ? rest.result : "The tests were not run: the owner said no to running them." });
    return true;
  }

  private handOff(body: NewJob, askedBy: string, via: string, script?: Script): JobDetails | string {
    const plan = this.host.plan();
    const residents = plan.agents.filter((a) => a.id !== hostAgentId(plan));
    const list = residents.map((a) => `${a.name} (${a.id})`).join(", ");
    if (!body.agent.trim()) return "Say which agent should do it.";
    const wanted = body.agent.trim().toLowerCase();
    const agent = plan.agents.find((a) => a.id.toLowerCase() === wanted || a.name.toLowerCase() === wanted);
    if (!agent) return `There is no agent called '${body.agent}'. The residents are: ${list}.`;
    if (agent.id === hostAgentId(plan)) return `${agent.name} is the host and hands out work but takes none. The residents are: ${list}.`;
    const rooms = plan.rooms.filter((r) => r.agent === agent.id);
    let room = rooms[0]?.id ?? null;
    if (body.room) {
      const host = hostAgentId(plan);
      const found = plan.rooms.find((r) => r.id === body.room || r.name.toLowerCase() === body.room?.toLowerCase());
      const names = plan.rooms.filter((r) => r.agent !== host).map((r) => r.name).join(", ");
      if (!found) return `There is no room called '${body.room}'. The rooms are: ${names}.`;
      if (found.agent === host) return `The ${found.name} is the host's and nobody else works there. Choose the room whose project the work is about, or leave the room out.`;
      room = found.id;
    }
    const brief = body.brief.trim();
    if (!brief) return "A job needs a brief that says what to do.";
    if (brief.length > LIMITS.brief_max) return `A brief can be at most ${LIMITS.brief_max} characters; this one has ${brief.length}.`;
    const queued = this.items.filter((j) => j.status === "queued").length;
    if (queued >= LIMITS.max_queued) return `${queued} jobs are already waiting, the most allowed. Wait for some to finish or cancel one.`;
    const title = (body.title?.trim() || brief.split("\n")[0] || "").replace(/\s+/g, " ").slice(0, LIMITS.title_max);
    const job: JobDetails = {
      id: `job${++this.count}a1`,
      title,
      agent: agent.id,
      room,
      status: "queued",
      asked_by: askedBy,
      parent: null,
      created_at: now(),
      started_at: null,
      ended_at: null,
      needed_approval: false,
      last_step: null,
      brief,
      careful: body.careful ?? false,
      via,
      result: "",
      error: "",
      cost_usd: 0,
      steps: [],
    };
    this.items.push(job);
    this.scripts.set(job.id, script ?? genericScript(brief));
    this.changed(job);
    this.pump();
    return job;
  }

  /** Start waiting jobs, oldest first, while places and their agents are free. */
  private pump(): void {
    for (const job of [...this.items].sort((a, b) => a.created_at - b.created_at)) {
      const running = this.items.filter((j) => j.status === "working" && j.parent === null).length;
      if (running >= LIMITS.max_running) return;
      const busy = this.items.some((j) => j.status === "working" && j.agent === job.agent);
      if (job.status === "queued" && !busy) this.begin(job);
    }
  }

  private begin(job: JobDetails): void {
    const plan = this.host.plan();
    const name = plan.agents.find((a) => a.id === job.agent)?.name ?? job.agent;
    const room = plan.rooms.find((r) => r.id === job.room)?.name;
    job.status = "working";
    job.started_at = now();
    const offline = this.host.localModel();
    const agent = plan.agents.find((a) => a.id === job.agent);
    job.model = offline ?? (job.careful ? (agent?.heavy_model ?? agent?.model) : agent?.model) ?? "";
    job.local = offline !== null;
    this.step(job, "started", `${name} started${room ? ` in the ${room}` : ""}.`);
    this.setAgent(job.agent, "working", job.id);
    if (job.room) this.host.emit("room.state", { room: job.room, state: "active" });
    const script = this.scripts.get(job.id);
    if (script) this.play(job, script);
  }

  /** Play the script's steps one after another, then its request, then the steps after it, then its end. */
  private play(job: JobDetails, script: Script): void {
    window.setTimeout(() => {
      if (job.status !== "working") return;
      const [next, ...steps] = script.steps;
      const [later, ...after] = script.after;
      if (next !== undefined) this.progress(job, next, { ...script, steps });
      else if (script.ask) this.ask(job, script.ask, { ...script, ask: null });
      else if (later !== undefined) this.progress(job, later, { ...script, after });
      else this.end(job, "done", script.result, "");
    }, STEP_MS);
  }

  private progress(job: JobDetails, text: string, rest: Script): void {
    this.step(job, "progress", text);
    job.cost_usd += 0.0041;
    this.play(job, rest);
  }

  private ask(job: JobDetails, ask: Ask, rest: Script): void {
    const plan = this.host.plan();
    const agent = plan.agents.find((a) => a.id === job.agent);
    const room = plan.rooms.find((r) => r.id === job.room)?.name;
    const id = `gate-${job.id}`;
    this.waiting.set(id, { job, ask, rest });
    window.setTimeout(() => this.unanswered(id), GATE_S * 1000);
    this.setAgent(job.agent, "waiting", job.id);
    this.host.emit("gate.request", {
      id,
      tool: "shell",
      summary: `${agent?.name ?? job.agent}${room ? `, in the ${room}` : ""}: ${ask.summary.charAt(0).toLowerCase()}${ask.summary.slice(1)}`,
      detail: ask.detail,
      expires_at: now() + GATE_S,
      agent: job.agent,
      agent_name: agent?.name ?? job.agent,
      job: job.id,
    });
  }

  /** Nobody answered in time: the program did not run, and the job says an approval was missed. */
  private unanswered(id: string): void {
    const w = this.waiting.get(id);
    if (!w) return;
    this.resolveGate(id, "timeout");
    w.job.needed_approval = true;
    this.step(w.job, "tool", `${w.ask.detail.split("\n")[0]} (nobody answered in time, so it did not run)`);
    this.play(w.job, { ...w.rest, result: "The tests were not run: nobody answered the request in time." });
  }

  private resolveGate(id: string, decision: "allow" | "deny" | "timeout"): void {
    const w = this.waiting.get(id);
    if (!w) return;
    this.waiting.delete(id);
    this.host.emit("gate.resolved", { id, decision });
    if (w.job.status === "working") this.setAgent(w.job.agent, "working", w.job.id);
  }

  private end(job: JobDetails, status: "done" | "failed" | "cancelled", result: string, error: string): void {
    const wasWorking = job.started_at !== null;
    job.status = status;
    job.ended_at = now();
    job.result = result;
    job.error = error;
    this.step(job, "finished", status === "done" ? "Finished." : status === "failed" ? `Failed: ${error}` : "Cancelled.");
    if (wasWorking) {
      this.setAgent(job.agent, "idle", null);
      if (job.room) this.host.emit("room.state", { room: job.room, state: "dark" });
    }
    if (job.parent === null) this.host.report(structuredClone(job));
    this.pump();
  }

  private step(job: JobDetails, kind: JobStep["kind"], text: string): void {
    const step = { ts: now(), kind, text };
    job.steps.push(step);
    job.last_step = step;
    this.changed(job);
  }

  private setAgent(agent: string, state: AgentStatus["state"], job: string | null): void {
    this.agents[agent] = { state, job };
    this.host.emit("agent.state", { agent, state, job });
  }

  private changed(job: JobDetails): void {
    this.host.emit("job.changed", structuredClone(summary(job)));
  }
}

const no = <T>(message: string): Promise<Result<T>> => Promise.resolve(refused(message));

/** The `job.changed` shape of a job. */
function summary(j: JobDetails): Job {
  const { id, title, agent, room, status, asked_by, parent, created_at, started_at, ended_at, needed_approval, model, local, last_step } = j;
  return { id, title, agent, room, status, asked_by, parent, created_at, started_at, ended_at, needed_approval, ...(model === undefined ? {} : { model }), ...(local === undefined ? {} : { local }), last_step };
}

function genericScript(brief: string): Script {
  return {
    steps: ["Read the notes in the project folder.", "Wrote down what the brief asks for and what is already there."],
    ask: null,
    after: [],
    result: `Done: ${brief.split("\n")[0]}. The notes are tidied and the open questions are listed at the top.`,
  };
}

function seed(t: number): JobDetails[] {
  const min = 60;
  const step = (ago: number, kind: string, text: string): JobStep => ({ ts: t - ago, kind, text });
  const job = (j: Partial<JobDetails> & Pick<JobDetails, "id" | "title" | "agent" | "room" | "status" | "created_at" | "brief">): JobDetails => {
    const steps = j.steps ?? [];
    return {
      asked_by: "host",
      parent: null,
      started_at: null,
      ended_at: null,
      needed_approval: false,
      careful: false,
      via: "text",
      result: "",
      error: "",
      cost_usd: 0,
      model: j.started_at === null || j.started_at === undefined ? "" : j.agent === "maker" ? OPUS : HAIKU,
      local: false,
      ...j,
      steps,
      last_step: steps.at(-1) ?? null,
    };
  };
  return [
    job({
      id: "3f2a91c0",
      title: "Summarise this week's engine notes",
      agent: "steward",
      room: "library",
      status: "done",
      created_at: t - 190 * min,
      started_at: t - 189 * min,
      ended_at: t - 176 * min,
      brief: "Read the engine notes from this week and write a short summary: what changed, what broke, what is still open.",
      result: "Three things changed this week: the date parser was rewritten, the export screen got a CSV path, and the tests moved to vitest. One thing broke (a report that wrote the day before the month) and was fixed. Still open: the CSV path has no tests.",
      cost_usd: 0.0213,
      steps: [
        step(189 * min, "started", "Brass started in the Library."),
        step(186 * min, "tool", "Read notes/engine-2026-11.md"),
        step(181 * min, "progress", "Grouped the notes by day; five days had entries."),
        step(176 * min, "finished", "Finished."),
      ],
    }),
    job({
      id: "7c41d2e8",
      title: "Check the export screen against the spec",
      agent: "checker",
      room: "spare-room",
      status: "failed",
      created_at: t - 95 * min,
      started_at: t - 94 * min,
      ended_at: t - 80 * min,
      needed_approval: true,
      careful: true,
      brief: "Compare the export screen with docs/export-spec.md and list every difference.",
      error: "A program needed a yes and nobody answered, so the check could not run.",
      result: "Compared the first half of the spec; the date column is already right.",
      cost_usd: 0.0538,
      steps: [
        step(94 * min, "started", "Tock started in the Spare Room."),
        step(92 * min, "tool", "Read docs/export-spec.md"),
        step(88 * min, "tool", "Wanted to run npm run export:preview (nobody answered in time)"),
        step(80 * min, "finished", "Failed: A program needed a yes and nobody answered, so the check could not run."),
      ],
    }),
    job({
      id: "a9e07b13",
      title: "Draft the reply to the landlord about the boiler",
      agent: "envoy",
      room: "comms-room",
      status: "working",
      asked_by: "owner",
      via: "window",
      created_at: t - 6 * min,
      started_at: t - 6 * min,
      brief: "Draft a polite reply to the landlord's email about the boiler service: we are home on Thursday morning, not Wednesday.",
      cost_usd: 0.0087,
      steps: [
        step(6 * min, "started", "Wren started in the Comms Room."),
        step(5 * min, "tool", "Read mail/landlord-2026-11-12.eml"),
        step(4 * min, "request", "Asked Rook: Look up the notice period for a boiler visit (job b2d4f6a8)"),
      ],
    }),
    job({
      id: "b2d4f6a8",
      title: "Look up the notice period for a boiler visit",
      agent: "scout",
      room: "comms-room",
      status: "working",
      asked_by: "envoy",
      parent: "a9e07b13",
      via: "",
      created_at: t - 4 * min,
      started_at: t - 4 * min,
      brief: "How much notice must a landlord give before a boiler service visit? Answer with the rule and where it comes from.",
      cost_usd: 0.0031,
      steps: [step(4 * min, "started", "Rook started in the Comms Room."), step(2 * min, "tool", "Searched the web: landlord notice period boiler service visit")],
    }),
    job({
      id: "5d83b0f2",
      title: "Rewrite the date parser so every import uses it",
      agent: "maker",
      room: "workshop",
      status: "done",
      created_at: t - 5 * 60 * min,
      started_at: t - 5 * 60 * min + 30,
      ended_at: t - 4 * 60 * min - 20 * min,
      brief: "Rewrite the engine's date parser so every import goes through one function.",
      result: "The parser is one function now and the three copies are gone. All 214 tests pass.",
      cost_usd: 0.0792,
      steps: [step(5 * 60 * min - 30, "started", "Tink started in the Workshop."), step(4 * 60 * min + 40 * min, "tool", "Edited src/dates.ts"), step(4 * 60 * min + 20 * min, "finished", "Finished.")],
    }),
    job({
      id: "6a17c4e5",
      title: "Run the engine's tests after the parser change",
      agent: "checker",
      room: "workshop",
      status: "failed",
      created_at: t - 3 * 60 * min,
      started_at: t - 3 * 60 * min + 20,
      ended_at: t - 2 * 60 * min - 30 * min,
      needed_approval: true,
      brief: "Run the engine's test suite and report anything that fails.",
      error: "A program needed a yes and nobody answered, so the tests could not run.",
      cost_usd: 0.0114,
      steps: [step(3 * 60 * min - 20, "started", "Tock started in the Workshop."), step(2 * 60 * min + 30 * min, "finished", "Failed: A program needed a yes and nobody answered, so the tests could not run.")],
    }),
    job({
      id: "9b30d1a7",
      title: "Check the CSV export against the spec",
      agent: "maker",
      room: "workshop",
      status: "done",
      created_at: t - 70 * min,
      started_at: t - 69 * min,
      ended_at: t - 52 * min,
      model: LOCAL_MODEL,
      local: true,
      brief: "Compare the CSV export with the spec and list the differences.",
      result: "The export matches the spec except the header row, which is missing the unit column.",
      cost_usd: 0.0287,
      steps: [step(69 * min, "started", "Tink started in the Workshop."), step(60 * min, "tool", "Read docs/export-spec.md"), step(52 * min, "finished", "Finished.")],
    }),
    job({
      id: "e1c5a7d9",
      title: "Tidy the garage inventory",
      agent: "maker",
      room: "garage",
      status: "cancelled",
      created_at: t - 26 * 60 * min,
      ended_at: t - 26 * 60 * min + 40,
      brief: "Sort the garage inventory list by shelf and mark what is missing.",
      error: "Cancelled before it started.",
      steps: [step(26 * 60 * min - 40, "finished", "Cancelled.")],
    }),
  ];
}
