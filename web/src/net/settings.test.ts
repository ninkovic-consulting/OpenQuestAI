import { afterEach, describe, expect, it, vi } from "vitest";
import { readRefusal } from "./api";
import { flatten, MockSettings, mockFolders } from "./mock-settings";
import { samplePlan } from "./sample-plan";
import { asDownloads, asFieldErrors, asModelListing, asSettings, asSpeakTest, asVoiceState } from "./settings-guards";
import { foldersQuery } from "./settings-http";
import type { Plan } from "./types";

function mock(plan: Plan = samplePlan()): MockSettings {
  return new MockSettings({ plan: () => plan, changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("type guards", () => {
  it("accept the mock's settings and refuse a broken copy", async () => {
    const r = await mock().settings();
    if (!r.ok) throw new Error("refused");
    expect(asSettings(JSON.parse(JSON.stringify(r.value)))).not.toBeNull();
    expect(asSettings({ ...r.value, key: { stored: "yes", source: null } })).toBeNull();
    expect(asSettings({ ...r.value, gate: { ...r.value.gate, tiers: { shell: "sometimes" } } })).toBeNull();
    expect(asVoiceState({ ...r.value.voice, mic: "maybe" })).toBeNull();
    expect(asVoiceState({ ...r.value.voice, mic: "silent" })).not.toBeNull();
    expect(asSettings({ ...r.value, gate: { ...r.value.gate, free_at_the_mac_only: undefined } })).toBeNull();
    expect(asSettings({ ...r.value, gate: { ...r.value.gate, free_for_jobs_from_the_mac: undefined } })).toBeNull();
    expect(asSettings({ ...r.value, gate: { ...r.value.gate, free_for_jobs_from_the_mac: [1] } })).toBeNull();
    expect(asSpeakTest({ ok: true, message: "Said." })).toEqual({ ok: true, message: "Said." });
    expect(asSpeakTest({ ok: "yes", message: "Said." })).toBeNull();
  });

  it("fill in what a model listing leaves out", () => {
    const listing = asModelListing({ source: "built_in", models: [{ id: "claude-x", display_name: "Claude X" }] });
    expect(listing?.models[0]).toEqual({ id: "claude-x", display_name: "Claude X", max_input_tokens: null, max_tokens: null, retires_at: null, price: null, efforts: [] });
    expect(asModelListing({ source: "somewhere", models: [] })).toBeNull();
  });

  it("narrow downloads and field errors", () => {
    const d = { state: "running", done_bytes: 1, total_bytes: null, message: null };
    expect(asDownloads({ local_model: d, speech_models: d })).not.toBeNull();
    expect(asDownloads({ local_model: d })).toBeNull();
    expect(asFieldErrors({ errors: [{ field: "budget.cap_usd", message: "No." }] })).toHaveLength(1);
    expect(asFieldErrors("plain")).toBeNull();
  });
});

describe("refusals", () => {
  it("read a plain detail, field errors, or the body as it came", () => {
    expect(readRefusal(400, JSON.stringify({ detail: "Not a key." }))).toEqual({ message: "Not a key.", errors: [] });
    const errors = [{ field: "assistant.name", message: "Too long." }];
    expect(readRefusal(400, JSON.stringify({ detail: { errors } }))).toEqual({ message: "Too long.", errors });
    expect(readRefusal(502, "")).toEqual({ message: "The assistant answered 502.", errors: [] });
  });
});

describe("folder suggestions", () => {
  it("are asked for only once the text names a folder, with the prefix in the query", () => {
    expect(foldersQuery("Pro")).toBeNull();
    expect(foldersQuery("  ")).toBeNull();
    expect(foldersQuery(" ~/Pro ")).toBe("/api/fs/dirs?prefix=%7E%2FPro");
    expect(foldersQuery("/Users")).toBe("/api/fs/dirs?prefix=%2FUsers");
  });

  it("in mock mode follow the daemon's rules", () => {
    const names = (prefix: string): string[] => {
      const r = mockFolders(prefix);
      return r.ok ? r.value.map((d) => d.path) : [`refused: ${r.message}`];
    };
    expect(names("~/pro")).toEqual(["~/Projects"]);
    expect(names("~/Projects/")).toContain("~/Projects/my-app");
    expect(names("~/")).not.toContain("~/.config");
    expect(names("~/.c")).toEqual(["~/.config"]);
    expect(names("/Us")).toEqual(["/Users"]);
    expect(names("~/../etc")[0]).toMatch(/^refused/);
    expect(names("~root")[0]).toMatch(/^refused/);
    expect(names("Projects")[0]).toMatch(/^refused/);
  });
});

describe("the mock's settings answers", () => {
  it("start on first run, so the wizard shows", async () => {
    const r = await mock().settings();
    expect(r.ok && r.value.setup.first_run).toBe(true);
  });

  it("refuse the host's name and a bad tier, field by field, all or nothing", async () => {
    const m = mock();
    const r = await m.patchSettings({ gate: { tiers: { shell: "sometimes" } }, agents: { host: { name: "X" } }, assistant: { name: "Juniper" } });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.map((e) => e.field)).toEqual(["gate.tiers.shell", "agents.host.name"]);
    const after = await m.settings();
    expect(after.ok && after.value.assistant.name).toBe("Vision");
  });

  it("let shell be free, for what the owner types or says at the Mac", async () => {
    const m = mock();
    const r = await m.patchSettings({ gate: { tiers: { shell: "free" } } });
    expect(r.ok && r.value.settings.gate.tiers["shell"]).toBe("free");
    expect(r.ok && r.value.settings.gate.free_at_the_mac_only).toEqual(["shell"]);
  });

  it("let run_program be free, for jobs the owner starts at the Mac", async () => {
    const m = mock();
    const r = await m.patchSettings({ gate: { tiers: { run_program: "free" } } });
    expect(r.ok && r.value.settings.gate.tiers["run_program"]).toBe("free");
    expect(r.ok && r.value.settings.gate.free_for_jobs_from_the_mac).toEqual(["run_program"]);
    expect(r.ok && r.value.settings.gate.never_free).toEqual(["start_project"]);
  });

  it("report a silent microphone, and try again when another is chosen", async () => {
    vi.useFakeTimers();
    const m = mock();
    await m.patchSettings({ voice: { input_device: "Insta360 Link 2C" } });
    const on = m.setVoice(true);
    await vi.advanceTimersByTimeAsync(500);
    const silent = await on;
    expect(silent.ok && [silent.value.running, silent.value.mic]).toEqual([false, "silent"]);
    expect(silent.ok && silent.value.mic_detail).toContain("“Insta360 Link 2C” sends only silence");
    const r = await m.patchSettings({ voice: { input_device: "MacBook Pro Microphone" } });
    expect(r.ok && [r.value.settings.voice.running, r.value.settings.voice.mic]).toEqual([true, "granted"]);
  });

  it("say a test sentence, or what is missing for it", async () => {
    vi.useFakeTimers();
    const m = mock();
    const said = m.speakTest({ tts_voice: "bm_george" });
    await vi.advanceTimersByTimeAsync(2000);
    const r = await said;
    expect(r.ok && r.value).toEqual({ ok: true, message: "Said: “Hello, I am Vision. This is how I sound.”" });
    expect((await m.speakTest({ tts_voice: "nobody" })).ok).toBe(false);
  });

  it("apply a name at once and keep a model change for the restart", async () => {
    const plan = samplePlan();
    const m = mock(plan);
    const r = await m.patchSettings({ assistant: { name: "Juniper" }, models: { talk: "claude-sonnet-5-5" } });
    expect(r.ok && r.value.applied).toEqual(["assistant.name"]);
    expect(r.ok && r.value.restart).toEqual(["models.talk"]);
    expect(r.ok && r.value.settings.restart_pending).toEqual(["models.talk"]);
    expect(plan.agents.find((a) => a.id === "host")?.name).toBe("Juniper");
  });

  it("refuse a text that is not a key, and accept one that is", async () => {
    vi.useFakeTimers();
    const m = mock();
    expect((await m.storeKey("hello")).ok).toBe(false);
    const stored = m.storeKey(`sk-ant-${"a".repeat(30)}`);
    await vi.advanceTimersByTimeAsync(1000);
    const r = await stored;
    expect(r.ok && r.value.verdict).toBe("accepted");
  });

  it("let a download progress to done", async () => {
    vi.useFakeTimers();
    const m = mock();
    await m.startDownload("local_model");
    await vi.advanceTimersByTimeAsync(5000);
    const mid = await m.downloads();
    expect(mid.ok && mid.value.local_model.state).toBe("running");
    await vi.advanceTimersByTimeAsync(11_000);
    const end = await m.downloads();
    expect(end.ok && end.value.local_model.state).toBe("done");
    const s = await m.settings();
    expect(s.ok && s.value.models.local.downloaded).toBe(true);
  });

  it("keep the Hall's agent and give no other room to the host", async () => {
    const m = mock();
    expect((await m.patchRoom("hall", { agent: "maker" })).ok).toBe(false);
    expect((await m.patchRoom("workshop", { agent: "host" })).ok).toBe(false);
    expect((await m.removeRoom("library")).ok).toBe(false);
  });

  it("flatten a nested patch into dotted fields", () => {
    expect(flatten({ agents: { maker: { name: "Tink" } }, budget: { cap_usd: 5 } })).toEqual([
      ["agents.maker.name", "Tink"],
      ["budget.cap_usd", 5],
    ]);
  });
});
