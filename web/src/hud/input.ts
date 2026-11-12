// Keyboard and the text field. `/` opens the field and Enter sends it; Space
// held down is push to talk; Escape interrupts the assistant while it speaks,
// otherwise it backs out of whatever is open, one step at a time.

import type { Daemon } from "../net/daemon";
import type { Store } from "../net/store";
import { envelope } from "../net/types";
import { el } from "./dom";

/** Things Escape can back out of, tried in order until one says it did something. */
export type EscapeStep = () => boolean;

export function mountInput(parent: HTMLElement, store: Store, daemon: Daemon, escapeSteps: EscapeStep[]): void {
  const composer = el("form", "composer");
  const field = el("input");
  field.type = "text";
  field.autocomplete = "off";
  field.maxLength = 20_000;
  field.setAttribute("aria-label", "Message");
  const hint = el("span", "hint caps", "Enter to send");
  composer.append(field, hint);
  parent.append(composer);

  const hints = el("div", "hint-bar caps");
  for (const [key, what] of [
    ["/", "type"],
    ["Space", "hold to talk"],
    ["Esc", "stop · back"],
  ] as const) {
    const item = el("span");
    item.append(el("kbd", "", key), what);
    hints.append(item);
  }
  parent.append(hints);

  const update = (): void => {
    field.placeholder = `Say something to ${store.get().plan?.assistant.name ?? ""}`;
  };
  update();
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan) update();
  });

  const open = (): void => {
    composer.classList.add("is-open");
    field.focus();
  };
  const close = (): boolean => {
    if (!composer.classList.contains("is-open")) return false;
    composer.classList.remove("is-open");
    field.value = "";
    field.blur();
    return true;
  };

  composer.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const text = field.value.trim();
    if (text) daemon.send(envelope("input.text", { text }));
    close();
  });
  field.addEventListener("keydown", (ev) => {
    ev.stopPropagation();
    if (ev.key === "Escape") close();
  });

  let talking = false;
  const typing = (target: EventTarget | null): boolean =>
    target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;

  window.addEventListener("keydown", (ev) => {
    if (typing(ev.target)) return;
    if (ev.key === "/") {
      ev.preventDefault();
      open();
    } else if (ev.code === "Space") {
      ev.preventDefault();
      if (!ev.repeat && !talking) {
        talking = true;
        daemon.send(envelope("input.ptt", { down: true }));
      }
    } else if (ev.key === "Escape") {
      if (store.get().assistant === "speaking") daemon.send(envelope("input.interrupt", {}));
      else escapeSteps.some((step) => step());
    }
  });
  const release = (): void => {
    if (!talking) return;
    talking = false;
    daemon.send(envelope("input.ptt", { down: false }));
  };
  window.addEventListener("keyup", (ev) => {
    if (ev.code === "Space") release();
  });
  window.addEventListener("blur", release);
}
