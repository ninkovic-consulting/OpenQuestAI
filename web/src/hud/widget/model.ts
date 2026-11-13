// What the widget shows, as pure functions of the store: the assistant's
// name and state, the latest exchange, what waits for the reply to end (the
// count and the newest), and the request that waits for a yes (the oldest,
// with how many more wait; gate.ts decides that for the house and the widget
// alike).

import type { Caption, ViewState } from "../../net/store";
import { asOrigin, type HistoryTurn, type Origin } from "../chat/entries";
import { waitingLine } from "../chat/queue";
import { imageMark } from "../chat/thumbs";
import { gateCard, type GateCard } from "../gate";

export type WidgetState = "idle" | "listening" | "thinking" | "speaking" | "connecting" | "offline";

/** The state the dot and the border show. `held`: push to talk is held here. */
export function widgetState(s: Pick<ViewState, "connection" | "assistant">, held: boolean): WidgetState {
  if (s.connection !== "open") return s.connection === "connecting" ? "connecting" : "offline";
  if (held) return "listening";
  switch (s.assistant) {
    case "listening":
    case "transcribing":
      return "listening";
    case "thinking":
      return "thinking";
    case "speaking":
      return "speaking";
    case "idle":
      return "idle";
  }
}

/** Who the words above the reply came from, and how. */
export function whoLabel(origin: Origin | null, agent?: string): string {
  switch (origin) {
    case "text":
      return "You · typed";
    case "voice":
      return "You · spoken";
    case "phone":
      return "You, from the phone";
    case "automation":
      return "Automation";
    case "job":
      return agent ? `Job report · ${agent}` : "Job report";
    case null:
      return "You";
  }
}

export interface Exchange {
  who: string;
  user: string;
  reply: string;
  /** The line in place of the reply while there is none. */
  status: string;
  streaming: boolean;
}

/** Still at work on a turn: what was said has no reply yet, but one may come. */
const busy = (assistant: ViewState["assistant"]): boolean => assistant !== "idle";

/** The label with how many images came with the words: "You · typed · 2 images". */
export function withImageMark(label: string, images: number): string {
  const mark = imageMark(images);
  return mark ? `${label} · ${mark}` : label;
}

/**
 * The latest exchange: a message just sent from the widget (`pending`, with
 * `pendingImages` images), else the live caption, else the last turn from
 * before the widget opened (`earlier`).
 */
export function latestExchange(
  caption: Caption,
  assistant: ViewState["assistant"],
  pending: string | null,
  earlier: HistoryTurn | null,
  pendingImages = 0,
): Exchange | null {
  if (pending !== null) return { who: withImageMark(whoLabel("text"), pendingImages), user: pending, reply: "", status: "Sent", streaming: false };
  if (caption.user !== "" || caption.reply !== "" || caption.images) {
    const origin = asOrigin(caption.source);
    const status = caption.reply !== "" ? "" : busy(assistant) ? "Waiting for the reply" : "No reply";
    const who = withImageMark(whoLabel(origin, caption.agent), caption.images?.length ?? 0);
    return { who, user: caption.user, reply: caption.reply, status, streaming: caption.streaming };
  }
  if (earlier === null) return null;
  return {
    who: withImageMark(whoLabel(earlier.origin, earlier.agent), earlier.images?.length ?? 0),
    user: earlier.user,
    reply: earlier.reply,
    status: earlier.reply !== "" ? "" : "No reply",
    streaming: false,
  };
}

export interface WidgetView {
  name: string;
  state: WidgetState;
  exchange: Exchange | null;
  /** What waits for the reply to end: "2 waiting · And short.", or null. */
  waiting: string | null;
  /** The oldest request that waits for a yes, and how many more wait after it. */
  gate: GateCard | null;
}

export function widgetView(s: ViewState, held: boolean, pending: string | null, earlier: HistoryTurn | null, pendingImages = 0): WidgetView {
  return {
    name: s.plan?.assistant.name ?? "",
    state: widgetState(s, held),
    exchange: latestExchange(s.caption, s.assistant, pending, earlier, pendingImages),
    waiting: waitingLine(s.queue),
    gate: gateCard(s),
  };
}

/** The top of the reply is where reading starts: a new turn, or a reply that started over, scrolls back up. */
export function replyRestarted(prev: Exchange | null, next: Exchange | null): boolean {
  if (next === null) return false;
  if (prev === null) return true;
  return prev.user !== next.user || prev.who !== next.who || !next.reply.startsWith(prev.reply);
}
