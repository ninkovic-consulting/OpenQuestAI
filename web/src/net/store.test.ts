import { describe, expect, it } from "vitest";
import { samplePlan } from "./sample-plan";
import { initialState, reduce, Store, type ViewState } from "./store";
import type { OutboundData, OutboundEvent, OutboundType, StateSnapshot } from "./types";

function ev<K extends OutboundType>(type: K, data: OutboundData[K]): { kind: "event"; event: OutboundEvent } {
  return { kind: "event", event: { type, ts: 1, data } as OutboundEvent };
}

const run = (...actions: Parameters<typeof reduce>[1][]): ViewState => actions.reduce(reduce, initialState());

describe("store reducers", () => {
  it("state.changed sets the state and brain, and drops the voice level when not speaking", () => {
    const speaking = run(ev("state.changed", { state: "speaking", brain: "claude" }), ev("voice.level", { level: 0.7 }));
    expect(speaking.assistant).toBe("speaking");
    expect(speaking.brain).toBe("claude");
    expect(speaking.voiceLevel).toBe(0.7);
    const idle = reduce(speaking, ev("state.changed", { state: "idle", brain: null }));
    expect(idle.voiceLevel).toBe(0);
    expect(idle.brain).toBe("claude");
  });

  it("budget stores spend and cap", () => {
    const s = run(ev("budget", { month: "2026-11", spent_usd: 12.5, cap_usd: 150 }));
    expect(s.budget).toEqual({ month: "2026-11", spent_usd: 12.5, cap_usd: 150 });
  });

  it("house.changed raises the announced revision but never lowers it", () => {
    const s = run(ev("house.changed", { revision: 4 }), ev("house.changed", { revision: 2 }));
    expect(s.houseRevision).toBe(4);
  });

  it("user.utterance starts a fresh caption", () => {
    const s = run(ev("vision.reply", { text: "old", turn_id: "t0" }), ev("user.utterance", { text: "hello", source: "voice" }));
    expect(s.caption).toEqual({ user: "hello", source: "voice", reply: "", streaming: false });
  });

  it("vision.delta streams into the reply and vision.reply settles it", () => {
    let s = run(ev("user.utterance", { text: "hi", source: "text" }), ev("vision.delta", { text: "Hel" }), ev("vision.delta", { text: "lo" }));
    expect(s.caption.reply).toBe("Hello");
    expect(s.caption.streaming).toBe(true);
    s = reduce(s, ev("vision.reply", { text: "Hello.", turn_id: "t1" }));
    expect(s.caption).toMatchObject({ reply: "Hello.", streaming: false, user: "hi" });
    s = reduce(s, ev("vision.delta", { text: "New" }));
    expect(s.caption.reply).toBe("New");
  });

  it("voice.level is clamped to 0..1", () => {
    expect(run(ev("voice.level", { level: 3 })).voiceLevel).toBe(1);
    expect(run(ev("voice.level", { level: -1 })).voiceLevel).toBe(0);
  });

  it("room.state overrides the plan's light and survives a plan reload", () => {
    const plan = samplePlan();
    let s = run({ kind: "plan", plan }, ev("room.state", { room: "library", state: "active" }));
    expect(s.roomLights["library"]).toBe("active");
    expect(s.roomLights["hall"]).toBe("active");
    s = reduce(s, { kind: "plan", plan: { ...plan, revision: 2 } });
    expect(s.roomLights["library"]).toBe("active");
  });

  it("gate.request queues requests once each, gate.resolved removes them", () => {
    const req = { id: "g1", tool: "shell", summary: "Run it", detail: "ls", expires_at: 100 };
    let s = run(ev("gate.request", req), ev("gate.request", req), ev("gate.request", { ...req, id: "g2" }));
    expect(s.gates.map((g) => g.id)).toEqual(["g1", "g2"]);
    s = reduce(s, ev("gate.resolved", { id: "g1", decision: "timeout" }));
    expect(s.gates.map((g) => g.id)).toEqual(["g2"]);
  });

  it("brain.fallback switches the brain and raises a warning toast", () => {
    const s = run(ev("brain.fallback", { from: "claude", to: "local", reason: "offline" }));
    expect(s.brain).toBe("local");
    expect(s.toasts).toEqual([{ id: 1, level: "warn", text: "Switched from claude to local: offline" }]);
  });

  it("notice becomes a toast; toasts are capped and dismissable", () => {
    let s = initialState();
    for (let i = 0; i < 6; i++) s = reduce(s, ev("notice", { level: "info", text: `n${i}` }));
    expect(s.toasts.map((t) => t.text)).toEqual(["n2", "n3", "n4", "n5"]);
    s = reduce(s, { kind: "dismiss", id: 3 });
    expect(s.toasts.map((t) => t.text)).toEqual(["n3", "n4", "n5"]);
  });

  it("a snapshot restores state, brain, budget and pending gates; only the first one shows notices", () => {
    const snapshot: StateSnapshot = {
      state: "thinking",
      brain: "local",
      budget: { month: "2026-11", spent_usd: 1, cap_usd: 2 },
      gate_pending: [{ type: "gate.request", ts: 1, data: { id: "g9", tool: "shell", summary: "", detail: "", expires_at: 5 } }],
      notices: [{ type: "notice", ts: 1, data: { level: "warn", text: "Voice is off." } }],
    };
    const first = run({ kind: "snapshot", snapshot, initial: true });
    expect(first).toMatchObject({ assistant: "thinking", brain: "local", budget: snapshot.budget });
    expect(first.gates.map((g) => g.id)).toEqual(["g9"]);
    expect(first.toasts.map((t) => t.text)).toEqual(["Voice is off."]);
    expect(run({ kind: "snapshot", snapshot, initial: false }).toasts).toEqual([]);
  });

  it("connection status is stored", () => {
    expect(run({ kind: "connection", connection: "open" }).connection).toBe("open");
  });

  it("the store notifies listeners with the new and previous state", () => {
    const store = new Store();
    const seen: string[] = [];
    store.subscribe((s, prev) => seen.push(`${prev.assistant}->${s.assistant}`));
    store.dispatch(ev("state.changed", { state: "listening", brain: null }));
    expect(seen).toEqual(["idle->listening"]);
  });
});
