import { describe, expect, it } from "vitest";
import { asWidgetPrefs, shortcutLine } from "../../net/shell-prefs";
import { initialState, reduce, type Action, type ViewState } from "../../net/store";
import type { GateRequest, OutboundData, OutboundEvent, OutboundType } from "../../net/types";
import type { HistoryTurn } from "../chat/entries";
import { latestExchange, replyRestarted, whoLabel, widgetState, widgetView } from "./model";

const ev = <K extends OutboundType>(type: K, data: OutboundData[K]): Action => ({
  kind: "event",
  event: { type, ts: 0, data } as OutboundEvent,
});

const open = (): ViewState => reduce(initialState(), { kind: "connection", connection: "open" });
const run = (s: ViewState, ...actions: Action[]): ViewState => actions.reduce(reduce, s);
const state = (s: ViewState, st: OutboundData["state.changed"]["state"]): ViewState => run(s, ev("state.changed", { state: st, brain: "claude" }));

const gate = (id: string, summary = "Vision wants to run the tests."): GateRequest => ({
  id,
  tool: "shell",
  summary,
  detail: "npm test",
  expires_at: 1000,
});

describe("the widget's state", () => {
  it("shows each of the assistant's states", () => {
    const s = open();
    expect(widgetState(s, false)).toBe("idle");
    expect(widgetState(state(s, "listening"), false)).toBe("listening");
    expect(widgetState(state(s, "transcribing"), false)).toBe("listening");
    expect(widgetState(state(s, "thinking"), false)).toBe("thinking");
    expect(widgetState(state(s, "speaking"), false)).toBe("speaking");
  });

  it("is offline or connecting while there is no connection, whatever else holds", () => {
    expect(widgetState(initialState(), false)).toBe("connecting");
    const off = run(state(open(), "speaking"), { kind: "connection", connection: "offline" });
    expect(widgetState(off, true)).toBe("offline");
  });

  it("listens at once while push to talk is held here", () => {
    expect(widgetState(open(), true)).toBe("listening");
    expect(widgetState(state(open(), "speaking"), true)).toBe("listening");
  });
});

describe("the latest exchange", () => {
  const caption = initialState().caption;

  it("is empty until something was said", () => {
    expect(latestExchange(caption, "idle", null, null)).toBeNull();
  });

  it("shows a message sent from the widget at once", () => {
    expect(latestExchange(caption, "idle", "Is the build green?", null)).toEqual({
      who: "You · typed",
      user: "Is the build green?",
      reply: "",
      status: "Sent",
      streaming: false,
    });
  });

  it("follows the turn: waiting, streaming, done", () => {
    let s = run(open(), ev("user.utterance", { text: "What changed?", source: "voice" }));
    s = state(s, "thinking");
    expect(latestExchange(s.caption, s.assistant, null, null)).toMatchObject({ who: "You · spoken", reply: "", status: "Waiting for the reply" });
    s = run(s, ev("vision.delta", { text: "Three " }), ev("vision.delta", { text: "things." }));
    expect(latestExchange(s.caption, s.assistant, null, null)).toMatchObject({ reply: "Three things.", status: "", streaming: true });
    s = state(run(s, ev("vision.reply", { text: "Three things.", turn_id: "t" })), "idle");
    expect(latestExchange(s.caption, s.assistant, null, null)).toMatchObject({ reply: "Three things.", streaming: false });
  });

  it("says when a turn closed without a reply", () => {
    const s = state(run(open(), ev("user.utterance", { text: "Hello", source: "text" })), "idle");
    expect(latestExchange(s.caption, s.assistant, null, null)?.status).toBe("No reply");
  });

  it("falls back to the last turn from before the widget opened", () => {
    const earlier: HistoryTurn = { startedAt: 1, origin: "phone", user: "Awake?", reply: "Yes.", status: "ok" };
    expect(latestExchange(caption, "idle", null, earlier)).toMatchObject({ who: "You, from the phone", user: "Awake?", reply: "Yes." });
  });

  it("names where the words came from", () => {
    expect(whoLabel("automation")).toBe("Automation");
    expect(whoLabel("job", "Tink")).toBe("Job report · Tink");
    expect(whoLabel(null)).toBe("You");
  });

  it("scrolls back to the first word only when a new reply begins", () => {
    const a = { who: "You · typed", user: "Hi", reply: "Hello", status: "", streaming: true };
    expect(replyRestarted(null, a)).toBe(true);
    expect(replyRestarted(a, { ...a, reply: "Hello there" })).toBe(false);
    expect(replyRestarted(a, { ...a, user: "Again" })).toBe(true);
    expect(replyRestarted(a, { ...a, reply: "Other" })).toBe(true);
    expect(replyRestarted(a, null)).toBe(false);
  });
});

describe("requests waiting for a yes", () => {
  it("shows the oldest with how many more wait, and moves on as they are answered", () => {
    let s = run(open(), ev("gate.request", gate("a", "Vision wants to run the tests.")), ev("gate.request", gate("b")), ev("gate.request", gate("c")));
    let v = widgetView(s, false, null, null);
    expect(v.gate?.gate.id).toBe("a");
    expect(v.gate?.summary).toBe("Vision wants to run the tests.");
    expect(v.gate?.more).toBe(2);
    s = run(s, ev("gate.resolved", { id: "a", decision: "allow" }));
    v = widgetView(s, false, null, null);
    expect(v.gate?.gate.id).toBe("b");
    expect(v.gate?.more).toBe(1);
    s = run(s, ev("gate.resolved", { id: "b", decision: "deny" }), ev("gate.resolved", { id: "c", decision: "timeout" }));
    expect(widgetView(s, false, null, null).gate).toBeNull();
  });

  it("names the resident who asks during a job", () => {
    const s = run(open(), ev("gate.request", { ...gate("r", "Tink: write the report file."), agent: "maker", agent_name: "Tink" }));
    expect(widgetView(s, false, null, null).gate).toMatchObject({ who: "Tink", summary: "Write the report file." });
  });
});

describe("the widget's name and field", () => {
  it("takes the assistant's name from the plan", () => {
    expect(widgetView(open(), false, null, null).name).toBe("");
  });
});

describe("the shell's preferences", () => {
  const answer = {
    widget: true,
    openWith: "widget",
    summon: "option-space",
    talk: "off",
    shown: true,
    shortcuts: [{ id: "option-space", label: "⌥ Space" }, { id: 3 }],
    status: { summon: { registered: false, problem: "macOS refused ⌥ Space." }, talk: { registered: false, problem: null } },
  };

  it("narrows the bridge's answer", () => {
    expect(asWidgetPrefs(answer)).toEqual({
      ...answer,
      shortcuts: [{ id: "option-space", label: "⌥ Space" }],
    });
    expect(asWidgetPrefs({ ...answer, openWith: "menubar" })?.openWith).toBe("menubar");
    expect(asWidgetPrefs({ ...answer, openWith: "dock" })).toBeNull();
    expect(asWidgetPrefs(null)).toBeNull();
  });

  it("says plainly whether each shortcut works", () => {
    expect(shortcutLine("off", { registered: false, problem: null })).toEqual({ tone: "idle", text: "Off." });
    expect(shortcutLine("option-space", { registered: true, problem: null }).tone).toBe("ok");
    expect(shortcutLine("option-space", { registered: true, problem: "macOS uses it too." })).toEqual({ tone: "warn", text: "macOS uses it too." });
    expect(shortcutLine("option-space", { registered: false, problem: "Another app already uses ⌥ Space." }).tone).toBe("bad");
  });
});
