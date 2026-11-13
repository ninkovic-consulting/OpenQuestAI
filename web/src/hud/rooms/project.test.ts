import { afterEach, describe, expect, it, vi } from "vitest";
import { MockDaemon } from "../../net/mock";
import { MockSettings } from "../../net/mock-settings";
import { asPlan } from "../../net/plan";
import { MAX_PROJECT_NAME, projectProblem } from "../../net/project-name";
import { samplePlan } from "../../net/sample-plan";
import { Store } from "../../net/store";
import type { Plan } from "../../net/types";
import { newRoom } from "../room-form";
import { namesFrom } from "../jobs/model";
import { roomEditFrom, roomPatch } from "../settings/room-edit";
import { agentRooms, roomCardModel } from "./model";
import { fieldView, projectLine, suggestProject, tidyName } from "./project";

const NO_BOARD = { jobs: {}, agents: {} };

function house(): Plan {
  const plan = samplePlan();
  const workshop = plan.rooms.find((r) => r.id === "workshop")!;
  workshop.folders = ["~/Projects/shop"];
  workshop.project = "Shop";
  const garage = plan.rooms.find((r) => r.id === "garage")!;
  garage.folders = ["~/Projects/harbor-books-project"];
  return plan;
}

describe("the guards for a project name", () => {
  it("accept a name, a blank and the longest length", () => {
    expect(projectProblem("Harbor Books")).toBeNull();
    expect(projectProblem("   ")).toBeNull();
    expect(projectProblem("x".repeat(MAX_PROJECT_NAME))).toBeNull();
  });

  it("refuse a long name, a second line, a control character and a folder path, in the daemon's words", () => {
    expect(projectProblem("x".repeat(MAX_PROJECT_NAME + 1))).toBe("The project name is 61 characters; use at most 60.");
    expect(projectProblem("a\nb")).toBe("The project name must be one line of plain text.");
    expect(projectProblem("a\u0007")).toBe("The project name must be one line of plain text.");
    expect(projectProblem("~/Projects/shop")).toContain("put folders in Project folders");
    expect(projectProblem(" /Users/me/shop")).toContain("looks like a folder path");
  });
});

describe("the name a folder suggests", () => {
  it("tidies the first folder's own name into words", () => {
    expect(suggestProject(["~/Projects/harbor-books-project"])).toBe("Harbor Books Project");
    expect(suggestProject(["/Users/me/code/shop_api/"])).toBe("Shop Api");
    expect(suggestProject(["~/Projects/HarborBooks", "~/Other"])).toBe("Harbor Books");
    expect(suggestProject(["~/Projects/harbor.books"])).toBe("Harbor Books");
    expect(suggestProject(["~/Projects/engine"])).toBe("Engine");
  });

  it("leaves capitals already there alone", () => {
    expect(tidyName("shop-API")).toBe("Shop API");
  });

  it("offers nothing without a folder, for the home folder or the disk, or for a name too long to use", () => {
    expect(suggestProject([])).toBeNull();
    expect(suggestProject(["  "])).toBeNull();
    expect(suggestProject(["~"])).toBeNull();
    expect(suggestProject(["/"])).toBeNull();
    expect(suggestProject([`~/${"a".repeat(MAX_PROJECT_NAME + 1)}`])).toBeNull();
  });
});

describe("the card and the agent's list", () => {
  it("say the name, or that there is none when the room has folders to suggest one from", () => {
    expect(projectLine({ project: "Shop", folders: [] })).toEqual({ kind: "named", name: "Shop" });
    expect(projectLine({ project: null, folders: ["~/a"] })).toEqual({ kind: "none" });
    expect(projectLine({ project: null, folders: [] })).toBeNull();
    const plan = house();
    expect(roomCardModel(plan, NO_BOARD, "workshop", 0)?.project).toEqual({ kind: "named", name: "Shop" });
    expect(roomCardModel(plan, NO_BOARD, "garage", 0)?.project).toEqual({ kind: "none" });
    expect(roomCardModel(plan, NO_BOARD, "attic", 0)?.project).toBeNull();
  });

  it("put the name in the agent's room list", () => {
    const plan = house();
    const rooms = agentRooms(plan, "maker", NO_BOARD, {}, null);
    expect(rooms.find((r) => r.id === "workshop")?.project).toBe("Shop");
    expect(rooms.find((r) => r.id === "garage")?.project).toBeNull();
  });

  it("put it beside the room in a job's names", () => {
    const names = namesFrom(house());
    expect(names.project("workshop")).toBe("Shop");
    expect(names.project("garage")).toBeNull();
    expect(names.project(null)).toBeNull();
  });
});

describe("saving a project name", () => {
  const plan = house();
  const workshop = plan.rooms.find((r) => r.id === "workshop")!;

  it("sends it when it changed, trimmed, and an empty string when it was emptied", () => {
    const before = roomEditFrom(plan, workshop);
    expect(before.project).toBe("Shop");
    expect(roomPatch(before, { ...before, project: " Shop " }, null, false, false)).toEqual({});
    expect(roomPatch(before, { ...before, project: " Shop Engine " }, null, false, false)).toEqual({ project: "Shop Engine" });
    expect(roomPatch(before, { ...before, project: "  " }, null, false, false)).toEqual({ project: "" });
  });

  it("puts a new room's name in the body only when there is one", () => {
    const fields = { name: "Den", agent: "maker", at: [4, 1] as [number, number], folders: [], model: "" };
    expect(newRoom({ ...fields, project: " Harbor Books " }, null).project).toBe("Harbor Books");
    expect(newRoom({ ...fields, project: "  " }, null)).not.toHaveProperty("project");
    expect(newRoom(fields, null)).not.toHaveProperty("project");
  });

  it("is part of the plan the window accepts: a string or null, nothing else", () => {
    const raw = JSON.parse(JSON.stringify(house())) as { rooms: Record<string, unknown>[] };
    expect(asPlan(raw)?.rooms.find((r) => r.id === "workshop")?.project).toBe("Shop");
    raw.rooms[0]!["project"] = 3;
    expect(asPlan(raw)).toBeNull();
    delete raw.rooms[0]!["project"];
    expect(asPlan(raw)).toBeNull();
  });
});

describe("the field", () => {
  const garage = ["~/Projects/harbor-books-project"];

  it("offers the folder's name as placeholder and as a button, and fills nothing in by itself", () => {
    expect(fieldView("", garage, "")).toEqual({ placeholder: "Harbor Books Project", offer: "Harbor Books Project", error: "" });
  });

  it("offers nothing once it holds a name, and an example when there is no folder to suggest from", () => {
    expect(fieldView("Mine", garage, "").offer).toBeNull();
    expect(fieldView("  ", garage, "").offer).toBe("Harbor Books Project");
    expect(fieldView("", [], "")).toEqual({ placeholder: "The project's name, such as Harbor Books", offer: null, error: "" });
  });

  it("shows a refusal first, else the guard's message for the text", () => {
    expect(fieldView("~/Projects/shop", [], "").error).toContain("looks like a folder path");
    expect(fieldView("Shop", [], "").error).toBe("");
    expect(fieldView("~/Projects/shop", [], "Room 'Den': nope.").error).toBe("Room 'Den': nope.");
  });
});

describe("mock mode", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const settings = (plan: Plan): MockSettings =>
    new MockSettings({ plan: () => plan, changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} });

  it("sets, clears and refuses a project name on a room", async () => {
    const plan = samplePlan();
    const m = settings(plan);
    const workshop = (): string | null | undefined => plan.rooms.find((r) => r.id === "workshop")?.project;
    expect((await m.patchRoom("workshop", { project: " Shop " })).ok).toBe(true);
    expect(workshop()).toBe("Shop");
    expect((await m.patchRoom("workshop", { project: "" })).ok).toBe(true);
    expect(workshop()).toBeNull();
    const refused = await m.patchRoom("workshop", { project: "~/shop" });
    expect(refused.ok).toBe(false);
    expect(!refused.ok && refused.errors[0]?.field).toBe("project");
    expect(workshop()).toBeNull();
  });

  it("shows rooms with and without a project name, and gives a new room its name", async () => {
    vi.stubGlobal("window", { setTimeout: (fn: () => void) => (fn(), 0) });
    const store = new Store();
    const daemon = new MockDaemon(store);
    const slot = samplePlan().free_slots[0]!;
    expect(await daemon.postRoom({ name: "Den", agent: "maker", at: slot, project: "x".repeat(61) })).toEqual({ ok: false, message: projectProblem("x".repeat(61)) });
    expect(await daemon.postRoom({ name: "Den", agent: "maker", at: slot, project: " Harbor Books " })).toEqual({ ok: true });
    const rooms = store.get().plan?.rooms ?? [];
    expect(rooms.find((r) => r.name === "Den")?.project).toBe("Harbor Books");
    expect(rooms.find((r) => r.id === "workshop")?.project).toBe("Shop Engine");
    expect(rooms.find((r) => r.id === "garage")).toMatchObject({ project: null, folders: ["~/Projects/harbor-books-project"] });
  });
});
