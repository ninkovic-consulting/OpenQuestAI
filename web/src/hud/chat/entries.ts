// The conversation thread as data: earlier turns from `/api/history`, then
// the live ones built from the store's caption, then what was typed here and
// not yet echoed back. Every function is pure; the dock feeds them.

import type { Caption } from "../../net/store";

/** Where a turn came from, when that is known. */
export type Origin = "text" | "voice" | "automation" | "phone";

/**
 * `sending`: typed here, not yet echoed by the daemon. `waiting`: accepted,
 * no reply yet. `streaming`: the reply is arriving. `done`: closed.
 * `answer`: typed while a request waited and taken as its answer (no reply).
 */
export type Phase = "sending" | "waiting" | "streaming" | "done" | "answer";

export interface Entry {
  id: number;
  user: string;
  origin: Origin | null;
  reply: string;
  phase: Phase;
  /** How a closed turn ended; `interrupted` when it closed without a word. */
  ended: "ok" | "interrupted" | "failed" | null;
  /** Typed while a request was waiting, so the daemon may take it as the answer. */
  toGate: boolean;
}

export interface Thread {
  entries: Entry[];
  nextId: number;
}

/** A turn from `/api/history`, narrowed to what the thread shows. */
export interface HistoryTurn {
  startedAt: number;
  origin: Origin | null;
  user: string;
  reply: string;
  status: "ok" | "interrupted" | "failed";
}

export const emptyThread = (): Thread => ({ entries: [], nextId: 1 });

const ORIGINS: ReadonlySet<string> = new Set<Origin>(["text", "voice", "automation", "phone"]);

export function asOrigin(source: string | null): Origin | null {
  return source !== null && ORIGINS.has(source) ? (source as Origin) : null;
}

const open = (phase: Phase): boolean => phase === "waiting" || phase === "streaming";

function add(t: Thread, entry: Omit<Entry, "id">, beforePending: boolean): Thread {
  const made: Entry = { ...entry, id: t.nextId };
  const firstPending = beforePending ? t.entries.findIndex((e) => e.phase === "sending") : -1;
  const at = firstPending === -1 ? t.entries.length : firstPending;
  return { entries: [...t.entries.slice(0, at), made, ...t.entries.slice(at)], nextId: t.nextId + 1 };
}

/** A message typed here: shown at once, below everything, until the daemon echoes it. */
export function sent(t: Thread, text: string, toGate: boolean): Thread {
  return add(t, { user: text, origin: "text", reply: "", phase: "sending", ended: null, toGate }, false);
}

/** A request was answered: typed messages sent to it that were never echoed were the answer. */
export function gateResolved(t: Thread): Thread {
  if (!t.entries.some((e) => e.phase === "sending" && e.toGate)) return t;
  return {
    ...t,
    entries: t.entries.map((e) => (e.phase === "sending" && e.toGate ? { ...e, phase: "answer", ended: "ok" } : e)),
  };
}

/** True when `next` opens a new turn: a `user.utterance` or `automation.started`. */
function startsTurn(prev: Caption, next: Caption): boolean {
  if (next.user === "" || next.reply !== "" || next.streaming) return false;
  return prev.user !== next.user || prev.source !== next.source || prev.reply !== "" || prev.streaming;
}

/** Fold one change of the store's caption into the thread. */
export function fromCaption(t: Thread, prev: Caption, next: Caption): Thread {
  if (prev === next) return t;
  const origin = asOrigin(next.source);
  if (startsTurn(prev, next)) {
    // Whatever was still open closed before this turn began.
    const closed = t.entries.map((e) => (open(e.phase) ? { ...e, phase: "done" as const, ended: e.ended ?? "ok" } : e));
    const mine = origin === "text" ? closed.findIndex((e) => e.phase === "sending" && e.user === next.user) : -1;
    if (mine !== -1) {
      const claimed = { ...closed[mine]!, phase: "waiting" as const };
      // The claimed message moves above any later ones still unconfirmed.
      const rest = closed.filter((_, i) => i !== mine);
      const firstPending = rest.findIndex((e) => e.phase === "sending");
      const at = firstPending === -1 ? rest.length : firstPending;
      return { ...t, entries: [...rest.slice(0, at), claimed, ...rest.slice(at)] };
    }
    return add({ ...t, entries: closed }, { user: next.user, origin, reply: "", phase: "waiting", ended: null, toGate: false }, true);
  }
  const phase: Phase = next.streaming ? "streaming" : "done";
  const ended = next.streaming ? null : next.reply === "" ? "interrupted" : "ok";
  let current = -1;
  for (let i = t.entries.length - 1; i >= 0; i--) {
    if (open(t.entries[i]!.phase)) {
      current = i;
      break;
    }
  }
  if (current === -1) {
    // A reply with no turn shown for it, as when the page opens mid-turn.
    if (next.reply === "") return t;
    return add(t, { user: next.user, origin, reply: next.reply, phase, ended, toGate: false }, true);
  }
  const entries = t.entries.slice();
  entries[current] = { ...entries[current]!, reply: next.reply, phase, ended };
  return { ...t, entries };
}

/** Earlier turns go above the live ones, oldest first; a turn already shown live is not repeated. */
export function withHistory(t: Thread, turns: readonly HistoryTurn[]): Thread {
  const live = new Set(t.entries.map((e) => `${e.user}\u0000${e.reply}`));
  const earlier = [...turns]
    .sort((a, b) => a.startedAt - b.startedAt)
    .filter((h) => !live.has(`${h.user}\u0000${h.reply}`));
  let nextId = t.nextId;
  const made: Entry[] = earlier.map((h) => ({
    id: nextId++,
    user: h.user,
    origin: h.origin,
    reply: h.reply,
    phase: "done",
    ended: h.status,
    toGate: false,
  }));
  return { entries: [...made, ...t.entries], nextId };
}

/** True when this change started a reply streaming. */
export function replyStarted(prev: Thread, next: Thread): boolean {
  if (prev === next) return false;
  const now = next.entries.findLast((e) => e.phase === "streaming");
  if (!now) return false;
  const before = prev.entries.find((e) => e.id === now.id);
  return before?.phase !== "streaming";
}
