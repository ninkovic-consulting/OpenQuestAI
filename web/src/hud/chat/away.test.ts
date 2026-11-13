import { describe, expect, it } from "vitest";
import type { Caption } from "../../net/store";
import { initialState, reduce } from "../../net/store";
import { asOutbound, type Presence } from "../../net/types";
import { awayLabel } from "../caption";
import { looking, type Page } from "./attention";
import { awayStart, emptyThread, fromCaption, markAway, seenAway, sent, type Thread } from "./entries";

const idle: Caption = { user: "", source: null, reply: "", streaming: false };
const away: Presence = { away: true, known: true, reason: "locked", since: 100, away_after_s: 300 };
const page = (visible: boolean, focus: boolean): Page => ({ visibilityState: visible ? "visible" : "hidden", hasFocus: () => focus });

/** Play captions into the thread the way the dock does, marking while nobody looks. */
function play(t: Thread, captions: Caption[], watching: boolean): Thread {
  let prev = idle;
  let thread = t;
  for (const c of captions) {
    const next = fromCaption(thread, prev, c);
    thread = watching ? next : markAway(thread, next);
    prev = c;
  }
  return thread;
}

const turn = (user: string, source: Caption["source"], reply: string): Caption[] => [
  { user, source, reply: "", streaming: false },
  { user, source, reply: reply.slice(0, 4), streaming: true },
  { user, source, reply, streaming: false },
];

describe("who is looking", () => {
  it("needs the page shown and focused, and the owner not away", () => {
    expect(looking(page(true, true), null)).toBe(true);
    expect(looking(page(true, true), { ...away, away: false })).toBe(true);
    expect(looking(page(false, true), null)).toBe(false);
    expect(looking(page(true, false), null)).toBe(false);
    expect(looking(page(true, true), away)).toBe(false);
  });

  it("takes presence from the snapshot and from the event", () => {
    const snap = reduce(initialState(), {
      kind: "snapshot",
      initial: true,
      snapshot: { state: "idle", brain: "fake", gate_pending: [], notices: [], budget: { month: "2026-11", spent_usd: 0, cap_usd: 1 }, presence: away },
    });
    expect(snap.presence).toEqual(away);
    const back = asOutbound({ type: "presence", ts: 2, data: { ...away, away: false, reason: null } });
    expect(back).not.toBeNull();
    expect(reduce(snap, { kind: "event", event: back! }).presence?.away).toBe(false);
    expect(asOutbound({ type: "presence", ts: 2, data: { away: "yes" } })).toBeNull();
  });
});

describe("what arrived while away", () => {
  it("marks only what came while nobody looked, and counts it under one divider", () => {
    let t = play(emptyThread(), turn("What is on today?", "text", "Two meetings."), true);
    t = play(t, [...turn("Evening check", "automation", "The tests are green."), ...turn("Fix the date format", "job", "Tink fixed it.")], false);
    expect(t.entries.map((e) => Boolean(e.away))).toEqual([false, true, true]);
    expect(awayStart(t)).toEqual({ id: t.entries[1]!.id, count: 2 });
    expect(awayLabel(2)).toBe("While you were away · 2");
  });

  it("marks a reply that finished after the owner left, but never what was typed here", () => {
    let t = sent(emptyThread(), "Summarise the notes.", false);
    t = play(t, [{ user: "Summarise the notes.", source: "text", reply: "", streaming: false }], true);
    const before = t;
    t = markAway(before, fromCaption(before, { user: "Summarise the notes.", source: "text", reply: "", streaming: false }, { user: "Summarise the notes.", source: "text", reply: "Three things.", streaming: false }));
    expect(t.entries[0]!.away).toBe(true);
    const typed = sent(emptyThread(), "hello", false);
    expect(markAway(emptyThread(), typed).entries[0]!.away).toBeUndefined();
  });

  it("clears once seen, and has nothing to show without marks", () => {
    const t = play(emptyThread(), turn("Evening check", "automation", "Green."), false);
    const seen = seenAway(t);
    expect(awayStart(seen)).toBeNull();
    expect(seen.entries[0]!.reply).toBe("Green.");
    expect(seenAway(seen)).toBe(seen);
  });
});
