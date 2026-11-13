// The chat dock along the bottom of the scene: the thread above, the message
// field below. The caption and the input each mount their half into the same
// dock, found by the store they share.

import "../../styles/chat.css";
import type { ImageRef } from "../../net/image-types";
import type { ImageSource } from "../../net/image-source";
import type { Store } from "../../net/store";
import { el } from "../dom";
import { looking } from "./attention";
import { emptyThread, fromCaption, gateResolved, markAway, nowWaiting, seenAway, sent, type Thread, withHistory } from "./entries";
import { asTurns, type HistoryLoader } from "./history";

export type ThreadListener = (thread: Thread, previous: Thread) => void;

/** What the waiting list's controls do; the input sets them (it talks to the daemon). */
export interface WaitingActions {
  sendNow(id: string): void;
  takeBack(id: string): void;
}

export class ChatDock {
  readonly root = el("div", "chat");
  private thread: Thread = emptyThread();
  private readonly listeners = new Set<ThreadListener>();
  /** Folds the expanded thread back to the latest exchange; false when it was not expanded. Set by the thread view. */
  collapse: () => boolean = () => false;
  /** The waiting list's Send now and Take back. Set by the input. */
  waiting: WaitingActions = { sendNow: () => {}, takeBack: () => {} };
  private giveImages: (source: ImageSource) => void = () => {};
  /**
   * Where the thread's images come from. The thread is drawn before the daemon
   * client exists; its thumbnails wait for this.
   */
  readonly images: Promise<ImageSource> = new Promise((resolve) => (this.giveImages = resolve));

  constructor(private readonly store: Store) {
    store.subscribe((s, prev) => {
      let next = fromCaption(this.thread, prev.caption, s.caption);
      if (s.gates.length < prev.gates.length) next = gateResolved(next);
      if (s.queue !== prev.queue) next = nowWaiting(next, s.queue.map((m) => m.id));
      if (!looking(document, s.presence)) next = markAway(this.thread, next);
      this.set(next);
    });
  }

  get(): Thread {
    return this.thread;
  }

  subscribe(listener: ThreadListener): void {
    this.listeners.add(listener);
  }

  /** A message typed here, perhaps with images, shown before the daemon echoes it; `msgId` is its name for the daemon. */
  sent(text: string, images: readonly ImageRef[] = [], msgId?: string): void {
    this.set(sent(this.thread, text, this.store.get().gates.length > 0, images, msgId));
  }

  /** The daemon client is here: the thread's images can be fetched. */
  provideImages(source: ImageSource): void {
    this.giveImages(source);
  }

  /** What arrived while away has been seen. */
  seen(): void {
    this.set(seenAway(this.thread));
  }

  async load(history: HistoryLoader): Promise<void> {
    const answer = await history();
    if (answer.ok) this.set(withHistory(this.thread, asTurns(answer.value)));
    else this.store.dispatch({ kind: "toast", level: "warn", text: `Could not load the conversation: ${answer.message}` });
  }

  private set(next: Thread): void {
    const previous = this.thread;
    if (next === previous) return;
    this.thread = next;
    for (const l of this.listeners) l(next, previous);
  }
}

const docks = new WeakMap<Store, ChatDock>();

/** The dock for this store, placed in `parent` the first time it is asked for. */
export function chatDock(parent: HTMLElement, store: Store): ChatDock {
  let dock = docks.get(store);
  if (!dock) {
    dock = new ChatDock(store);
    docks.set(store, dock);
    parent.append(dock.root);
  }
  return dock;
}
