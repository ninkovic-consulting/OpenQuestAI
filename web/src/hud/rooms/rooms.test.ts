import { describe, expect, it } from "vitest";
import type { Job, JobStatus } from "../../net/job-types";
import { HOST_TOOLS, samplePlan } from "../../net/sample-plan";
import type { Plan, ToolRef } from "../../net/types";
import type { Board } from "../../scene/residence";
import { RoomSelection } from "./selection";
import { activeIn, agentRooms, agentToOpen, carefulWords, folderWords, jobsInRoom, recentIn, roomCardModel, selectionIn } from "./model";

const NOW = 1_800_000_000;
const tool = (id: string, available: boolean): ToolRef => ({ id, title: id.toUpperCase(), available, built_in: false });

function job(id: string, agent: string, room: string | null, status: JobStatus, over: Partial<Job> = {}): Job {
  return {
    id,
    title: `Job ${id}`,
    agent,
    room,
    status,
    asked_by: "host",
    parent: null,
    created_at: NOW - 1000,
    started_at: status === "queued" ? null : NOW - 900,
    ended_at: status === "done" || status === "failed" || status === "cancelled" ? NOW - 100 : null,
    needed_approval: false,
    last_step: null,
    ...over,
  };
}

const board = (jobs: Job[], agents: Board["agents"] = {}): Board => ({ jobs: Object.fromEntries(jobs.map((j) => [j.id, j])), agents });

function house(): Plan {
  const plan = samplePlan();
  const workshop = plan.rooms.find((r) => r.id === "workshop")!;
  workshop.folders = ["~/Projects/shop", "~/Notes/a-very-long-folder-name/with/more/parts", "~/Projects/engine"];
  workshop.tools = [HOST_TOOLS[4]!, tool("git", true), tool("docker", false)];
  return plan;
}

describe("which jobs belong to a room", () => {
  const all = board([job("a", "maker", "workshop", "working"), job("b", "scout", "workshop", "working"), job("c", "maker", "kitchen", "working"), job("d", "maker", null, "queued")]);

  it("are those whose room it is, visitors included", () => {
    expect(jobsInRoom(all.jobs, "workshop").map((j) => j.id).sort()).toEqual(["a", "b"]);
    expect(jobsInRoom(all.jobs, "attic")).toEqual([]);
  });

  it("working or waiting: those waiting for a yes first, then working, then queued, oldest first", () => {
    const b = board(
      [
        job("q", "maker", "workshop", "queued", { created_at: NOW - 50 }),
        job("w2", "checker", "workshop", "working", { created_at: NOW - 40 }),
        job("w1", "maker", "workshop", "working", { created_at: NOW - 80 }),
        job("g", "scout", "workshop", "working", { created_at: NOW - 10 }),
        job("x", "maker", "workshop", "done"),
        job("y", "maker", "garage", "working"),
      ],
      { scout: { state: "waiting", job: "g" }, maker: { state: "working", job: "w1" } },
    );
    expect(activeIn(b, "workshop").map((a) => [a.job.id, a.phase])).toEqual([["g", "waiting"], ["w1", "working"], ["w2", "working"], ["q", "queued"]]);
  });

  it("finished: the last three that ended, newest first, with no open job among them", () => {
    const jobs = [
      job("1", "maker", "workshop", "done", { ended_at: NOW - 400 }),
      job("2", "maker", "workshop", "failed", { ended_at: NOW - 300 }),
      job("3", "checker", "workshop", "cancelled", { ended_at: NOW - 200 }),
      job("4", "maker", "workshop", "done", { ended_at: NOW - 100 }),
      job("5", "maker", "workshop", "working"),
      job("6", "maker", "garage", "done"),
    ];
    expect(recentIn(board(jobs).jobs, "workshop").map((j) => j.id)).toEqual(["4", "3", "2"]);
    expect(recentIn(board(jobs).jobs, "workshop", 1)).toHaveLength(1);
  });
});

describe("what the room card shows", () => {
  const jobs = [
    job("w", "maker", "workshop", "working", { title: "Fix the date format", last_step: { ts: NOW, kind: "tool", text: "Read src/dates.ts" } }),
    job("v", "scout", "workshop", "working", { title: "Look up the notice period" }),
    job("d", "checker", "workshop", "done", { title: "Run the suite", ended_at: NOW - 120 }),
  ];

  it("names the room, its agent with the short model, the folders in full and each tool's state", () => {
    const card = roomCardModel(house(), board(jobs), "workshop", NOW)!;
    expect(card).toMatchObject({ name: "Workshop", hall: false, agent: { id: "maker", name: "Tink", model: "Opus 5.5", modelId: "claude-opus-5-5" } });
    expect(card.folders).toEqual(["~/Projects/shop", "~/Notes/a-very-long-folder-name/with/more/parts", "~/Projects/engine"]);
    expect(card.tools).toEqual([{ title: "Shell", state: "runs" }, { title: "GIT", state: "runs" }, { title: "DOCKER", state: "missing" }]);
    expect(card.note).toContain("Writing files and running these programs ask you first");
  });

  it("a room without folders says so, and its project tools wait", () => {
    const plan = house();
    plan.rooms.find((r) => r.id === "workshop")!.folders = [];
    const card = roomCardModel(plan, board([]), "workshop", NOW)!;
    expect(card.folders).toEqual([]);
    expect(card.tools[1]).toEqual({ title: "GIT", state: "waits" });
    expect(card.note).toContain("Attach a project folder");
  });

  it("uses the room's own model, else its agent's", () => {
    const plan = house();
    plan.rooms.find((r) => r.id === "kitchen")!.model = "";
    expect(roomCardModel(plan, board([]), "kitchen", NOW)?.agent.model).toBe("Opus 5.5");
    plan.rooms.find((r) => r.id === "kitchen")!.model = "claude-haiku-5-5";
    expect(roomCardModel(plan, board([]), "kitchen", NOW)?.agent.model).toBe("Haiku 5.5");
  });

  it("tells who is at work now, a visitor as one, and what ended lately", () => {
    const card = roomCardModel(house(), board(jobs), "workshop", NOW)!;
    expect(card.now).toEqual([
      { id: "w", title: "Fix the date format", who: "Tink", visiting: false, phase: "working", step: "Read src/dates.ts" },
      { id: "v", title: "Look up the notice period", who: "Rook", visiting: true, phase: "working", step: null },
    ]);
    expect(card.recent).toEqual([{ id: "d", title: "Run the suite", who: "Tock", when: expect.stringMatching(/^\d\d:\d\d$/) as string, outcome: "done" }]);
  });

  it("a quiet room lists nothing", () => {
    const card = roomCardModel(house(), board(jobs), "kitchen", NOW)!;
    expect(card.now).toEqual([]);
    expect(card.recent).toEqual([]);
  });

  it("offers the job field for a resident's room, with what careful does, and not in the Hall", () => {
    expect(roomCardModel(house(), board([]), "workshop", NOW)?.brief).toEqual({ careful: "thinks longer" });
    expect(roomCardModel(house(), board([]), "spare-room", NOW)?.brief).toEqual({ careful: "switches to Opus 5.5" });
    const hall = roomCardModel(house(), board([]), "hall", NOW)!;
    expect(hall).toMatchObject({ hall: true, brief: null, note: "", agent: { name: "Vision" } });
    expect(roomCardModel(house(), board([]), "nowhere", NOW)).toBeNull();
  });

  it("words careful by the agent's heavier model", () => {
    expect(carefulWords({ heavy_model: "claude-opus-5-5" })).toBe("switches to Opus 5.5");
    expect(carefulWords({ heavy_model: null })).toBe("thinks longer");
  });
});

describe("an agent's rooms", () => {
  const lights = { kitchen: "active", garage: "idle" } as const;

  it("are listed in plan order with their folders and their light", () => {
    const rooms = agentRooms(house(), "maker", board([]), lights, null);
    expect(rooms.map((r) => [r.id, r.folders, r.state])).toEqual([["kitchen", 0, "active"], ["game-room", 0, "dark"], ["garage", 0, "idle"], ["workshop", 3, "dark"]]);
  });

  it("show a job in the room over its light, a visitor's too, and mark the selected room", () => {
    const b = board([job("v", "scout", "workshop", "working"), job("q", "maker", "garage", "queued")], { scout: { state: "waiting", job: "v" } });
    const rooms = agentRooms(house(), "maker", b, lights, "workshop");
    expect(rooms.find((r) => r.id === "workshop")).toMatchObject({ state: "waiting", selected: true });
    expect(rooms.find((r) => r.id === "garage")).toMatchObject({ state: "queued", selected: false });
  });

  it("the host's list is the Hall, and an agent with no room has none", () => {
    expect(agentRooms(house(), "host", board([]), {}, null).map((r) => r.id)).toEqual(["hall"]);
    expect(agentRooms(house(), "nobody", board([]), {}, null)).toEqual([]);
  });

  it("count project folders in words", () => {
    expect([0, 1, 3].map(folderWords)).toEqual(["no project folders", "1 project folder", "3 project folders"]);
  });
});

describe("the selection", () => {
  it("holds one room, tells listeners only when it changes", () => {
    const selection = new RoomSelection();
    const heard: (string | null)[] = [];
    selection.subscribe((r) => heard.push(r));
    selection.set("workshop");
    selection.set("workshop");
    selection.set(null);
    expect(heard).toEqual(["workshop", null]);
    expect(selection.get()).toBeNull();
  });

  it("is dropped once the room leaves the plan", () => {
    expect(selectionIn(house(), "workshop")).toBe("workshop");
    expect(selectionIn(house(), "gone")).toBeNull();
    expect(selectionIn(null, "workshop")).toBeNull();
    expect(selectionIn(house(), null)).toBeNull();
  });

  it("opens the selected room's agent's list, and leaves the open one alone when nothing is selected", () => {
    expect(agentToOpen(house(), "workshop", "scout")).toBe("maker");
    expect(agentToOpen(house(), "hall", null)).toBe("host");
    expect(agentToOpen(house(), null, "scout")).toBe("scout");
    expect(agentToOpen(house(), null, null)).toBeNull();
  });
});
