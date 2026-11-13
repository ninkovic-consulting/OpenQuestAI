import { afterEach, describe, expect, it, vi } from "vitest";
import { MockDaemon } from "./mock";
import { folderRefusal } from "./mock-folders";
import { MockSettings } from "./mock-settings";
import { samplePlan } from "./sample-plan";
import { Store } from "./store";
import type { Plan } from "./types";

describe("the mock's rules for a room's folders", () => {
  it("accept a list of separate folders, and an empty one", () => {
    expect(folderRefusal(["~/Projects/shop", "~/Projects/engine", "~/Notes"], 8)).toBeNull();
    expect(folderRefusal([], 8)).toBeNull();
    expect(folderRefusal(["~/Projects/shop", "~/Projects/shopping"], 8)).toBeNull();
  });

  it("refuse more than the limit", () => {
    const nine = Array.from({ length: 9 }, (_, i) => `~/p${i}`);
    expect(folderRefusal(nine, 8)).toBe("A room can have at most 8 folders.");
    expect(folderRefusal(nine.slice(0, 8), 8)).toBeNull();
  });

  it("refuse a duplicate, even with a trailing slash", () => {
    expect(folderRefusal(["~/Projects/shop", "~/Projects/shop/"], 8)).toBe("~/Projects/shop is listed twice.");
  });

  it("refuse one folder inside another, whichever comes first", () => {
    expect(folderRefusal(["~/Projects", "~/Projects/shop"], 8)).toBe("~/Projects/shop is inside ~/Projects; keep one of them.");
    expect(folderRefusal(["~/Projects/shop", "~/Projects"], 8)).toBe("~/Projects/shop is inside ~/Projects; keep one of them.");
  });

  it("refuse the home folder, an empty path and a missing folder", () => {
    expect(folderRefusal(["~"], 8)).toContain("home folder");
    expect(folderRefusal(["~/"], 8)).toContain("home folder");
    expect(folderRefusal(["~/a", " "], 8)).toBe("A folder path cannot be empty.");
    expect(folderRefusal(["~/nowhere"], 8)).toBe("~/nowhere is not a folder.");
  });
});

describe("the mock house applies them", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const settings = (plan: Plan): MockSettings =>
    new MockSettings({ plan: () => plan, changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} });

  it("saves the whole list on a room, and an empty one detaches everything", async () => {
    const plan = samplePlan();
    const m = settings(plan);
    expect((await m.patchRoom("workshop", { folders: ["~/a", " ~/b "] })).ok).toBe(true);
    expect(plan.rooms.find((r) => r.id === "workshop")?.folders).toEqual(["~/a", "~/b"]);
    expect((await m.patchRoom("workshop", { folders: [] })).ok).toBe(true);
    expect(plan.rooms.find((r) => r.id === "workshop")?.folders).toEqual([]);
  });

  it("refuses a duplicate with an error for the folders field, leaving the room as it was", async () => {
    const plan = samplePlan();
    const m = settings(plan);
    await m.patchRoom("workshop", { folders: ["~/a"] });
    const r = await m.patchRoom("workshop", { folders: ["~/a", "~/a"] });
    expect(r).toEqual({ ok: false, message: "~/a is listed twice.", errors: [{ field: "folders", message: "~/a is listed twice." }] });
    expect(plan.rooms.find((r2) => r2.id === "workshop")?.folders).toEqual(["~/a"]);
  });

  it("refuses a new room whose folders break a rule, and gives a good one its folders", async () => {
    vi.stubGlobal("window", { setTimeout: (fn: () => void) => (fn(), 0) });
    const store = new Store();
    const daemon = new MockDaemon(store);
    const slot = samplePlan().free_slots[0];
    if (!slot) throw new Error("the sample plan has a free slot");
    const bad = await daemon.postRoom({ name: "Den", agent: "maker", at: slot, folders: ["~/Projects", "~/Projects/shop"] });
    expect(bad).toEqual({ ok: false, message: "~/Projects/shop is inside ~/Projects; keep one of them." });
    expect(await daemon.postRoom({ name: "Den", agent: "maker", at: slot, folders: [" ~/Projects/shop ", "~/Notes"] })).toEqual({ ok: true });
    expect(store.get().plan?.rooms.find((r) => r.name === "Den")?.folders).toEqual(["~/Projects/shop", "~/Notes"]);
  });
});
