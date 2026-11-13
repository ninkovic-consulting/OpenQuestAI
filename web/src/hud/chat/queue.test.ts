import { afterEach, describe, expect, it, vi } from "vitest";
import { MockDaemon } from "../../net/mock";
import type { WaitingMessage } from "../../net/queue-types";
import { type Caption, initialState, reduce, Store, type ViewState } from "../../net/store";
import { asOutbound, envelope, type OutboundEvent, type StateSnapshot } from "../../net/types";
import { widgetView } from "../widget/model";
import { emptyThread, fromCaption, nowWaiting, sent } from "./entries";
import { type KeyContext, type KeyPress, routeKey } from "./keys";
import { answering, queueFull, queues, sendHints, waitingLine, waitingRows } from "./queue";

const waiting = (id: string, preview: string, more: Partial<WaitingMessage> = {}): WaitingMessage => ({
  id,
  preview,
  images: 0,
  source: "text",
  at: 1,
  ...more,
});
const event = (e: Omit<OutboundEvent, "ts">): OutboundEvent => ({ ...e, ts: 1 }) as OutboundEvent;
const caption = (more: Partial<Caption>): Caption => ({ user: "", source: null, reply: "", streaming: false, ...more });

describe("what Enter does", () => {
  it("queues while the assistant thinks or speaks, or while the window's messages wait", () => {
    const s = initialState();
    expect(queues(s)).toBe(false);
    expect(queues({ ...s, assistant: "thinking" })).toBe(true);
    expect(queues({ ...s, assistant: "speaking" })).toBe(true);
    expect(queues({ ...s, queue: [waiting("a", "held")] })).toBe(true);
    expect(queues({ ...s, queue: [waiting("p", "phone", { source: "phone" })] })).toBe(false);
    expect(answering("listening")).toBe(false);
  });

  it("the hints say it, word for word", () => {
    expect(sendHints(true)).toEqual([["Enter", "queues"], ["⌘ Enter", "sends now"]]);
    expect(sendHints(false)).toEqual([["Enter", "sends"]]);
  });

  it("a sixth typed message is refused; the phone's do not count", () => {
    const five = ["a", "b", "c", "d", "e"].map((id) => waiting(id, id));
    expect(queueFull(five)).toBe(true);
    expect(queueFull([...five.slice(1), waiting("p", "p", { source: "phone" })])).toBe(false);
  });
});

describe("keys for sending now and stopping", () => {
  const press = (key: string, more: Partial<KeyPress> = {}): KeyPress => ({ key, code: key, shift: false, ctrl: false, meta: false, alt: false, composing: false, ...more });
  const field: KeyContext = { focus: "field", overlay: false, fieldEmpty: false, answering: true };

  it("Cmd+Enter or Ctrl+Enter sends now; Enter sends (or queues); Shift+Enter is a new line", () => {
    expect(routeKey(press("Enter", { meta: true }), field)).toEqual({ kind: "send-now" });
    expect(routeKey(press("Enter", { ctrl: true }), field)).toEqual({ kind: "send-now" });
    expect(routeKey(press("Enter"), field)).toEqual({ kind: "send" });
    expect(routeKey(press("Enter", { shift: true }), field)).toEqual({ kind: "none" });
  });

  it("Escape stops a thinking assistant too, not only a speaking one", () => {
    expect(routeKey(press("Escape"), field)).toEqual({ kind: "interrupt" });
    expect(routeKey(press("Escape"), { ...field, answering: false })).toEqual({ kind: "blur" });
  });
});

describe("the waiting list", () => {
  it("each row says it sends after this reply; only typed ones can be sent now or taken back", () => {
    const rows = waitingRows([waiting("a", "Make them rhyme.", { images: 2 }), waiting("p", "From the bus.", { source: "phone" })]);
    expect(rows).toEqual([
      { id: "a", who: "You · typed", text: "Make them rhyme.", mark: "2 images", note: "Sends after this reply", controls: true },
      { id: "p", who: "You, from the phone", text: "From the bus.", mark: "", note: "Goes after this reply, as its own turn", controls: false },
    ]);
  });

  it("the widget shows the count and the newest", () => {
    expect(waitingLine([])).toBeNull();
    expect(waitingLine([waiting("a", "first"), waiting("b", "And short.")])).toBe("2 waiting · And short.");
    const s: ViewState = { ...initialState(), queue: [waiting("a", "first")] };
    expect(widgetView(s, false, null, null).waiting).toBe("1 waiting · first");
  });
});

describe("the thread and the waiting messages", () => {
  it("a message sent here that the daemon holds leaves the thread for the waiting list", () => {
    let t = sent(emptyThread(), "hi", false, [], "m1");
    t = sent(t, "other", false, [], "m2");
    expect(nowWaiting(t, ["m1"]).entries.map((e) => e.user)).toEqual(["other"]);
    expect(nowWaiting(t, [])).toBe(t);
  });

  it("the turn that answers several waiting messages is one entry with all their words", () => {
    let t = sent(emptyThread(), "Make them rhyme.", true, [], "m1");
    t = sent(t, "And short.", true, [], "m2");
    const next = caption({ user: "Make them rhyme.\n\nAnd short.", source: "text", ids: ["m1", "m2"] });
    t = fromCaption(t, caption({}), next);
    expect(t.entries.map((e) => [e.user, e.phase])).toEqual([["Make them rhyme.\n\nAnd short.", "waiting"]]);
    expect(t.entries[0]?.msgId).toBeUndefined();
  });

  it("a reply cut off with words in it is marked interrupted", () => {
    let t = fromCaption(emptyThread(), caption({}), caption({ user: "go", source: "text" }));
    const streaming = caption({ user: "go", source: "text", reply: "First part", streaming: true });
    t = fromCaption(t, caption({ user: "go", source: "text" }), streaming);
    t = fromCaption(t, streaming, { ...streaming, streaming: false, ended: "interrupted" });
    expect(t.entries[0]).toMatchObject({ reply: "First part", phase: "done", ended: "interrupted" });
  });
});

describe("the store", () => {
  it("keeps the queue from its event and from a snapshot, and the reply's status and the turn's ids", () => {
    let s = reduce(initialState(), { kind: "event", event: event({ type: "queue.changed", data: { items: [waiting("a", "x")] } }) });
    expect(s.queue.map((m) => m.id)).toEqual(["a"]);
    s = reduce(s, { kind: "event", event: event({ type: "user.utterance", data: { text: "x", source: "text", images: [], ids: ["a"] } }) });
    expect(s.caption.ids).toEqual(["a"]);
    s = reduce(s, { kind: "event", event: event({ type: "vision.reply", data: { text: "Half", turn_id: "t", status: "interrupted" } }) });
    expect(s.caption.ended).toBe("interrupted");
    const snap: StateSnapshot = { state: "idle", brain: "fake", gate_pending: [], notices: [], budget: { month: "2026-11", spent_usd: 0, cap_usd: 1 } };
    expect(reduce(s, { kind: "snapshot", snapshot: { ...snap, queue: [waiting("b", "y")] }, initial: false }).queue.map((m) => m.id)).toEqual(["b"]);
    expect(reduce(s, { kind: "snapshot", snapshot: snap, initial: false }).queue).toEqual([]);
  });

  it("refuses a queue event of the wrong shape", () => {
    expect(asOutbound({ type: "queue.changed", data: { items: [{ id: "a" }] } })).toBeNull();
    expect(asOutbound({ type: "queue.changed", data: { items: [waiting("a", "x")] } })).not.toBeNull();
  });
});

describe("mock mode", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("two messages queue during a long reply; one is taken back, one sent now, and Escape still stops", () => {
    vi.useFakeTimers();
    vi.stubGlobal("window", globalThis);
    const store = new Store();
    const daemon = new MockDaemon(store);
    const said: string[] = [];
    store.subscribe((s, prev) => {
      if (s.caption.user !== prev.caption.user || s.caption.ids !== prev.caption.ids) said.push(s.caption.user);
    });
    daemon.send(envelope("input.text", { text: "Explain it in detail.", id: "q0" }));
    vi.advanceTimersByTime(1500);
    expect(store.get().assistant).toBe("speaking");
    daemon.send(envelope("input.text", { text: "Keep it short.", id: "q1" }));
    daemon.send(envelope("input.text", { text: "Forget that.", id: "q2" }));
    expect(store.get().queue.map((m) => m.preview)).toEqual(["Keep it short.", "Forget that."]);
    daemon.send(envelope("input.take_back", { id: "q2" }));
    expect(store.get().queue.map((m) => m.id)).toEqual(["q1"]);
    daemon.send(envelope("input.send_now", { id: "q1" }));
    expect(store.get().caption).toMatchObject({ user: "Keep it short.", ids: ["q1"] });
    expect(store.get().queue).toEqual([]);
    vi.advanceTimersByTime(1500);
    expect(store.get().assistant).toBe("speaking");
    daemon.send(envelope("input.interrupt", {}));
    expect(store.get().assistant).toBe("idle");
    expect(store.get().caption.ended).toBe("interrupted");
    expect(said).toEqual(["Explain it in detail.", "Keep it short."]);
  });
});
