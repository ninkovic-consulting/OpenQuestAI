// Whether the owner is looking at the window: the page is shown and has
// focus, and the daemon does not say they are away from the Mac. What arrives
// while they are not is set apart in the thread until they have seen it.

import type { Store } from "../../net/store";
import type { Presence } from "../../net/types";

/** The page as far as attention goes; `document` in the window, a stand-in in tests. */
export interface Page {
  visibilityState: DocumentVisibilityState;
  hasFocus(): boolean;
}

export function looking(page: Page, presence: Presence | null): boolean {
  return page.visibilityState === "visible" && page.hasFocus() && !(presence?.away ?? false);
}

/** Calls `changed` whenever the answer of `looking` may have changed. */
export function followAttention(store: Store, changed: () => void): void {
  document.addEventListener("visibilitychange", changed);
  window.addEventListener("focus", changed);
  window.addEventListener("blur", changed);
  store.subscribe((s, prev) => {
    if (s.presence !== prev.presence) changed();
  });
}
