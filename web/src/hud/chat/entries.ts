// The conversation thread as data: earlier turns from `/api/history`, then
// the live ones built from the store's caption, then what was typed here and
// not yet echoed back. What arrived while nobody was looking is marked, so
// the thread can set it apart when the owner is back. Every function is
// pure; the dock feeds them.

import type { ImageRef } from "../../net/image-types";
import type { Caption } from "../../net/store";

/** Where a turn came from, when that is known. */
export type Origin = "text" | "voice" | "automation" | "phone" | "job";

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
  /** For a job report: the resident whose job it was; `user` is then the job's title. */
  agent?: string;
  reply: string;
  phase: Phase;
  /** How a closed turn ended; `interrupted` when it closed without a word. */
  ended: "ok" | "interrupted" | "failed" | null;
  /** Typed while a request was waiting, so the daemon may take it as the answer. */
  toGate: boolean;
  /** Arrived or changed while the window was not being looked at, and not seen since. */
  away?: true;
  /** Images the owner sent with the words; left out when there are none. */
  images?: ImageRef[];
}

export interface Thread {
  entries: Entry[];
  nextId: number;
}

/** A turn from `/api/history`, narrowed to what the thread shows. */
export interface HistoryTurn {
  startedAt: number;
  origin: Origin | null;
  agent?: string;
  user: string;
  reply: string;
  status: "ok" | "interrupted" | "failed";
  /** Missing counts as none. */
  images?: ImageRef[];
}

export const emptyThread = (): Thread => ({ entries: [], nextId: 1 });

const ORIGINS: ReadonlySet<string> = new Set<Origin>(["text", "voice", "automation", "phone", "job"]);

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

/** Only a non-empty list is kept on an entry. */
const withImages = (images: readonly ImageRef[] | undefined): { images?: ImageRef[] } => (images && images.length > 0 ? { images: [...images] } : {});

/** Which images, so an echo is matched to the message it repeats. */
const imageKey = (images: readonly ImageRef[] | undefined): string => (images ?? []).map((i) => i.id).join(",");

/** A message typed here, perhaps with images: shown at once, below everything, until the daemon echoes it. */
export function sent(t: Thread, text: string, toGate: boolean, images: readonly ImageRef[] = []): Thread {
  return add(t, { user: text, origin: "text", reply: "", phase: "sending", ended: null, toGate, ...withImages(images) }, false);
}

/** A request was answered: typed messages sent to it that were never echoed were the answer. */
export function gateResolved(t: Thread): Thread {
  if (!t.entries.some((e) => e.phase === "sending" && e.toGate)) return t;
  return {
    ...t,
    entries: t.entries.map((e) => (e.phase === "sending" && e.toGate ? { ...e, phase: "answer", ended: "ok" } : e)),
  };
}

/** The resident a job report is about, when the caption names one. */
const about = (c: Caption): { agent?: string } => (c.agent === undefined ? {} : { agent: c.agent });

/** True when `next` opens a new turn: a `user.utterance` (words, images or both) or `automation.started`. */
function startsTurn(prev: Caption, next: Caption): boolean {
  if ((next.user === "" && !next.images) || next.reply !== "" || next.streaming) return false;
  return prev.user !== next.user || prev.source !== next.source || prev.images !== next.images || prev.reply !== "" || prev.streaming;
}

/** Fold one change of the store's caption into the thread. */
export function fromCaption(t: Thread, prev: Caption, next: Caption): Thread {
  if (prev === next) return t;
  const origin = asOrigin(next.source);
  if (startsTurn(prev, next)) {
    // Whatever was still open closed before this turn began.
    const closed = t.entries.map((e) => (open(e.phase) ? { ...e, phase: "done" as const, ended: e.ended ?? "ok" } : e));
    const said = imageKey(next.images);
    const mine = origin === "text" ? closed.findIndex((e) => e.phase === "sending" && e.user === next.user && imageKey(e.images) === said) : -1;
    if (mine !== -1) {
      const claimed = { ...closed[mine]!, phase: "waiting" as const };
      // The claimed message moves above any later ones still unconfirmed.
      const rest = closed.filter((_, i) => i !== mine);
      const firstPending = rest.findIndex((e) => e.phase === "sending");
      const at = firstPending === -1 ? rest.length : firstPending;
      return { ...t, entries: [...rest.slice(0, at), claimed, ...rest.slice(at)] };
    }
    return add({ ...t, entries: closed }, { user: next.user, origin, ...about(next), reply: "", phase: "waiting", ended: null, toGate: false, ...withImages(next.images) }, true);
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
    return add(t, { user: next.user, origin, ...about(next), reply: next.reply, phase, ended, toGate: false, ...withImages(next.images) }, true);
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
    ...(h.agent === undefined ? {} : { agent: h.agent }),
    reply: h.reply,
    phase: "done",
    ended: h.status,
    toGate: false,
    ...withImages(h.images),
  }));
  return { entries: [...made, ...t.entries], nextId };
}

/**
 * Mark what this change brought while nobody was looking: an entry that is new,
 * or whose reply or phase moved. Something typed here is never marked; it was seen.
 */
export function markAway(prev: Thread, next: Thread): Thread {
  if (prev === next) return next;
  const before = new Map(prev.entries.map((e) => [e.id, e]));
  let marked = false;
  const entries = next.entries.map((e) => {
    const was = before.get(e.id);
    const moved = was === undefined || was.reply !== e.reply || was.phase !== e.phase;
    if (e.away || e.phase === "sending" || !moved) return e;
    marked = true;
    return { ...e, away: true as const };
  });
  return marked ? { ...next, entries } : next;
}

/** How many entries arrived while away, and the first of them; null when none did. */
export function awayStart(t: Thread): { id: number; count: number } | null {
  const away = t.entries.filter((e) => e.away);
  const first = away[0];
  return first ? { id: first.id, count: away.length } : null;
}

/** The owner has seen them: the marks go. */
export function seenAway(t: Thread): Thread {
  if (!t.entries.some((e) => e.away)) return t;
  return {
    ...t,
    entries: t.entries.map((e) => {
      if (!e.away) return e;
      const { away: _seen, ...rest } = e;
      return rest;
    }),
  };
}

/** True when this change started a reply streaming. */
export function replyStarted(prev: Thread, next: Thread): boolean {
  if (prev === next) return false;
  const now = next.entries.findLast((e) => e.phase === "streaming");
  if (!now) return false;
  const before = prev.entries.find((e) => e.id === now.id);
  return before?.phase !== "streaming";
}
