import { afterEach, describe, expect, it, vi } from "vitest";
import { installMockBridge } from "../../net/mock-bridge";
import { MockSettings } from "../../net/mock-settings";
import { nativeHelpers } from "../../net/native";
import { samplePlan } from "../../net/sample-plan";
import { ok, refused, type Result } from "../../net/settings-api";
import { asDeleteAllAnswer, asDeleteAllPreview, asSettings } from "../../net/settings-guards";
import { DELETE_ALL_CONFIRM, HttpSettings } from "../../net/settings-http";
import type { DeleteAllAnswer } from "../../net/settings-types";
import { APP_STAYED, CLOSING_APP, DeleteAllFlow, deleteQuestion, leftLines, STOPPED_IN_BROWSER, type DeleteView } from "./delete-all";

function mockHouse() {
  const plan = samplePlan();
  return { plan: () => plan, changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} };
}

const ANSWER: DeleteAllAnswer = {
  home: "/Users/you/Library/Application Support/Vision",
  removed: ["config.toml", "house", "log.db", "token"],
  left: [],
  folder_removed: true,
  elsewhere: [],
  keychain: { ok: true, message: "The API key and the phone's bot token are no longer in the Keychain." },
  models: null,
  launch_agent: { installed: false, removed: false, message: "" },
  message: "The data folder is gone. The assistant stops now.",
};

/** A daemon answer the test releases when it wants, so the running state can be seen. */
function held(answer: Result<DeleteAllAnswer>) {
  let release: () => void = () => {};
  const asked: boolean[] = [];
  const deleteAll = (models: boolean): Promise<Result<DeleteAllAnswer>> => {
    asked.push(models);
    return new Promise((resolve) => {
      release = () => resolve(answer);
    });
  };
  return { deleteAll, asked, release: () => release() };
}

describe("Delete all data, step by step", () => {
  it("asks first, and Keep it does nothing", async () => {
    const daemon = held(ok(ANSWER));
    const views: DeleteView[] = [];
    const flow = new DeleteAllFlow({ deleteAll: daemon.deleteAll, finish: null }, (v) => views.push(v));
    expect(flow.view()).toMatchObject({ phase: "idle", question: null, canStart: true });
    flow.ask(false);
    expect(flow.view()).toMatchObject({ phase: "asking", question: deleteQuestion(false), canConfirm: true, canKeep: true, canStart: false });
    flow.keep();
    expect(flow.view()).toMatchObject({ phase: "idle", question: null, canStart: true, message: "" });
    expect(daemon.asked).toEqual([]);
    expect(views.map((v) => v.phase)).toEqual(["asking", "idle"]);
  });

  it("names the models in the question only when they are to go", () => {
    expect(deleteQuestion(true)).toContain("downloaded models");
    expect(deleteQuestion(false)).not.toContain("models");
    expect(deleteQuestion(false)).toContain("cannot be undone");
  });

  it("disables every button while it runs, then calls the app after the daemon answered", async () => {
    const daemon = held(ok(ANSWER));
    const order: string[] = [];
    const finish = vi.fn(async (summary: string) => {
      order.push(`finish: ${summary}`);
    });
    const flow = new DeleteAllFlow({ deleteAll: (m) => (order.push("daemon"), daemon.deleteAll(m)), finish });
    flow.ask(true);
    const done = flow.confirm();
    expect(flow.view()).toMatchObject({ phase: "running", canStart: false, canConfirm: false, canKeep: false, question: deleteQuestion(true) });
    expect(finish).not.toHaveBeenCalled();
    await flow.confirm(); // a second press while it runs does nothing
    expect(daemon.asked).toEqual([true]);
    daemon.release();
    await done;
    expect(order).toEqual(["daemon", `finish: ${ANSWER.message}`]);
    expect(flow.view()).toMatchObject({ phase: "done", tone: "ok", message: `${ANSWER.message} ${CLOSING_APP}`, canStart: false });
  });

  it("shows the reason when the daemon refuses, and pretends nothing worked", async () => {
    const daemon = held(refused("Nothing was deleted. The data folder is set to /Users/you, which is your home folder or a folder above it."));
    const finish = vi.fn(async () => {});
    const flow = new DeleteAllFlow({ deleteAll: daemon.deleteAll, finish });
    flow.ask(false);
    const done = flow.confirm();
    daemon.release();
    await done;
    expect(flow.view()).toMatchObject({ phase: "failed", tone: "bad", canStart: true, question: null });
    expect(flow.view().message).toContain("did not finish");
    expect(flow.view().message).toContain("your home folder");
    expect(finish).not.toHaveBeenCalled();
    flow.ask(false); // and it can be tried again
    expect(flow.view().phase).toBe("asking");
  });

  it("says the assistant stopped in a plain browser", async () => {
    const flow = new DeleteAllFlow({ deleteAll: () => Promise.resolve(ok(ANSWER)), finish: null });
    flow.ask(false);
    await flow.confirm();
    expect(flow.view()).toMatchObject({ phase: "done", message: `${ANSWER.message} ${STOPPED_IN_BROWSER}` });
  });

  it("says so when the app did not close", async () => {
    const flow = new DeleteAllFlow({ deleteAll: () => Promise.resolve(ok(ANSWER)), finish: () => Promise.reject(new Error("no")) });
    flow.ask(false);
    await flow.confirm();
    expect(flow.view().message).toBe(`${ANSWER.message} ${APP_STAYED}`);
  });

  it("lists what stayed, and does not call it a clean finish", async () => {
    const answer: DeleteAllAnswer = {
      ...ANSWER,
      folder_removed: false,
      left: [{ name: "Sam's notes.txt", why: "The app did not make it." }],
      elsewhere: ["/Volumes/Spare/vision-logs"],
      keychain: { ok: false, message: "The Keychain did not let the API key be removed." },
      models: { removed: [], left: [{ repo: "mlx-community/Kokoro-82M-bf16", why: "It is still downloading." }], freed_bytes: 0 },
    };
    const summaries: string[] = [];
    const flow = new DeleteAllFlow({ deleteAll: () => Promise.resolve(ok(answer)), finish: async (s) => void summaries.push(s) });
    flow.ask(true);
    await flow.confirm();
    expect(leftLines(answer)).toEqual([
      "Sam's notes.txt: The app did not make it.",
      "/Volumes/Spare/vision-logs: kept outside the data folder by your settings.",
      "mlx-community/Kokoro-82M-bf16: It is still downloading.",
    ]);
    expect(flow.view()).toMatchObject({ tone: "warn", left: leftLines(answer) });
    expect(summaries[0]?.split("\n")).toEqual([answer.message, ...leftLines(answer)]);
  });
});

describe("Delete all data on the wire", () => {
  it("sends the confirmation the daemon asks for, and the models choice", async () => {
    const calls: unknown[][] = [];
    const api = { call: (...args: unknown[]) => (calls.push(args), Promise.resolve(ok(ANSWER))) };
    const http = new HttpSettings(api as never);
    const r = await http.deleteAll(true);
    expect(r.ok).toBe(true);
    expect(calls).toEqual([["POST", "/api/delete-all", { confirm: DELETE_ALL_CONFIRM, models: true }]]);
    expect(DELETE_ALL_CONFIRM).toBe("delete all data");
  });

  it("accepts the daemon's shapes and refuses others", () => {
    expect(asDeleteAllAnswer(ANSWER)).not.toBeNull();
    expect(asDeleteAllAnswer({ ...ANSWER, models: { removed: ["a/b"], left: [], freed_bytes: 10 } })).not.toBeNull();
    expect(asDeleteAllAnswer({ ...ANSWER, left: ["notes.txt"] })).toBeNull();
    expect(asDeleteAllAnswer({ ...ANSWER, keychain: { ok: "yes", message: "" } })).toBeNull();
    expect(asDeleteAllAnswer({ ...ANSWER, models: { removed: [], left: [], freed_bytes: "1 GB" } })).toBeNull();
    expect(asDeleteAllPreview({ home: "/h", models: [{ repo: "a/b", bytes: 3 }], models_bytes: 3 })).not.toBeNull();
    expect(asDeleteAllPreview({ home: "/h", models: [{ repo: "a/b" }], models_bytes: 3 })).toBeNull();
  });

  it("needs the data folder in the settings answer", async () => {
    const r = await new MockSettings(mockHouse()).settings();
    if (!r.ok) throw new Error(r.message);
    expect(asSettings(r.value)).not.toBeNull();
    expect(r.value.data.home).toBe("/Users/you/Library/Application Support/Vision");
    const { data: _gone, ...without } = r.value;
    expect(asSettings(without)).toBeNull();
  });
});

describe("Delete all data in mock mode", () => {
  it("previews and deletes the models only when asked", async () => {
    vi.useFakeTimers();
    const mock = new MockSettings(mockHouse());
    const preview = await mock.deleteAllPreview();
    expect(preview.ok && preview.value.home).toBe("/Users/you/Library/Application Support/Vision");
    const kept = mock.deleteAll(false);
    await vi.runAllTimersAsync();
    const answer = await kept;
    vi.useRealTimers();
    expect(answer.ok && answer.value.models).toBeNull();
    expect(answer.ok && asDeleteAllAnswer(answer.value)).not.toBeNull();
  });
});

describe("the app's last step through the bridge", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("is missing in a plain browser", () => {
    vi.stubGlobal("window", {});
    expect(nativeHelpers().finishDeleteAll).toBeNull();
  });

  it("is pretended by the mock bridge, so the control can be looked at in a browser", async () => {
    vi.stubGlobal("window", {});
    installMockBridge();
    const finish = nativeHelpers().finishDeleteAll;
    expect(finish).not.toBeNull();
    await expect(finish?.("done")).resolves.toBeUndefined();
  });

  it("is passed the summary in the app", async () => {
    const seen: unknown[] = [];
    vi.stubGlobal("window", { pywebview: { api: { finishDeleteAll: (summary: unknown) => (seen.push(summary), Promise.resolve(true)) } } });
    const finish = nativeHelpers().finishDeleteAll;
    expect(finish).not.toBeNull();
    await finish?.("The data folder is gone.");
    expect(seen).toEqual(["The data folder is gone."]);
  });
});
