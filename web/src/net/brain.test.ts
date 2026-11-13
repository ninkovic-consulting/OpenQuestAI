import { afterEach, describe, expect, it, vi } from "vitest";
import { asBrainMode, asDeleteAnswer, asLocalListing, asServerTest } from "./brain-guards";
import type { BrainMode } from "./brain-types";
import { asJob } from "./job-guards";
import { MockLocal } from "./mock-local";
import { CATALOG, fitOf, GIB, MOCK_MEMORY, recommendedOf } from "./mock-local-data";
import { effortProblem, levelTable, mockLevels } from "./mock-effort";
import { MockSettings } from "./mock-settings";
import { asPlan } from "./plan";
import { samplePlan } from "./sample-plan";
import { initialState, reduce } from "./store";
import { asOutbound } from "./types";

const QWEN4 = "mlx-community/Qwen3-4B-Instruct-2507-4bit";
const QWEN8 = "mlx-community/Qwen3-8B-4bit";

function mock(announce: (m: BrainMode) => void = () => {}) {
  const plan = samplePlan();
  const house = { plan: () => plan, changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} };
  return new MockSettings(house, announce);
}

afterEach(() => vi.useRealTimers());

describe("the local-model guards", () => {
  const listing = () => new MockLocal().listing({ backend: "mlx", model: QWEN4, server: "http://127.0.0.1:1234/v1", offline: false });

  it("accept the listing the mock serves and refuse one that lost a field", () => {
    expect(asLocalListing(listing())).not.toBeNull();
    const broken = JSON.parse(JSON.stringify(listing())) as { models: { fit: string }[] };
    broken.models[0]!.fit = "huge";
    expect(asLocalListing(broken)).toBeNull();
    expect(asLocalListing({ ...listing(), chosen: null })).toBeNull();
  });

  it("accept a delete answer only with what was deleted and freed", () => {
    expect(asDeleteAnswer({ ...listing(), deleted: QWEN8, freed_bytes: 1 })).not.toBeNull();
    expect(asDeleteAnswer(listing())).toBeNull();
  });

  it("check a server test and a brain mode", () => {
    expect(asServerTest({ ok: false, models: [], message: "Nothing answered." })).not.toBeNull();
    expect(asServerTest({ ok: true, models: [1], message: "" })).toBeNull();
    const mode = { offline: true, answering: "local", local_backend: "mlx", local_model: QWEN4, local_tools: null };
    expect(asBrainMode(mode)).not.toBeNull();
    expect(asBrainMode({ ...mode, answering: "gpt" })).toBeNull();
    expect(asBrainMode({ ...mode, local_tools: "yes" })).toBeNull();
  });

  it("let brain.mode through only when it is shaped like one, and keep it in the store", () => {
    const mode = { offline: true, answering: "local", local_backend: "mlx", local_model: QWEN4, local_tools: true };
    const event = asOutbound({ type: "brain.mode", ts: 1, data: mode });
    expect(event).not.toBeNull();
    expect(asOutbound({ type: "brain.mode", ts: 1, data: { offline: true } })).toBeNull();
    if (!event) return;
    expect(reduce(initialState(), { kind: "event", event }).mode).toEqual(mode);
  });

  it("take a job with or without the model it ran on", () => {
    const job = { id: "a", title: "t", agent: "maker", room: null, status: "done", asked_by: "host", parent: null, created_at: 0, started_at: 0, ended_at: 1, needed_approval: false, last_step: null };
    expect(asJob(job)).not.toBeNull();
    expect(asJob({ ...job, model: QWEN4, local: true })).not.toBeNull();
    expect(asJob({ ...job, model: 3 })).toBeNull();
    expect(asJob({ ...job, local: "yes" })).toBeNull();
  });

  it("need the house's effort levels in a plan", () => {
    expect(asPlan(samplePlan())).not.toBeNull();
    const { effort_levels: _levels, ...without } = samplePlan();
    expect(asPlan(without)).toBeNull();
    expect(asPlan({ ...samplePlan(), effort_levels: { x: [1] } })).toBeNull();
  });
});

describe("the mock's catalog", () => {
  it("marks each model against this Mac's memory as the daemon does", () => {
    const fits = Object.fromEntries(CATALOG.map((m) => [m.title, fitOf(m, MOCK_MEMORY)]));
    expect(fits["Qwen3.5 9B"]).toBe("comfortable");
    expect(fits["Qwen3 Coder 30B"]).toBe("tight");
    expect(fits["Gemma 4 31B"]).toBe("too_big");
    expect(fitOf({ memory_gb: 24, size_bytes: 12e9 }, 24 * GIB)).toBe("comfortable");
  });

  it("recommends the largest comfortable model that uses tools", () => {
    expect(recommendedOf(MOCK_MEMORY)).toBe("mlx-community/Qwen3.5-9B-MLX-4bit");
    expect(recommendedOf(2 * GIB)).toBeNull();
  });

  it("holds every state at once: on disk, failed, idle, too big", () => {
    const rows = new MockLocal().listing({ backend: "mlx", model: QWEN4, server: "", offline: false }).models;
    const state = (id: string) => rows.find((m) => m.id === id)?.download.state;
    expect(state(QWEN8)).toBe("done");
    expect(state("mlx-community/Qwen3.5-4B-MLX-4bit")).toBe("failed");
    expect(state(QWEN4)).toBe("idle");
    expect(rows.some((m) => m.fit === "too_big")).toBe(true);
  });

  it("downloads for a while with progress, then is on disk; a repo that is missing fails", () => {
    vi.useFakeTimers();
    const local = new MockLocal();
    local.start(QWEN4);
    vi.advanceTimersByTime(5000);
    const mid = local.download(QWEN4);
    expect(mid.state).toBe("running");
    expect(mid.done_bytes).toBeGreaterThan(0);
    expect(mid.done_bytes).toBeLessThan(mid.total_bytes ?? 0);
    vi.advanceTimersByTime(8000);
    expect(local.onDisk(QWEN4)).toBe(true);
    local.start("someone/missing-model");
    vi.advanceTimersByTime(3000);
    expect(local.download("someone/missing-model").state).toBe("failed");
    expect(local.remove(QWEN4)).toBeGreaterThan(0);
    expect(local.onDisk(QWEN4)).toBe(false);
  });

  it("answers a server test at LM Studio's address and fails anywhere else", () => {
    expect(MockLocal.testServer("http://127.0.0.1:1234/v1/")).toMatchObject({ ok: true });
    expect(MockLocal.testServer("http://127.0.0.1:9/v1")).toMatchObject({ ok: false, models: [] });
  });
});

describe("offline mode in the mock", () => {
  it("is refused until the model is on this Mac, then accepted, and announced", async () => {
    vi.useFakeTimers();
    const heard: BrainMode[] = [];
    const m = mock((mode) => heard.push(mode));
    const refused = await m.patchSettings({ models: { offline: true } });
    expect(refused.ok).toBe(false);
    expect(!refused.ok && refused.errors[0]?.field).toBe("models.offline");
    expect(!refused.ok && refused.message).toContain("is not downloaded yet");
    expect(heard).toEqual([]);
    await m.downloadLocal(QWEN4);
    await vi.advanceTimersByTimeAsync(13_000);
    const accepted = await m.patchSettings({ models: { offline: true } });
    expect(accepted.ok && accepted.value.applied).toEqual(["models.offline"]);
    expect(heard).toHaveLength(1);
    expect(heard[0]).toMatchObject({ offline: true, answering: "local", local_model: QWEN4 });
  });

  it("refuses to delete the model it uses, and frees the others", async () => {
    const m = mock();
    expect((await m.patchSettings({ models: { local: QWEN8 } })).ok).toBe(true);
    expect((await m.patchSettings({ models: { offline: true } })).ok).toBe(true);
    const blocked = await m.deleteLocal(QWEN8);
    expect(!blocked.ok && blocked.message).toContain("offline mode is using");
    expect((await m.patchSettings({ models: { offline: false } })).ok).toBe(true);
    const gone = await m.deleteLocal(QWEN8);
    expect(gone.ok && gone.value.freed_bytes).toBeGreaterThan(4e9);
  });

  it("needs a server that answers and has the model", async () => {
    const m = mock();
    const nobody = await m.patchSettings({ models: { local_backend: "openai", local_server: "http://127.0.0.1:9/v1", local: "x", offline: true } });
    expect(!nobody.ok && nobody.message).toContain("Offline mode needs the local server");
    const wrong = await m.patchSettings({ models: { local_backend: "openai", local_server: "http://127.0.0.1:1234/v1", local: "x", offline: true } });
    expect(!wrong.ok && wrong.message).toContain("has no model called x");
    const right = await m.patchSettings({ models: { local_backend: "openai", local_server: "http://127.0.0.1:1234/v1", local: "qwen3-8b", offline: true } });
    expect(right.ok && right.value.settings.models.local).toMatchObject({ backend: "openai", offline: true, server: "http://127.0.0.1:1234/v1" });
  });

  it("applies the local model at once, and asks a Hugging Face repo of the app's own backend", async () => {
    const m = mock();
    const r = await m.patchSettings({ models: { local: QWEN8 } });
    expect(r.ok && [r.value.applied, r.value.restart]).toEqual([["models.local"], []]);
    expect((await m.patchSettings({ models: { local: "not a repo" } })).ok).toBe(false);
  });
});

describe("thinking levels in the mock", () => {
  it("differ by model", () => {
    expect(mockLevels("claude-opus-5-5")).toEqual(["low", "medium", "high", "xhigh", "max"]);
    expect(mockLevels("claude-opus-4-6")).toEqual(["low", "medium", "high", "max"]);
    expect(mockLevels("claude-haiku-4-5")).toEqual([]);
    expect(levelTable(["claude-opus-4-6", "claude-opus-4-6"])).toEqual({ "claude-opus-4-6": ["low", "medium", "high", "max"] });
  });

  it("refuse a level the model does not take, in the daemon's words", () => {
    expect(effortProblem("claude-opus-4-6", "xhigh")).toBe("claude-opus-4-6 does not take effort xhigh; it takes low, medium, high, max.");
    expect(effortProblem("claude-haiku-4-5", "high")).toBeNull();
    expect(effortProblem("claude-opus-5-5", "extreme")).toContain("An effort level is one of");
  });

  it("check the host's levels against the models, also when both change together", async () => {
    const m = mock();
    const bad = await m.patchSettings({ models: { heavy: "claude-opus-4-6", heavy_effort: "xhigh" } });
    expect(!bad.ok && bad.errors).toEqual([{ field: "models.heavy_effort", message: "claude-opus-4-6 does not take effort xhigh; it takes low, medium, high, max." }]);
    const good = await m.patchSettings({ models: { heavy: "claude-opus-4-6", heavy_effort: "max" } });
    expect(good.ok && good.value.settings.models.heavy_effort).toBe("max");
  });

  it("set an agent's levels and keep the host's to the talk and heavy levels", async () => {
    const m = mock();
    const r = await m.patchSettings({ agents: { maker: { effort: "high", heavy_effort: "max" } } });
    expect(r.ok && r.value.settings.agents.find((a) => a.id === "maker")).toMatchObject({ effort: "high", heavy_effort: "max" });
    expect((await m.patchSettings({ agents: { maker: { model: "claude-opus-4-6", effort: "xhigh" } } })).ok).toBe(false);
    expect((await m.patchSettings({ agents: { host: { effort: "high" } } })).ok).toBe(false);
    const talk = await m.patchSettings({ models: { talk_effort: "medium" } });
    expect(talk.ok && talk.value.settings.agents.find((a) => a.is_host)?.effort).toBe("medium");
  });

  it("list the levels each model takes", async () => {
    const r = await mock().models();
    const rows = r.ok ? Object.fromEntries(r.value.models.map((x) => [x.id, x.efforts])) : {};
    expect(rows["claude-haiku-4-5"]).toEqual([]);
    expect(rows["claude-opus-4-6"]).not.toContain("xhigh");
  });
});
