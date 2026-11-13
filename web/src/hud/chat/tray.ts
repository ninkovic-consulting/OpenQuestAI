// The images waiting to go with the next message, as data: each is checked
// here first (its kind by its first bytes, its size, how many already wait),
// then waits while it uploads, then is ready. The line beside the field says
// why an image was refused and goes at the next thing that works. Every
// function is pure; attach.ts feeds them.

import type { BrainMode } from "../../net/brain-types";
import type { ImageLimits, ImageRef } from "../../net/image-types";
import { imageRefusal } from "../../net/image-sniff";

export interface Waiting {
  /** This window's own name for it, before the daemon has given it one. */
  key: number;
  state: "pending" | "ready";
  /** The daemon's image, once uploaded. */
  image: ImageRef | null;
}

export interface Tray {
  items: Waiting[];
  nextKey: number;
  /** Why the last image or send was refused; null once something worked. */
  refusal: string | null;
}

/** A file offered by paste, drop or the picker: its size and its first bytes. */
export interface Offered {
  size: number;
  head: Uint8Array;
}

export const BLOCKED = "Images need Claude or a local model that can see; offline mode is on with a text-only model.";
const STILL_UPLOADING = "An image is still uploading; press Enter again when it is ready.";

export const emptyTray = (): Tray => ({ items: [], nextKey: 1, refusal: null });

/** Offline mode with a model that reads text only: images would fail after sending, so they are refused now. */
export function imagesBlocked(mode: BrainMode | null): boolean {
  return mode !== null && mode.offline && mode.local_images !== true;
}

const tooMany = (max: number): string => `At most ${max} images go with one message.`;

/**
 * Files offered at once. Each that passes waits as pending, in order, until
 * the tray is full; the keys given are those of the files taken, by index.
 * The first refusal is the one shown; all taken and none refused clears it.
 */
export function offer(t: Tray, files: readonly Offered[], limits: ImageLimits, blocked: boolean): { tray: Tray; taken: { index: number; key: number }[] } {
  if (files.length === 0) return { tray: t, taken: [] };
  if (blocked) return { tray: { ...t, refusal: BLOCKED }, taken: [] };
  let refusal: string | null = null;
  const items = t.items.slice();
  let nextKey = t.nextKey;
  const taken: { index: number; key: number }[] = [];
  files.forEach((f, index) => {
    const why = items.length >= limits.max_per_message ? tooMany(limits.max_per_message) : imageRefusal(f.size, f.head, limits);
    if (why !== null) {
      refusal ??= why;
      return;
    }
    const key = nextKey++;
    items.push({ key, state: "pending", image: null });
    taken.push({ index, key });
  });
  return { tray: { items, nextKey, refusal }, taken };
}

/** The upload finished; an image removed meanwhile stays removed (the caller forgets it on the daemon). */
export function uploaded(t: Tray, key: number, image: ImageRef): Tray {
  if (!t.items.some((w) => w.key === key)) return t;
  return { ...t, items: t.items.map((w) => (w.key === key ? { ...w, state: "ready" as const, image } : w)) };
}

/** The daemon refused it: it leaves the tray and its reason is shown. */
export function failed(t: Tray, key: number, why: string): Tray {
  if (!t.items.some((w) => w.key === key)) return t;
  return { ...t, items: t.items.filter((w) => w.key !== key), refusal: why };
}

/** The owner took it out before sending. */
export function removeImage(t: Tray, key: number): Tray {
  return { ...t, items: t.items.filter((w) => w.key !== key), refusal: null };
}

export function refuse(t: Tray, why: string): Tray {
  return t.refusal === why ? t : { ...t, refusal: why };
}

export type Send = { ok: true; images: ImageRef[] } | { ok: false; why: string | null };

/**
 * What Enter sends with the text. An image alone may go; nothing at all is no
 * send and no complaint. Enter while an image still uploads is refused plainly:
 * the draft and the images stay.
 */
export function readyToSend(t: Tray, text: string, blocked: boolean): Send {
  if (t.items.length === 0) return text === "" ? { ok: false, why: null } : { ok: true, images: [] };
  if (blocked) return { ok: false, why: BLOCKED };
  if (t.items.some((w) => w.state === "pending")) return { ok: false, why: STILL_UPLOADING };
  return { ok: true, images: t.items.flatMap((w) => (w.image ? [w.image] : [])) };
}

/** The remove button's name: "Remove image 2 of 3". */
export const removeLabel = (index: number, count: number): string => `Remove image ${index + 1} of ${count}`;
