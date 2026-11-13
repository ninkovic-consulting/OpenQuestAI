import { describe, expect, it } from "vitest";
import type { LocalListing } from "../../net/brain-types";
import { MockLocal } from "../../net/mock-local";
import { MockSettings } from "../../net/mock-settings";
import { samplePlan } from "../../net/sample-plan";
import type { ModelListing } from "../../net/settings-types";
import { jobModelName, localShort, offlineMark, offlineTitle } from "../mode";
import { buildPatch, draftFrom, fieldLabel } from "./draft";
import { droppedWords, fallbackLevel, levelsFor } from "./effort";
import { anyRunning, chosenSize, chosenTitle, deleteBlock, deleteQuestion, downloadOf, fitTone, fitWords, inUse, memoryLine, offersDownload, orderBySize, toolsWords } from "./local-words";

const QWEN4 = "mlx-community/Qwen3-4B-Instruct-2507-4bit";
const QWEN8 = "mlx-community/Qwen3-8B-4bit";

const listing = (over: Partial<Pick<LocalListing, "chosen" | "offline">> = {}): LocalListing => ({
  ...new MockLocal().listing({ backend: "mlx", model: QWEN4, server: "http://127.0.0.1:1234/v1", offline: false }),
  ...over,
});

describe("which thinking levels are offered", () => {
  const claude: ModelListing = {
    source: "api",
    fetched_at: null,
    models: [
      { id: "claude-opus-4-6", display_name: "Opus 4.6", max_input_tokens: null, max_tokens: null, retires_at: null, price: null, efforts: ["low", "medium", "high", "max"] },
      { id: "claude-haiku-4-5", display_name: "Haiku 4.5", max_input_tokens: null, max_tokens: null, retires_at: null, price: null, efforts: [] },
    ],
  };

  it("come from the model list, else the house's table, else all five", () => {
    const plan = { ...samplePlan(), effort_levels: { "claude-sonnet-4-6": ["low", "high"] } };
    expect(levelsFor("claude-opus-4-6", claude, plan)).toEqual(["low", "medium", "high", "max"]);
    expect(levelsFor("claude-haiku-4-5", claude, plan)).toEqual([]);
    expect(levelsFor("claude-sonnet-4-6", null, plan)).toEqual(["low", "high"]);
    expect(levelsFor("claude-unknown", claude, plan)).toEqual(["low", "medium", "high", "xhigh", "max"]);
    expect(levelsFor("claude-unknown", null, null)).toHaveLength(5);
  });

  it("keep a level the new model takes, else drop to the nearest lower one, else the lowest", () => {
    const noXhigh = ["low", "medium", "high", "max"];
    expect(fallbackLevel(noXhigh, "medium")).toBe("medium");
    expect(fallbackLevel(noXhigh, "xhigh")).toBe("high");
    expect(fallbackLevel(["high", "max"], "low")).toBe("high");
    expect(fallbackLevel([], "high")).toBeNull();
  });

  it("say what moved, and nothing when nothing did", () => {
    expect(droppedWords("claude-opus-4-6", "xhigh", "high")).toBe("Opus 4.6 does not take xhigh, so the level is now high.");
    expect(droppedWords("claude-opus-4-6", "high", "high")).toBeNull();
    expect(droppedWords("claude-haiku-4-5", "high", null)).toBeNull();
  });
});

describe("the levels in the settings draft", () => {
  it("hold the host's and each resident's, and send only what changed, nested", async () => {
    const r = await new MockSettings({ plan: () => samplePlan(), changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} }).settings();
    if (!r.ok) throw new Error("no settings");
    const saved = draftFrom(r.value);
    expect(saved["models.talk_effort"]).toBe("low");
    expect(saved["agents.maker.heavy_effort"]).toBe("high");
    expect(saved).not.toHaveProperty("agents.host.effort");
    const draft = { ...saved, "models.heavy_effort": "max", "agents.maker.effort": "high" };
    expect(buildPatch(saved, draft, ["models.", "agents."]).patch).toEqual({ models: { heavy_effort: "max" }, agents: { maker: { effort: "high" } } });
    expect(fieldLabel("agents.maker.heavy_effort", r.value)).toBe("Tink's thinking level for careful work");
    expect(fieldLabel("models.talk_effort", r.value)).toBe("talk thinking level");
  });
});

describe("the catalog in words", () => {
  it("orders the models from small to large whatever the file's order", () => {
    const sizes = orderBySize([...listing().models].reverse()).map((m) => m.size_bytes);
    expect(sizes).toEqual([...sizes].sort((a, b) => a - b));
  });

  it("says what a fit means and what a model does with tools", () => {
    expect([fitTone("comfortable"), fitTone("tight"), fitTone("too_big")]).toEqual(["ok", "warn", "bad"]);
    expect(fitWords("too_big")).toBe("Too big for this Mac");
    expect(toolsWords({ tools: false, tools_recommended: false })).toBe("Talks only, no tools");
    expect(toolsWords({ tools: true, tools_recommended: false })).toBe("Can use tools, not always reliably");
    expect(toolsWords({ tools: true, tools_recommended: true })).toBe("Uses tools well");
    expect(memoryLine(24 * 1024 ** 3)).toBe("This Mac has 24 GB of memory.");
  });

  it("knows the model in use, its download and its title", () => {
    const l = listing();
    expect(inUse(l, QWEN4)).toBe(true);
    expect(inUse(l, QWEN8)).toBe(false);
    expect(inUse({ ...l, chosen: { ...l.chosen, backend: "openai", model: QWEN4 } }, QWEN4)).toBe(false);
    expect(downloadOf(l, QWEN8)?.state).toBe("done");
    expect(downloadOf(l, "unknown/repo")).toBeUndefined();
    expect(chosenTitle(l)).toBe("Qwen3 4B Instruct");
    expect(chosenSize(l)).toBe(2_278_969_697);
  });

  it("finds a download that runs, also a custom model's", () => {
    const l = listing();
    expect(anyRunning(l)).toBe(false);
    const running = { state: "running", done_bytes: 1, total_bytes: 9, message: null } as const;
    expect(anyRunning({ ...l, custom: { id: "x/y", on_disk_bytes: null, download: running } })).toBe(true);
    expect(anyRunning({ ...l, models: l.models.map((m, i) => (i === 0 ? { ...m, download: running } : m)) })).toBe(true);
  });

  it("offers the download only when the model runs inside the app and is not here", () => {
    const l = listing();
    expect(offersDownload(l)).toBe(true);
    expect(offersDownload(listing({ chosen: { ...l.chosen, model: QWEN8 } }))).toBe(false);
    expect(offersDownload(listing({ chosen: { ...l.chosen, backend: "openai" } }))).toBe(false);
    expect(offersDownload(null)).toBe(false);
  });

  it("does not let the model offline mode uses be deleted, nor one that is downloading", () => {
    const l = listing({ chosen: { backend: "mlx", model: QWEN8, server: "", tools: true }, offline: true });
    expect(deleteBlock(l, QWEN8)).toContain("Offline mode is using it");
    expect(deleteBlock({ ...l, offline: false }, QWEN8)).toBeNull();
    expect(deleteBlock(l, QWEN4)).toBeNull();
    expect(deleteQuestion("Qwen3 8B", 4_623_782_544)).toBe("Delete Qwen3 8B from this Mac? This frees 4.6 GB. It can be downloaded again.");
  });
});

describe("offline mode in words", () => {
  const mode = { offline: true, answering: "local", local_backend: "mlx", local_model: QWEN4, local_tools: false } as const;

  it("marks the state with the model's short name, only while it is on", () => {
    expect(localShort(QWEN4)).toBe("Qwen3-4B-Instruct-2507");
    expect(localShort("mlx-community/Qwen3.5-9B-MLX-4bit")).toBe("Qwen3.5-9B");
    expect(localShort("mlx-community/gpt-oss-20b-MXFP4-Q8")).toBe("gpt-oss-20b");
    expect(localShort("qwen3-8b")).toBe("qwen3-8b");
    expect(offlineMark(mode)).toBe("offline · Qwen3-4B-Instruct-2507");
    expect(offlineMark({ ...mode, offline: false })).toBeNull();
    expect(offlineMark(null)).toBeNull();
    expect(offlineTitle(mode)).toContain("cannot use tools");
  });

  it("names the model a job ran on, and keeps quiet before it started", () => {
    expect(jobModelName({ model: "claude-opus-5-5", local: false })).toBe("Opus 5.5");
    expect(jobModelName({ model: QWEN4, local: true })).toBe("Qwen3-4B-Instruct-2507");
    expect(jobModelName({ model: "", local: false })).toBeNull();
    expect(jobModelName({})).toBeNull();
  });
});
