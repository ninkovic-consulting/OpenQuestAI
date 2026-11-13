// Mock mode's waiting messages, held as the daemon holds them: at most five
// typed while the assistant answers, listed on every change, taken back, or
// taken (all, or up to one sent now) for the turn that answers them together.

import type { ImageRef } from "./image-types";
import { MAX_WAITING, type WaitingMessage } from "./queue-types";

const PREVIEW_CHARS = 140;

interface Held {
  id: string;
  text: string;
  images: ImageRef[];
  at: number;
}

function preview(text: string, images: number): string {
  const flat = text.split(/\s+/).filter(Boolean).join(" ");
  if (!flat) return images === 1 ? "The owner sent this image." : `The owner sent these ${images} images.`;
  return flat.length <= PREVIEW_CHARS ? flat : `${flat.slice(0, PREVIEW_CHARS - 1).trimEnd()}…`;
}

export class MockQueue {
  private held: Held[] = [];

  constructor(private readonly changed: (items: WaitingMessage[]) => void) {}

  get size(): number {
    return this.held.length;
  }

  /** False when five already wait. */
  add(text: string, images: ImageRef[], id: string, force = false): boolean {
    if (!force && this.held.length >= MAX_WAITING) return false;
    this.held.push({ id, text, images, at: Date.now() / 1000 });
    this.publish();
    return true;
  }

  has(id: string): boolean {
    return this.held.some((m) => m.id === id);
  }

  takeBack(id: string): void {
    const kept = this.held.filter((m) => m.id !== id);
    if (kept.length === this.held.length) return;
    this.held = kept;
    this.publish();
  }

  /** Everything that waits, or the messages up to `upto`; the rest keep waiting. */
  take(upto: string | null): Held[] {
    const at = upto === null ? -1 : this.held.findIndex((m) => m.id === upto);
    const count = at === -1 ? this.held.length : at + 1;
    const batch = this.held.slice(0, count);
    this.held = this.held.slice(count);
    return batch;
  }

  publish(): void {
    this.changed(this.held.map((m) => ({ id: m.id, preview: preview(m.text, m.images.length), images: m.images.length, source: "text", at: m.at })));
  }
}
