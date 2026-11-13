import { afterEach, describe, expect, it, vi } from "vitest";
import { MockDaemon } from "./mock";
import { rootProblem } from "./mock-folders";
import { mockProject, START_PROJECT } from "./mock-project";
import { isMockFolder, MockSettings } from "./mock-settings";
import { samplePlan } from "./sample-plan";
import { asSettings } from "./settings-guards";
import { Store } from "./store";
import { envelope } from "./types";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("starting a project in mock mode", () => {
  it("is asked for in a few ways", () => {
    expect(START_PROJECT.test("start a project: a recipe box")).toBe(true);
    expect(START_PROJECT.test("Start a new project for me: a recipe box")).toBe(true);
    expect(START_PROJECT.test("restart the project")).toBe(false);
  });

  it("gives research to the scout and software to the maker, and says why on the card", () => {
    const plan = samplePlan();
    const research = mockProject("research the best tents for a winter trip", plan, [4, 1], "Attic");
    expect(research.agent).toBe("scout");
    expect(research.detail).toContain("Agent: Rook (scout). Why: It is research");
    const tool = mockProject("a small tool that renames photos", plan, [4, 1], "Attic");
    expect(tool.agent).toBe("maker");
    expect(tool.detail.split("\n")).toEqual([
      "Project: Small Tool That",
      "Description: a small tool that renames photos",
      "Agent: Tink (maker). Why: It is software to build, the maker's work.",
      "Folder to create: /Users/you/Projects/small-tool-that",
      "Inside it: README.md with the name and description, and git init (git is installed).",
      'Room to add: "Small Tool That", run by Tink, at [4, 1] next to the Attic.',
      "Room tools: Git.",
      "First job for Tink, in that room:",
      expect.stringContaining('Write a first plan for "Small Tool That" in PLAN.md'),
    ]);
    expect(tool.room).toMatchObject({ kind: "extra", agent: "maker", project: "Small Tool That", folders: ["~/Projects/small-tool-that"], at: [4, 1] });
  });

  it("raises the card, and a yes adds the room and hands off the first job there", () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", globalThis);
    const store = new Store();
    const daemon = new MockDaemon(store);
    daemon.send(envelope("input.text", { text: "Start a project: a small tool that renames photos" }));
    vi.advanceTimersByTime(1000);
    const [gate] = store.get().gates;
    expect(gate?.tool).toBe("start_project");
    expect(gate?.summary).toBe("Start a new project");
    expect(gate?.detail).toContain("Folder to create: /Users/you/Projects/small-tool-that");
    daemon.send(envelope("gate.decision", { id: gate?.id ?? "", decision: "allow" }));
    vi.advanceTimersByTime(500);
    expect(store.get().gates).toEqual([]);
    const room = store.get().plan?.rooms.find((r) => r.id === "small-tool-that");
    expect(room).toMatchObject({ agent: "maker", project: "Small Tool That" });
    const job = Object.values(store.get().jobs).find((j) => j.room === "small-tool-that");
    expect(job?.agent).toBe("maker");
  });
});

describe("where new projects go, in mock mode", () => {
  it("must be an existing folder of its own", () => {
    expect(rootProblem("~/Projects", isMockFolder)).toBeNull();
    expect(rootProblem("~/Documents/Notes", isMockFolder)).toBeNull();
    expect(rootProblem("~", isMockFolder)).toContain("the disk, the home folder or a folder above it");
    expect(rootProblem("~/Nowhere", isMockFolder)).toBe("~/Nowhere is not a folder on this Mac.");
    expect(rootProblem("Projects", isMockFolder)).toContain("not a full path");
  });

  it("is in the settings and saved like the daemon saves it", async () => {
    const plan = samplePlan();
    const settings = new MockSettings({
      plan: () => plan,
      changed: () => undefined,
      reset: () => undefined,
      tools: () => [],
      forgetAutomations: () => undefined,
      forgetPhone: () => undefined,
    }, () => undefined, () => undefined);
    const before = await settings.settings();
    expect(before.ok && asSettings(before.value)?.projects).toEqual({ root: "~/Projects" });
    const refused = await settings.patchSettings({ projects: { root: "~" } });
    expect(!refused.ok && refused.errors[0]?.field).toBe("projects.root");
    const saved = await settings.patchSettings({ projects: { root: "~/Documents" } });
    expect(saved.ok && saved.value.settings.projects.root).toBe("~/Documents");
  });
});
