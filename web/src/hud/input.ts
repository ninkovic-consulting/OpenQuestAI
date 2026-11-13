// The keyboard and the message field. The field is always there; typing
// anywhere goes into it unless another input, a form or a dialog has focus.
// Enter sends and keeps the field ready for the next message; Space held is
// push to talk while the field is empty and unfocused; Escape interrupts the
// assistant while it speaks, otherwise leaves the field, then backs out of
// whatever is open, one step at a time. The rules are in chat/keys.ts.

import type { Daemon } from "../net/daemon";
import type { Store } from "../net/store";
import { envelope } from "../net/types";
import { makeComposer } from "./chat/composer";
import { chatDock } from "./chat/dock";
import type { HistoryLoader } from "./chat/history";
import { type Focus, type KeyAction, OVERLAYS, routeKey } from "./chat/keys";
import { SentLog } from "./chat/recall";
import { Talk } from "./chat/talk";
import { el } from "./dom";

/** Things Escape can back out of, tried in order until one says it did something. */
export type EscapeStep = () => boolean;

function focusOf(target: EventTarget | null, field: HTMLTextAreaElement): Focus {
  if (target === field) return "field";
  if (!(target instanceof HTMLElement)) return "other";
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return "editable";
  if (target.isContentEditable || target.closest("form, [role='dialog'], [role='alertdialog']")) return "editable";
  return "other";
}

function mountHints(parent: HTMLElement): void {
  const hints = el("div", "hint-bar caps");
  for (const [key, what, cls] of [
    ["Enter", "send", ""],
    ["Space", "hold to talk", ""],
    ["↑", "last message", "is-optional"],
    ["Esc", "stop · back", ""],
  ] as const) {
    const item = el("span", cls);
    item.append(el("kbd", "", key), what);
    hints.append(item);
  }
  parent.append(hints);
}

/** `history` loads the earlier conversation into the thread when the daemon client offers it. */
export function mountInput(
  parent: HTMLElement,
  store: Store,
  daemon: Daemon,
  escapeSteps: EscapeStep[],
  history?: HistoryLoader,
): void {
  const dock = chatDock(parent, store);
  const talk = new Talk((down) => {
    daemon.send(envelope("input.ptt", { down }));
    showListening();
  });
  const composer = makeComposer(talk);
  const { field } = composer;
  dock.root.append(composer.row);
  mountHints(parent);
  const log = new SentLog();
  const steps: EscapeStep[] = [() => dock.collapse(), ...escapeSteps];

  const showListening = (): void => composer.setListening(talk.held || store.get().assistant === "listening");
  const showName = (): void => composer.setName(store.get().plan?.assistant.name ?? "");
  showName();
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan) showName();
    if (s.assistant !== prev.assistant) showListening();
  });
  if (history) void dock.load(history);

  const send = (): void => {
    const text = field.value.trim();
    if (!text) return;
    // Not connected: the daemon client says so, and the draft stays.
    if (store.get().connection !== "open") return daemon.send(envelope("input.text", { text }));
    // Shown first: the echo may come back before `send` returns.
    dock.sent(text);
    daemon.send(envelope("input.text", { text }));
    log.remember(text);
    field.value = "";
    composer.fit();
  };

  const typeIn = (text: string): void => {
    if (document.activeElement !== field) {
      field.focus();
      field.setSelectionRange(field.value.length, field.value.length);
    }
    field.setRangeText(text, field.selectionStart, field.selectionEnd, "end");
    composer.fit();
  };

  const act = (a: KeyAction): void => {
    switch (a.kind) {
      case "none":
        return;
      case "send":
        return send();
      case "recall":
        field.value = log.recall();
        field.setSelectionRange(field.value.length, field.value.length);
        return composer.fit();
      case "interrupt":
        return daemon.send(envelope("input.interrupt", {}));
      case "blur":
        return field.blur();
      case "step-back":
        steps.some((step) => step());
        return;
      case "focus":
        return field.focus();
      case "type":
        return typeIn(a.text);
      case "talk":
        return talk.down("key");
    }
  };

  window.addEventListener("keydown", (ev) => {
    const action = routeKey(
      { key: ev.key, code: ev.code, shift: ev.shiftKey, ctrl: ev.ctrlKey, meta: ev.metaKey, alt: ev.altKey, composing: ev.isComposing },
      {
        focus: focusOf(ev.target, field),
        overlay: document.querySelector(OVERLAYS) !== null,
        fieldEmpty: field.value === "",
        speaking: store.get().assistant === "speaking",
      },
    );
    // Escape still reaches the shortcuts of whatever is open; everything else we act on is ours.
    if (action.kind !== "none" && action.kind !== "step-back" && action.kind !== "interrupt") ev.preventDefault();
    act(action);
  });
  window.addEventListener("keyup", (ev) => {
    if (ev.code === "Space") talk.up("key");
  });
  window.addEventListener("blur", () => talk.cancel());
}
