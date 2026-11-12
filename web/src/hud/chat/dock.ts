// The chat dock along the bottom of the scene: the thread above, the message
// field below. The caption and the input each mount their half into the same
// dock, found by the store they share.

import "../../styles/chat.css";
import type { Store } from "../../net/store";
import { el } from "../dom";
import { emptyThread, fromCaption, gateResolved, sent, type Thread, withHistory } from "./entries";
import { asTurns, type HistoryLoader } from "./history";

export type ThreadListener = (thread: Thread, previous: Thread) => void;

export class ChatDock {
  readonly root = el("div", "chat");
  private thread: Thread = emptyThread();
  private readonly listeners = new Set<ThreadListener>();
  /** Folds the expanded thread back to the latest exchange; false when it was not expanded. Set by the thread view. */
  collapse: () => boolean = () => false;

  constructor(private readonly store: Store) {
    store.subscribe((s, prev) => {
      let next = fromCaption(this.thread, prev.caption, s.caption);
      if (s.gates.length < prev.gates.length) next = gateResolved(next);
      this.set(next);
    });
  }

  get(): Thread {
    return this.thread;
  }

  subscribe(listener: ThreadListener): void {
    this.listeners.add(listener);
  }

  /** A message typed here, shown before the daemon echoes it. */
  sent(text: string): void {
    this.set(sent(this.thread, text, this.store.get().gates.length > 0));
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
