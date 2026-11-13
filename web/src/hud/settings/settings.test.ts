import { describe, expect, it } from "vitest";
import { MockSettings } from "../../net/mock-settings";
import { samplePlan } from "../../net/sample-plan";
import type { ModelListing, PatchAnswer, Settings } from "../../net/settings-types";
import type { Plan } from "../../net/types";
import { modelChoices, modelDetail, OWN_MODEL } from "../pickers/model-picker";
import { fromProposal } from "../room-form";
import { buildPatch, changedFields, draftFrom, placeErrors, rebase, restartLine, saveSummary } from "./draft";
import { formatBytes, formatDay, formatDownload, formatPrice, formatTokens, modelOption, voiceLabel } from "./format";
import { agentsFor, isHostRoom, roomEditFrom, roomPatch } from "./room-edit";
import { back, forward, skip, startFlow, stepCount, stepOf, summary } from "./wizard/flow";

function mockHouse(plan: Plan = samplePlan()) {
  return { plan: () => plan, changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} };
}

async function settings(): Promise<Settings> {
  const r = await new MockSettings(mockHouse()).settings();
  if (!r.ok) throw new Error("mock settings refused");
  return r.value;
}

describe("the settings draft", () => {
  it("leaves the host agent out: its name and model follow the assistant", async () => {
    const d = draftFrom(await settings());
    expect(d["agents.maker.name"]).toBe("Tink");
    expect(d).not.toHaveProperty("agents.host.name");
    expect(d["gate.tiers.shell"]).toBe("ask");
    expect(d["budget.cap_usd"]).toBe("150");
  });

  it("sends only changed fields of the group, nested and typed", async () => {
    const saved = draftFrom(await settings());
    const draft = { ...saved, "budget.cap_usd": "200.5", "models.talk": "claude-sonnet-5-5", "assistant.name": "Juniper", "voice.followup_s": "20.0" };
    const { patch, errors } = buildPatch(saved, draft, ["models.", "budget."]);
    expect(errors).toEqual([]);
    expect(patch).toEqual({ models: { talk: "claude-sonnet-5-5" }, budget: { cap_usd: 200.5 } });
    expect(changedFields(saved, draft, ["voice."])).toEqual([]);
  });

  it("nests agent and tier fields the way the daemon reads them", async () => {
    const saved = draftFrom(await settings());
    const draft = { ...saved, "agents.maker.name": " Smith ", "gate.tiers.open_url": "free" };
    expect(buildPatch(saved, draft, ["agents.", "gate."]).patch).toEqual({ agents: { maker: { name: "Smith" } }, gate: { tiers: { open_url: "free" } } });
  });

  it("keeps a number field that is not a number out of the body, as its own error", async () => {
    const saved = draftFrom(await settings());
    const { patch, errors } = buildPatch(saved, { ...saved, "budget.cap_usd": "lots" }, ["budget."]);
    expect(patch).toEqual({});
    expect(errors).toEqual([{ field: "budget.cap_usd", message: "Enter a number." }]);
  });

  it("puts errors beside their fields and the rest in general", () => {
    const placed = placeErrors(
      [
        { field: "budget.cap_usd", message: "Too much." },
        { field: "agents", message: "This house cannot be edited." },
      ],
      ["budget.cap_usd", "assistant.name"],
    );
    expect(placed.byField.get("budget.cap_usd")).toBe("Too much.");
    expect(placed.general).toEqual(["This house cannot be edited."]);
  });

  it("rebases: the saved group takes the new values, edits elsewhere stay", async () => {
    const s = await settings();
    const old = draftFrom(s);
    const next = draftFrom({ ...s, assistant: { name: "Juniper" } });
    const draft = { ...old, "assistant.name": "Juni", "voice.tts_voice": "bf_emma" };
    const r = rebase(old, next, draft, ["assistant."]);
    expect(r["assistant.name"]).toBe("Juniper");
    expect(r["voice.tts_voice"]).toBe("bf_emma");
    expect(rebase(old, next, draft, [""])["voice.tts_voice"]).toBe("af_heart");
  });

  it("says plainly what applied and what waits for a restart", async () => {
    const s = await settings();
    const answer: PatchAnswer = { changed: ["assistant.name", "models.talk"], applied: ["assistant.name"], restart: ["models.talk"], settings: s };
    expect(saveSummary(answer)).toBe("Saved. Applied now: assistant's name. Takes effect after a restart: talk model.");
    expect(saveSummary({ ...answer, changed: [] })).toBe("Nothing changed.");
    expect(restartLine({ ...s, restart_pending: ["models.heavy", "key"] })).toBe("Restart needed for: heavy model, API key.");
    expect(restartLine(s)).toBeNull();
  });
});

describe("formatting", () => {
  it("prices per million tokens, or says the price is not known", () => {
    expect(formatPrice({ input_per_mtok: 3, output_per_mtok: 15 })).toBe("$3 in / $15 out per million tokens");
    expect(formatPrice({ input_per_mtok: 0.8, output_per_mtok: 4 })).toBe("$0.80 in / $4 out per million tokens");
    expect(formatPrice(null)).toBe("price not known");
  });

  it("names a model with its price and its retiring date", () => {
    const m = { id: "x", display_name: "Claude X", max_input_tokens: null, max_tokens: null, retires_at: "2026-11-30", price: { input_per_mtok: 15, output_per_mtok: 75 }, efforts: [] };
    expect(modelOption(m)).toBe("Claude X · $15 / $75 per M · retires 30 Nov 2026");
    expect(modelOption({ ...m, retires_at: null, price: null })).toBe("Claude X · price not known");
    expect(formatDay("not a date")).toBe("not a date");
  });

  it("sizes, tokens, downloads and voices", () => {
    expect(formatBytes(2_100_000_000)).toBe("2.1 GB");
    expect(formatBytes(640_000_000)).toBe("640 MB");
    expect(formatTokens(1_000_000)).toBe("1M");
    expect(formatTokens(200_000)).toBe("200k");
    expect(formatDownload({ state: "running", done_bytes: 500_000_000, total_bytes: 2_000_000_000, message: null })).toBe("Downloading… 500 MB of 2.0 GB");
    expect(formatDownload({ state: "idle", done_bytes: 0, total_bytes: 2_100_000_000, message: null })).toBe("Not downloaded · about 2.1 GB");
    expect(formatDownload({ state: "failed", done_bytes: 0, total_bytes: null, message: "disk full" })).toBe("Did not finish: disk full");
    expect(voiceLabel("bm_george")).toBe("George (British, male)");
    expect(voiceLabel("odd")).toBe("odd");
  });
});

describe("the model picker's choices", () => {
  const listing: ModelListing = {
    source: "api",
    fetched_at: null,
    models: [{ id: "claude-opus-5-5", display_name: "Claude Opus 5.5", max_input_tokens: 1_000_000, max_tokens: null, retires_at: null, price: null, efforts: [] }],
  };

  it("offers the agent's own model first, sending nothing", () => {
    const choices = modelChoices(listing, "", OWN_MODEL);
    expect(choices[0]).toEqual({ value: "", label: OWN_MODEL });
    expect(choices[1]?.label).toBe("Claude Opus 5.5 · price not known");
  });

  it("keeps a current model the list lacks", () => {
    expect(modelChoices(listing, "claude-old", null).map((c) => c.value)).toEqual(["claude-opus-5-5", "claude-old"]);
    expect(modelDetail(listing.models[0], "")).toBe("price not known · 1M tokens of context");
  });
});

describe("editing a room", () => {
  const plan = samplePlan();
  const workshop = plan.rooms.find((r) => r.id === "workshop")!;
  const hall = plan.rooms.find((r) => r.id === "hall")!;
  const tool = (id: string) => ({ id, title: id, available: true, built_in: false });

  it("starts from the room, with the agent's model as its own", () => {
    expect(roomEditFrom(plan, workshop)).toEqual({ name: "Workshop", agent: "maker", folders: [], model: "" });
  });

  it("never offers the host for another room, and only the host for the Hall", () => {
    expect(agentsFor(plan, workshop).map((a) => a.id)).not.toContain("host");
    expect(agentsFor(plan, hall).map((a) => a.id)).toEqual(["host"]);
    expect(isHostRoom(plan, hall)).toBe(true);
  });

  it("sends only what changed; the Hall keeps its agent", () => {
    const before = roomEditFrom(plan, workshop);
    expect(roomPatch(before, { ...before, name: " Forge " }, null, false, false)).toEqual({ name: "Forge" });
    expect(roomPatch(before, { ...before, model: "claude-sonnet-5-5" }, null, false, false)).toEqual({ model: "claude-sonnet-5-5" });
    expect(roomPatch(before, { ...before, agent: "scout" }, null, false, true)).toEqual({});
  });

  it("sends the whole folder list, with tools for a new folder", () => {
    const before = roomEditFrom(plan, workshop);
    const folders = ["~/Projects/my-app", "~/Projects/shop"];
    const picks = fromProposal(folders, [tool("git"), tool("npm")]);
    expect(roomPatch(before, { ...before, folders }, picks, false, false)).toEqual({ folders, tools: ["git", "npm"] });
    expect(roomPatch(before, { ...before, folders: [" ~/Projects/my-app ", ""] }, null, false, false)).toEqual({ folders: ["~/Projects/my-app"] });
  });

  it("sends the list when a folder is removed or the order changes, and nothing when it is the same", () => {
    const withTwo = { ...roomEditFrom(plan, workshop), folders: ["~/a", "~/b"] };
    expect(roomPatch(withTwo, { ...withTwo, folders: ["~/b"] }, null, false, false)).toEqual({ folders: ["~/b"] });
    expect(roomPatch(withTwo, { ...withTwo, folders: ["~/b", "~/a"] }, null, false, false)).toEqual({ folders: ["~/b", "~/a"] });
    expect(roomPatch(withTwo, { ...withTwo }, null, false, false)).toEqual({});
  });

  it("detaching every folder sends an empty list and clears the tools", () => {
    const withFolder = { ...roomEditFrom(plan, workshop), folders: ["~/Projects/my-app"] };
    expect(roomPatch(withFolder, { ...withFolder, folders: [] }, null, false, false)).toEqual({ folders: [], tools: null });
  });

  it("sends tools only for a proposal of these folders, after a change or a toggle", () => {
    const withFolder = { ...roomEditFrom(plan, workshop), folders: ["~/Projects/my-app"] };
    const same = fromProposal(["~/Projects/my-app"], [tool("git")], []);
    expect(roomPatch(withFolder, withFolder, same, false, false)).toEqual({});
    expect(roomPatch(withFolder, withFolder, same, true, false)).toEqual({ tools: [] });
    expect(roomPatch(withFolder, withFolder, fromProposal(["~/elsewhere"], [tool("git")]), true, false)).toEqual({});
  });
});

describe("the wizard's steps", () => {
  it("counts and moves forward, keeping how each step ended", () => {
    let flow = forward(startFlow());
    expect(stepOf(flow)).toBe("key");
    expect(stepCount(flow)).toBe("Step 2 of 8");
    flow = forward(flow, { status: "done", text: "Stored." });
    flow = skip(flow);
    expect(stepOf(flow)).toBe("microphone");
    expect(flow.outcomes.downloads).toEqual({ status: "skipped", text: "Skipped" });
    flow = back(flow);
    expect(stepOf(flow)).toBe("downloads");
  });

  it("skipping on welcome goes to the summary with every task skipped", () => {
    const flow = skip(startFlow());
    expect(stepOf(flow)).toBe("done");
    expect(summary(flow).map((s) => s.outcome.status)).toEqual(["skipped", "skipped", "skipped", "skipped", "skipped", "skipped"]);
    expect(skip(flow)).toBe(flow);
  });

  it("never goes past the ends", () => {
    expect(back(startFlow()).index).toBe(0);
    let flow = startFlow();
    for (let i = 0; i < 12; i++) flow = forward(flow);
    expect(stepOf(flow)).toBe("done");
    expect(summary(flow).find((s) => s.id === "room")?.outcome.text).toBe("Not reached");
  });
});
