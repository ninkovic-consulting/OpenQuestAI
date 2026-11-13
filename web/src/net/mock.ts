// Mock mode (`?mock=1`): a pretend daemon for development and screenshots.
// It serves the sample plan and plays a scripted sequence through the same
// store actions the real socket uses.

import { cellKey, cellOwners } from "../scene/grid";
import type { Automation, RunStatus } from "./automation-types";
import type { Daemon } from "./daemon";
import type { JobDetails } from "./job-types";
import type { ImageRef } from "./image-types";
import { MockAutomations } from "./mock-automations";
import { folderRefusal } from "./mock-folders";
import { MockImages } from "./mock-images";
import { MockJobs } from "./mock-jobs";
import { MockLibrary } from "./mock-library";
import { MockPhone } from "./mock-phone";
import { MockProcedures } from "./mock-procedures";
import { MockProposals } from "./mock-proposals";
import { MockSettings } from "./mock-settings";
import { hostAgentId, hostRefusal, hostRoom } from "./plan";
import { HOST_TOOLS, samplePlan } from "./sample-plan";
import type { Result } from "./settings-api";
import type { Store } from "./store";
import type {
  AssistantState,
  Cell,
  Door,
  InboundEvent,
  NewRoom,
  OutboundData,
  OutboundEvent,
  OutboundType,
  Plan,
  PostResult,
  ProposeResult,
  Room,
  StateSnapshot,
  ToolRef,
} from "./types";

const WORD_MS = 75;
/** How often a job's report checks whether the assistant is free yet. */
const REPORT_POLL_MS = 500;
/** "ask tink ..." hands a job to Tink, as the host would. */
const ASK_TINK = /^\s*ask tink\b[\s,:]*(?:to\s+)?/i;
const LEVEL_MS = 33;

const projectTool = (id: string, title: string, available: boolean): ToolRef => ({ id, title, available, built_in: false });

/** What mock mode proposes for any folder: a web app on GitHub with a Dockerfile, on a Mac without Docker. */
const MOCK_PROPOSAL: readonly ToolRef[] = [
  projectTool("git", "Git", true),
  projectTool("gh", "GitHub", true),
  projectTool("npm", "npm", true),
  projectTool("docker", "Docker", false),
];
const MOCK_CATALOG: readonly ToolRef[] = [...HOST_TOOLS, ...MOCK_PROPOSAL];

const LONG_REPLY =
  "This afternoon the date parser was rewritten so that every import goes through one function, " +
  "which removed three copies of the same logic. The checker then ran the whole suite twice and found " +
  "a single failure: a report that wrote the day before the month. That is fixed in the workshop now, " +
  "and the suite is green again. Tomorrow the export screen needs the same treatment, and I would " +
  "start with the CSV path, because it has no tests yet and two people rely on it every Monday.";

export class MockDaemon implements Daemon {
  private plan: Plan = mockPlan();
  private speaking: { timers: number[]; text: string; turn: string; done: (() => void) | null } | null = null;
  private turn = 0;
  private pending: number | null = null;
  readonly automations = new MockAutomations({
    changed: (id) => this.emit("automation.changed", { id, change: "updated", automation: null }),
    perform: (a) => this.runAutomation(a),
  });
  readonly phone = new MockPhone();
  readonly library = new MockLibrary();
  readonly images = new MockImages();
  readonly proposals = new MockProposals({ emit: (type, data) => this.emit(type, data) });
  readonly procedures = new MockProcedures({ emit: (type, data) => this.emit(type, data), plan: () => this.plan });
  readonly jobs = new MockJobs({
    emit: <K extends OutboundType>(type: K, data: OutboundData[K]) => this.emit(type, data),
    plan: () => this.plan,
    localModel: () => (this.settings.mode().offline ? this.settings.mode().local_model : null),
    report: (job) => this.reportJob(job),
  });
  readonly settings = new MockSettings({
    plan: () => this.plan,
    changed: () => this.publish(),
    reset: () => {
      const revision = this.plan.revision;
      this.plan = mockPlan();
      this.plan.revision = revision;
      this.publish();
    },
    tools: (ids, agent) => (ids ? ids.flatMap((id) => MOCK_CATALOG.filter((t) => t.id === id).map((t) => ({ ...t }))) : agentTools(agent)),
    forgetAutomations: () => this.automations.clear(),
    forgetPhone: (removeToken) => this.phone.reset(removeToken),
  }, (mode) => this.emit("brain.mode", mode));

  constructor(private readonly store: Store) {}

  start(): void {
    this.store.dispatch({ kind: "connection", connection: "open" });
    // What `GET /api/state` answers on connect, in the daemon's shape.
    const snapshot: StateSnapshot = {
      state: "idle",
      brain: "claude",
      gate_pending: [],
      notices: [{ level: "info", text: "Mock mode: no daemon is connected." }],
      budget: { month: "2026-11", spent_usd: 18.42, cap_usd: 150 },
      mode: this.settings.mode(),
      presence: this.phone.presence(),
    };
    this.store.dispatch({ kind: "snapshot", snapshot, initial: true });
    this.store.dispatch({ kind: "plan", plan: structuredClone(this.plan) });
    void this.jobs.list().then((r) => {
      if (r.ok) this.store.dispatch({ kind: "jobs", list: r.value });
    });
    this.jobs.announce();
    const name = (id: string): string => this.plan.agents.find((a) => a.id === id)?.name ?? id;
    const workshop = this.plan.rooms.find((r) => r.id === "workshop")?.name ?? "Workshop";
    this.at(300, () => this.emit("budget", { month: "2026-11", spent_usd: 18.42, cap_usd: 150 }));
    this.at(600, () => this.setState("listening"));
    this.at(1600, () => this.emit("user.utterance", { text: "What got done on the engine this afternoon?", source: "voice" }));
    this.at(1700, () => this.setState("thinking"));
    this.at(2600, () =>
      this.say(
        `The tests pass now. ${name("checker")} found one bad date format, and ${name("maker")} is fixing it in the ${workshop}.`,
      ),
    );
    this.at(9000, () =>
      this.emit("gate.request", {
        id: "gate-1",
        tool: "shell",
        summary: `${this.plan.assistant.name} wants to run the test suite in the project folder.`,
        detail: "npm test -- --run",
        expires_at: Date.now() / 1000 + 60,
      }),
    );
    this.at(12_000, () => this.addScriptedRoom());
    if (new URLSearchParams(location.search).get("away") === "1") this.playAway();
  }

  send(event: InboundEvent): void {
    switch (event.type) {
      case "input.text":
        this.answerText(event.data.text, event.data.images ?? []);
        break;
      case "input.ptt":
        if (event.data.down) {
          this.interrupt();
          this.setState("listening");
        } else {
          this.setState("transcribing");
          this.at(500, () => this.answer("Is everything quiet in the house?", "voice"));
        }
        break;
      case "input.interrupt":
        this.interrupt();
        break;
      case "gate.decision":
        if (this.jobs.decide(event.data.id, event.data.decision)) break;
        this.emit("gate.resolved", { id: event.data.id, decision: event.data.decision });
        this.emit("notice", {
          level: "info",
          text: event.data.decision === "allow" ? "Command allowed." : "Command declined.",
        });
        break;
      case "hello":
        break;
    }
  }

  /** A few earlier turns, in the shape `/api/history` answers with; one carries two sketches, one an image since removed. */
  async history(): Promise<Result<unknown>> {
    const sketches = await this.images.sketches();
    const removed: ImageRef = { id: "0".repeat(32), width: 400, height: 300 };
    const hour = 3600;
    const now = Date.now() / 1000;
    const turn = (ago: number, source: string, user_text: string, reply: string, status = "ok", images: ImageRef[] = []): Record<string, unknown> => ({
      turn_id: `earlier-${ago}`,
      started_at: now - ago,
      ended_at: now - ago + 4,
      source,
      user_text,
      reply,
      status,
      images,
    });
    return {
      ok: true,
      value: {
        turns: [
          turn(6 * hour, "text", "The photo of the old shelf, for the record.", "Kept. It is with the Library's notes.", "ok", [removed]),
          turn(5 * hour, "text", "Remember that the renderer rewrite is due in March.", "Noted. I will keep that with the engine notes."),
          turn(
            4 * hour,
            "text",
            "Here are the bench sketch and the ground floor. Where should the bench go?",
            "The Workshop has the room: put the bench along its east wall, where the plan leaves a gap of two metres.",
            "ok",
            sketches,
          ),
          turn(3 * hour, "automation", "", "It is time: there are two notes for today, both about the engine."),
          turn(
            2.8 * hour,
            "job",
            'Brass finished job 3f2a91c0, "Summarise this week\'s engine notes".\nBrass\'s result:\nThree things changed this week.',
            "Brass has the engine notes summarised: three changes, one breakage that is already fixed, and the CSV path still has no tests.",
          ),
          turn(2 * hour, "phone", "Is the Mac still awake?", "Yes. Nothing is running and the house is quiet."),
          turn(1 * hour, "voice", "Open the project notes.", "Opening them", "interrupted"),
        ],
      },
    };
  }

  proposeTools(folder: string): Promise<ProposeResult> {
    if (folder.includes("nowhere")) return Promise.resolve({ ok: false, message: `${folder} is not a folder.` });
    return Promise.resolve({ ok: true, tools: MOCK_PROPOSAL.map((t) => ({ ...t })) });
  }

  postRoom(room: NewRoom): Promise<PostResult> {
    const extras = this.plan.rooms.filter((r) => r.kind === "extra").length;
    if (extras >= this.plan.max_extra_rooms)
      return Promise.resolve({ ok: false, message: `The house already has ${extras} extra rooms, the most it can hold.` });
    const folders = room.folders === undefined ? null : folderRefusal(room.folders, this.plan.max_room_folders);
    if (folders !== null) return Promise.resolve({ ok: false, message: folders });
    if (!this.plan.free_slots.some(([x, y]) => x === room.at[0] && y === room.at[1]))
      return Promise.resolve({ ok: false, message: "That slot is not free." });
    const agent = this.plan.agents.find((a) => a.id === room.agent);
    if (!agent) return Promise.resolve({ ok: false, message: `Unknown agent: ${room.agent}` });
    if (agent.id === hostAgentId(this.plan)) return Promise.resolve({ ok: false, message: hostRefusal(this.plan) });
    this.addRoom({
      id: room.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      name: room.name,
      kind: "extra",
      shape: "rect",
      at: room.at,
      size: [1, 1],
      agent: agent.id,
      model: room.model ?? agent.model,
      folders: (room.folders ?? []).map((f) => f.trim()),
      floor: "wood-floor",
      wall: "wallpaper",
      tools: room.tools ? room.tools.flatMap((id) => MOCK_CATALOG.filter((t) => t.id === id).map((t) => ({ ...t }))) : agentTools(agent.id),
      state: "idle",
    });
    return Promise.resolve({ ok: true });
  }

  // ---------------------------------------------------------------- script helpers

  private at(ms: number, fn: () => void): number {
    return window.setTimeout(fn, ms);
  }

  private emit<K extends OutboundType>(type: K, data: OutboundData[K]): void {
    this.store.dispatch({ kind: "event", event: { type, ts: Date.now() / 1000, data } as OutboundEvent });
  }

  /** Like the daemon: the Hall is active while thinking or speaking, idle otherwise. */
  private setState(state: AssistantState): void {
    this.emit("state.changed", { state, brain: "claude" });
    const hall = hostRoom(this.plan)?.id;
    if (hall) this.emit("room.state", { room: hall, state: state === "thinking" || state === "speaking" ? "active" : "idle" });
  }

  /** Typed, perhaps with images. One the daemon no longer has stops the message, as on the daemon. */
  private answerText(text: string, ids: readonly string[]): void {
    const images = this.images.refs(ids);
    if (images === null) {
      this.emit("notice", { level: "warn", text: "An image in that message is no longer here; nothing was sent." });
      return;
    }
    this.answer(text, "text", images);
  }

  private answer(text: string, source: "voice" | "text", images: ImageRef[] = []): void {
    this.interrupt();
    this.emit("user.utterance", { text, source, images });
    this.setState("thinking");
    if (images.length > 0) {
      const seen = images.length === 1 ? "the image" : `the ${images.length} images`;
      this.pending = this.at(900, () => {
        this.pending = null;
        this.say(`I have ${seen} you sent. In mock mode I cannot look at them, but they reached me and they are in the thread.`);
      });
      return;
    }
    if (ASK_TINK.test(text)) return this.askTink(text.replace(ASK_TINK, ""));
    // Asking for detail gets a reply several lines long, to exercise the caption.
    const long = /\b(more|detail|explain|why)\b/i.test(text);
    this.pending = this.at(900, () => {
      this.pending = null;
      this.say(long ? LONG_REPLY : "Everything is quiet. The workshop lights are on and the tests are green.");
    });
  }

  /** The host hands the rest of the message to Tink as a job, and says so. */
  private askTink(rest: string): void {
    const brief = rest.trim() ? rest.trim().charAt(0).toUpperCase() + rest.trim().slice(1) : "Run the engine's test suite and say whether it passes.";
    const made = this.jobs.handOffFromHost("maker", "workshop", brief);
    const reply = typeof made === "string" ? made : `I asked Tink to take it in the Workshop: "${made.title}". I will tell you how it goes.`;
    this.pending = this.at(700, () => {
      this.pending = null;
      this.say(reply);
    });
  }

  /** A job ended: once the assistant is free, a turn of its own with no words from the user, as the daemon runs it. */
  private reportJob(job: JobDetails): void {
    if (this.speaking || this.pending !== null) {
      this.at(REPORT_POLL_MS, () => this.reportJob(job));
      return;
    }
    const name = this.plan.agents.find((a) => a.id === job.agent)?.name ?? job.agent;
    const reply =
      job.status === "done"
        ? `${name} finished "${job.title}". ${job.result}`
        : job.status === "failed"
          ? `${name}'s job "${job.title}" failed: ${job.error}`
          : `${name}'s job "${job.title}" was cancelled.`;
    this.setState("thinking");
    this.pending = this.at(900, () => {
      this.pending = null;
      this.say(reply);
    });
  }

  /** An automation's run: no words from the user, the automation's name in the caption. */
  private runAutomation(a: Automation): Promise<{ status: RunStatus; reply: string }> {
    this.interrupt();
    this.emit("automation.started", { id: a.id, name: a.name });
    this.setState("thinking");
    const reply = `It is time: ${a.instruction.charAt(0).toLowerCase()}${a.instruction.slice(1)}`;
    return new Promise((resolve) => {
      this.at(900, () =>
        this.say(reply, () => {
          this.emit("automation.finished", { id: a.id, name: a.name, status: "ok", reply });
          resolve({ status: "ok", reply });
        }),
      );
    });
  }

  private say(text: string, done: (() => void) | null = null): void {
    const turn = `turn-${++this.turn}`;
    const words = text.split(/(?<= )/);
    const timers: number[] = [];
    this.speaking = { timers, text: "", turn, done };
    this.setState("speaking");
    words.forEach((word, i) =>
      timers.push(
        this.at(i * WORD_MS, () => {
          if (this.speaking) this.speaking.text += word;
          this.emit("vision.delta", { text: word });
        }),
      ),
    );
    const total = words.length * WORD_MS + 1200;
    for (let t = 0; t < total; t += LEVEL_MS) {
      const syllable = Math.abs(Math.sin(t / 95)) * 0.6 + Math.abs(Math.sin(t / 37)) * 0.3;
      const fade = Math.min(1, (total - t) / 400);
      timers.push(this.at(t, () => this.emit("voice.level", { level: Math.min(1, syllable * fade + 0.05) })));
    }
    timers.push(this.at(total, () => this.finish()));
  }

  private finish(): void {
    if (!this.speaking) return;
    const { text, turn, done } = this.speaking;
    this.speaking = null;
    this.emit("vision.reply", { text: text.trim(), turn_id: turn });
    this.setState("idle");
    done?.();
  }

  private interrupt(): void {
    if (this.pending !== null) {
      // A reply that was still being thought about is dropped, as the daemon drops it.
      clearTimeout(this.pending);
      this.pending = null;
      if (!this.speaking) this.setState("idle");
    }
    if (!this.speaking) return;
    for (const t of this.speaking.timers) clearTimeout(t);
    this.finish();
  }

  /** `?away=1`: the owner locks the Mac, an automation runs and a job reports, and the owner comes back. */
  private playAway(): void {
    const presence = (away: boolean): void => this.emit("presence", this.phone.setAway(away));
    this.at(14_000, () => presence(true));
    this.at(14_500, () =>
      void this.automations
        .create({ name: "Evening check", instruction: "Say whether the engine's tests are green.", schedule: { kind: "daily", time: "18:00" }, speak: false })
        .then((r) => (r.ok ? this.automations.run(r.value.id) : r)),
    );
    this.at(15_000, () => this.jobs.handOffFromHost("maker", "workshop", "Fix the date format in the CSV export."));
    this.at(45_000, () => presence(false));
  }

  private addScriptedRoom(): void {
    const slot = this.plan.free_slots.find(([x, y]) => x === 4 && y === 1) ?? this.plan.free_slots[0];
    const scout = this.plan.agents.find((a) => a.id === "scout") ?? this.plan.agents[0];
    if (!slot || !scout) return;
    this.addRoom({
      id: "observatory",
      name: "Observatory",
      kind: "extra",
      shape: "rect",
      at: slot,
      size: [1, 1],
      agent: scout.id,
      model: scout.model,
      folders: [],
      floor: "wood-floor",
      wall: "wallpaper",
      tools: agentTools(scout.id),
      state: "idle",
    });
    this.emit("notice", { level: "info", text: "A new room was added to the house." });
  }

  /** Add a room the way the house backend would: a door toward a neighbour, slots recomputed. */
  private addRoom(room: Room): void {
    const plan = this.plan;
    const owners = cellOwners(plan);
    const [x, y] = room.at;
    const sides: [Door["side"], Cell][] = [
      ["w", [x - 1, y]],
      ["n", [x, y - 1]],
      ["e", [x + 1, y]],
      ["s", [x, y + 1]],
    ];
    const neighbour = sides
      .map(([side, c]) => ({ side, owner: owners.get(cellKey(c[0], c[1])) }))
      .find((n) => n.owner !== undefined && n.owner.shape === "rect");
    plan.rooms.push(room);
    if (neighbour?.owner) plan.doors.push({ a: room.id, b: neighbour.owner.id, cell: room.at, side: neighbour.side });
    owners.set(cellKey(x, y), room);
    plan.free_slots = plan.free_slots.filter(([fx, fy]) => fx !== x || fy !== y);
    for (const [, c] of sides) {
      const taken = owners.has(cellKey(c[0], c[1])) || plan.free_slots.some(([fx, fy]) => fx === c[0] && fy === c[1]);
      if (!taken) plan.free_slots.push(c);
    }
    this.publish();
  }

  /** Announce a change to the plan the way the daemon does: `house.changed`, then the new plan. */
  private publish(): void {
    this.plan.revision += 1;
    this.emit("house.changed", { revision: this.plan.revision });
    const plan = structuredClone(this.plan);
    this.at(120, () => this.store.dispatch({ kind: "plan", plan }));
  }
}

/** The sample house, with the Workshop already working in three project folders. */
function mockPlan(): Plan {
  const plan = samplePlan();
  const workshop = plan.rooms.find((r) => r.id === "workshop");
  if (workshop) {
    workshop.folders = ["~/Projects/engine", "~/Projects/shop", "~/Notes/design"];
    workshop.tools = [HOST_TOOLS[4], ...MOCK_PROPOSAL].filter((t): t is ToolRef => t !== undefined).map((t) => ({ ...t }));
  }
  return plan;
}

/** An agent's default tools in the sample house: the host has the built-ins, the rest none. */
function agentTools(agent: string): ToolRef[] {
  return agent === "host" ? HOST_TOOLS.map((t) => ({ ...t })) : [];
}
