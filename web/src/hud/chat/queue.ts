// Messages written while the assistant answers, as pure decisions: whether
// Enter sends or queues, what the key hints say, the waiting list the thread
// and the widget show, and when one more is refused. The daemon holds what
// waits (`queue.changed`), so every window shows the same list and a reload
// loses nothing; this window only names its messages so it can find them.

import { MAX_WAITING, type WaitingMessage } from "../../net/queue-types";
import type { ViewState } from "../../net/store";
import { imageMark } from "./thumbs";

/** The assistant is at work on a turn: thinking (tools included) or speaking. */
export function answering(assistant: ViewState["assistant"]): boolean {
  return assistant === "thinking" || assistant === "speaking";
}

/** Enter queues rather than sends: a turn runs, or this window's lane already holds messages. */
export function queues(s: Pick<ViewState, "assistant" | "queue">): boolean {
  return answering(s.assistant) || s.queue.some((m) => m.source === "text");
}

/** One more message would be refused: the window's lane is full. */
export function queueFull(queue: readonly WaitingMessage[]): boolean {
  return queue.filter((m) => m.source === "text").length >= MAX_WAITING;
}

export const FULL_LINE = `${MAX_WAITING} messages already wait. Take one back, or press ⌘ Enter to stop the reply and send them all now.`;

/** The key hints for sending, as [key, what] pairs: what Enter does right now. */
export function sendHints(busy: boolean): Array<readonly [string, string]> {
  return busy ? [["Enter", "queues"], ["⌘ Enter", "sends now"]] : [["Enter", "sends"]];
}

/** A message's name for the daemon, chosen here so the window can find it in the queue and the turn. */
export function newMessageId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

export interface WaitingRow {
  id: string;
  /** Who wrote it, as the thread labels the owner's words. */
  who: string;
  text: string;
  /** How many images go with it, in words; empty for none. */
  mark: string;
  note: string;
  /** Send now and take back: only for what was typed at the Mac. */
  controls: boolean;
}

/** The waiting list under the thread, in the order the messages will go. */
export function waitingRows(queue: readonly WaitingMessage[]): WaitingRow[] {
  return queue.map((m) => ({
    id: m.id,
    who: m.source === "phone" ? "You, from the phone" : "You · typed",
    text: m.preview,
    mark: imageMark(m.images),
    note: m.source === "phone" ? "Goes after this reply, as its own turn" : "Sends after this reply",
    controls: m.source === "text",
  }));
}

/** The widget's line about what waits: the count and the newest, or null when nothing does. */
export function waitingLine(queue: readonly WaitingMessage[]): string | null {
  const newest = queue.at(-1);
  if (!newest) return null;
  return `${queue.length} waiting · ${newest.preview}`;
}
