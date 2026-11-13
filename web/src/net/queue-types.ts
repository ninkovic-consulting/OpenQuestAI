// Messages that wait for the assistant to be free: `queue.changed` and `queue`
// in `GET /api/state`. Mirrors `WaitingMessage` in vision/core/events.py.

/** Typed in a window, or sent from the paired phone. */
export type WaitingSource = "text" | "phone";

export interface WaitingMessage {
  id: string;
  /** The start of the words, on one line; for images alone, what they are. */
  preview: string;
  /** How many images go with it. */
  images: number;
  source: WaitingSource;
  /** Unix seconds: when it arrived. */
  at: number;
}

/** The most of the window's messages that may wait; one more is refused. */
export const MAX_WAITING = 5;

function asWaitingMessage(raw: unknown): WaitingMessage | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { id, preview, images, source, at } = raw as Record<string, unknown>;
  if (typeof id !== "string" || typeof preview !== "string" || typeof images !== "number" || typeof at !== "number") return null;
  if (source !== "text" && source !== "phone") return null;
  return { id, preview, images, source, at };
}

/** Raw JSON as the list of waiting messages, or null when it is not one. */
export function asWaitingList(raw: unknown): WaitingMessage[] | null {
  if (!Array.isArray(raw)) return null;
  const list = raw.map(asWaitingMessage);
  return list.every((m): m is WaitingMessage => m !== null) ? list : null;
}
