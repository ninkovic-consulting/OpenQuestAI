import { describe, expect, it } from "vitest";
import type { Caption } from "../../net/store";
import { entryLabel, entryStatus, whoSaid } from "../caption";
import { emptyThread, fromCaption, gateResolved, replyStarted, sent, type Thread, withHistory } from "./entries";
import { asTurns } from "./history";
import { type KeyContext, type KeyPress, routeKey } from "./keys";
import { SentLog } from "./recall";
import { Talk } from "./talk";

const press = (key: string, more: Partial<KeyPress> = {}): KeyPress => ({
  key,
  code: key === " " ? "Space" : `Key${key.toUpperCase()}`,
  shift: false,
  ctrl: false,
  meta: false,
  alt: false,
  composing: false,
  ...more,
});
const scene: KeyContext = { focus: "other", overlay: false, fieldEmpty: true, answering: false };
const field: KeyContext = { ...scene, focus: "field" };

describe("keys outside the field", () => {
  it("a printable key goes into the field, with its case", () => {
    expect(routeKey(press("h"), scene)).toEqual({ kind: "type", text: "h" });
    expect(routeKey(press("H", { shift: true }), scene)).toEqual({ kind: "type", text: "H" });
    expect(routeKey(press("?", { shift: true }), scene)).toEqual({ kind: "type", text: "?" });
  });

  it("shortcuts, named keys and composing input are not typed", () => {
    expect(routeKey(press("c", { meta: true }), scene).kind).toBe("none");
    expect(routeKey(press(",", { ctrl: true }), scene).kind).toBe("none");
    expect(routeKey(press("Tab", { code: "Tab" }), scene).kind).toBe("none");
    expect(routeKey(press("ArrowUp", { code: "ArrowUp" }), scene).kind).toBe("none");
    expect(routeKey(press("a", { composing: true }), scene).kind).toBe("none");
  });

  it("`/` focuses the field without typing itself", () => {
    expect(routeKey(press("/", { code: "Slash" }), scene)).toEqual({ kind: "focus" });
  });

  it("another input, a form or a dialog keeps its keys, and so does an open overlay", () => {
    const editable = { ...scene, focus: "editable" as const };
    for (const k of [press("h"), press(" "), press("/", { code: "Slash" }), press("Escape", { code: "Escape" })])
      expect(routeKey(k, editable).kind).toBe("none");
    const overlay = { ...scene, overlay: true };
    expect(routeKey(press("h"), overlay).kind).toBe("none");
    expect(routeKey(press(" "), overlay).kind).toBe("none");
    expect(routeKey(press("/", { code: "Slash" }), overlay).kind).toBe("none");
  });

  it("Escape interrupts a speaking assistant, else steps back, overlay or not", () => {
    const esc = press("Escape", { code: "Escape" });
    expect(routeKey(esc, { ...scene, answering: true }).kind).toBe("interrupt");
    expect(routeKey(esc, scene).kind).toBe("step-back");
    expect(routeKey(esc, { ...scene, overlay: true }).kind).toBe("step-back");
  });
});

describe("the Space rule", () => {
  it("is push to talk only when the field is empty and not focused", () => {
    expect(routeKey(press(" "), scene)).toEqual({ kind: "talk" });
  });

  it("types a space into a waiting draft instead of talking", () => {
    expect(routeKey(press(" "), { ...scene, fieldEmpty: false })).toEqual({ kind: "type", text: " " });
  });

  it("is an ordinary space in the focused field, empty or not", () => {
    expect(routeKey(press(" "), field).kind).toBe("none");
    expect(routeKey(press(" "), { ...field, fieldEmpty: false }).kind).toBe("none");
  });

  it("one hold at a time: the other hand cannot end it, and losing the window lets go", () => {
    const sentDowns: boolean[] = [];
    const talk = new Talk((down) => sentDowns.push(down));
    talk.down("key");
    talk.down("pointer");
    talk.up("pointer");
    expect(talk.held).toBe(true);
    talk.up("key");
    talk.down("pointer");
    talk.cancel();
    expect(sentDowns).toEqual([true, false, true, false]);
    expect(talk.held).toBe(false);
  });
});

describe("keys in the field", () => {
  it("Enter sends, Shift+Enter is a new line", () => {
    expect(routeKey(press("Enter", { code: "Enter" }), { ...field, fieldEmpty: false })).toEqual({ kind: "send" });
    expect(routeKey(press("Enter", { code: "Enter", shift: true }), field).kind).toBe("none");
    expect(routeKey(press("Enter", { code: "Enter", composing: true }), field).kind).toBe("none");
  });

  it("Up recalls the last message only in an empty field", () => {
    const up = press("ArrowUp", { code: "ArrowUp" });
    expect(routeKey(up, field)).toEqual({ kind: "recall" });
    expect(routeKey(up, { ...field, fieldEmpty: false }).kind).toBe("none");
    const log = new SentLog();
    expect(log.recall()).toBe("");
    log.remember("first");
    log.remember("second");
    expect(log.recall()).toBe("second");
  });

  it("Escape interrupts while speaking, else leaves the field", () => {
    const esc = press("Escape", { code: "Escape" });
    expect(routeKey(esc, { ...field, answering: true }).kind).toBe("interrupt");
    expect(routeKey(esc, field).kind).toBe("blur");
  });

  it("`/` and letters type themselves", () => {
    expect(routeKey(press("/", { code: "Slash" }), field).kind).toBe("none");
    expect(routeKey(press("h"), field).kind).toBe("none");
  });
});

const cap = (user: string, source: Caption["source"], reply = "", streaming = false): Caption => ({ user, source, reply, streaming });
const EMPTY = cap("", null);

/** Play captions through the thread, as the store would hand them over. */
function play(t: Thread, ...captions: Caption[]): Thread {
  let prev = EMPTY;
  for (const c of captions) {
    t = fromCaption(t, prev, c);
    prev = c;
  }
  return t;
}

describe("the thread", () => {
  it("builds one entry per turn, newest at the bottom, streaming then done", () => {
    let t = play(emptyThread(), cap("Hi", "voice"), cap("Hi", "voice", "Hel", true), cap("Hi", "voice", "Hello", true));
    expect(t.entries.map((e) => [e.user, e.reply, e.phase])).toEqual([["Hi", "Hello", "streaming"]]);
    t = fromCaption(t, cap("Hi", "voice", "Hello", true), cap("Hi", "voice", "Hello.", false));
    t = fromCaption(t, cap("Hi", "voice", "Hello.", false), cap("Lights", "text"));
    expect(t.entries.map((e) => [e.user, e.origin, e.reply, e.phase])).toEqual([
      ["Hi", "voice", "Hello.", "done"],
      ["Lights", "text", "", "waiting"],
    ]);
  });

  it("shows a typed message at once and keeps it when the daemon echoes it", () => {
    let t = sent(emptyThread(), "Lights on", false);
    expect(t.entries[0]?.phase).toBe("sending");
    t = play(t, cap("Lights on", "text"));
    expect(t.entries).toHaveLength(1);
    expect(t.entries[0]?.phase).toBe("waiting");
  });

  it("keeps unconfirmed messages below a turn that started elsewhere", () => {
    let t = sent(emptyThread(), "Mine", false);
    t = play(t, cap("From the phone", "phone"));
    expect(t.entries.map((e) => [e.user, e.phase])).toEqual([
      ["From the phone", "waiting"],
      ["Mine", "sending"],
    ]);
  });

  it("a message sent during a reply waits below it while the old reply closes", () => {
    let t = play(emptyThread(), cap("One", "text"), cap("One", "text", "First", true));
    t = sent(t, "Two", false);
    t = fromCaption(t, cap("One", "text", "First", true), cap("One", "text", "First", false));
    expect(t.entries.map((e) => [e.user, e.reply, e.phase])).toEqual([
      ["One", "First", "done"],
      ["Two", "", "sending"],
    ]);
    t = fromCaption(t, cap("One", "text", "First", false), cap("Two", "text"));
    expect(t.entries.map((e) => e.phase)).toEqual(["done", "waiting"]);
  });

  it("a turn closed without a word reads as interrupted", () => {
    const t = play(emptyThread(), cap("Hi", "voice"), cap("Hi", "voice", "", false));
    expect(t.entries[0]?.ended).toBe("interrupted");
  });

  it("a message taken as the answer to a request is marked so", () => {
    let t = sent(emptyThread(), "yes", true);
    t = gateResolved(sent(t, "later", false));
    expect(t.entries.map((e) => e.phase)).toEqual(["answer", "sending"]);
    expect(entryStatus(t.entries[0]!)).toBe("Taken as the answer to the request");
  });

  it("knows when a reply starts streaming", () => {
    const a = play(emptyThread(), cap("Hi", "voice"));
    const b = fromCaption(a, cap("Hi", "voice"), cap("Hi", "voice", "He", true));
    const c = fromCaption(b, cap("Hi", "voice", "He", true), cap("Hi", "voice", "Hello", true));
    expect(replyStarted(a, b)).toBe(true);
    expect(replyStarted(b, c)).toBe(false);
  });

  it("labels each entry by where it came from", () => {
    expect(entryLabel("text")).toBe("You · typed");
    expect(entryLabel("voice")).toBe("You · spoken");
    expect(entryLabel("phone")).toBe(whoSaid("phone"));
    expect(entryLabel("automation")).toBe("Automation");
    expect(entryLabel(null)).toBe("You");
  });
});

describe("history", () => {
  const turn = (started_at: number, user_text: string, reply: string, source = "text", status = "ok") => ({
    turn_id: `t${started_at}`,
    started_at,
    ended_at: started_at + 1,
    source,
    user_text,
    reply,
    status,
    brain: "claude",
    model: "m",
  });

  it("narrows the daemon's answer and leaves out what is malformed", () => {
    const turns = asTurns({ turns: [turn(1, "a", "b", "phone", "interrupted"), { started_at: "x" }, turn(2, "c", "d", "fax", "odd")] });
    expect(turns).toEqual([{ startedAt: 1, origin: "phone", user: "a", reply: "b", status: "interrupted" }]);
    expect(asTurns(null)).toEqual([]);
    expect(asTurns({ turns: "no" })).toEqual([]);
  });

  it("puts earlier turns above the live ones, oldest first, without repeating one shown live", () => {
    let t = play(emptyThread(), cap("Now", "voice"), cap("Now", "voice", "Live", false));
    t = withHistory(t, asTurns({ turns: [turn(30, "Third", "3"), turn(10, "First", "1", "automation"), turn(20, "Second", "2"), turn(40, "Now", "Live", "voice")] }));
    expect(t.entries.map((e) => e.user)).toEqual(["First", "Second", "Third", "Now"]);
    expect(t.entries[0]?.origin).toBe("automation");
    expect(new Set(t.entries.map((e) => e.id)).size).toBe(4);
  });
});
