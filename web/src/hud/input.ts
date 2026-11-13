// The keyboard and the message field. The field is always there; typing
// anywhere goes into it unless another input, a form or a dialog has focus.
// Enter sends and keeps the field ready for the next message; while the
// assistant answers, what Enter sends waits for the reply to end (the daemon
// holds it and the thread lists it) and Cmd+Enter stops the reply and sends
// at once. Space held is push to talk while the field is empty and unfocused;
// Escape interrupts the assistant while it answers, otherwise leaves the
// field, then backs out of whatever is open, one step at a time. The rules
// are in chat/keys.ts and chat/queue.ts. The Space hint, the hold-to-talk
// control and the field's prompt follow the listening mode (listen.ts).

import type { Daemon } from "../net/daemon";
import { imageSource } from "../net/image-source";
import type { Store, ViewState } from "../net/store";
import { envelope } from "../net/types";
import { mountAttach } from "./chat/attach";
import { makeComposer } from "./chat/composer";
import { chatDock } from "./chat/dock";
import type { HistoryLoader } from "./chat/history";
import { type Focus, type KeyAction, OVERLAYS, routeKey } from "./chat/keys";
import { answering, FULL_LINE, newMessageId, queueFull, queues, sendHints } from "./chat/queue";
import { SentLog } from "./chat/recall";
import { Talk } from "./chat/talk";
import { el } from "./dom";
import { fieldPrompt, modeOf, talkHint, talkLabel } from "./listen";

/** Things Escape can back out of, tried in order until one says it did something. */
export type EscapeStep = () => boolean;

function focusOf(target: EventTarget | null, field: HTMLTextAreaElement): Focus {
  if (target === field) return "field";
  if (!(target instanceof HTMLElement)) return "other";
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return "editable";
  if (target.isContentEditable || target.closest("form, [role='dialog'], [role='alertdialog']")) return "editable";
  return "other";
}

/** The key hints; what Enter does follows the assistant (`queue.ts`), the Space hint the listening mode (`listen.ts`). */
function mountHints(parent: HTMLElement, store: Store): void {
  const hints = el("div", "hint-bar caps");
  const send = el("span", "send-hints");
  const talk = el("span", "talk-hint");
  const items: HTMLElement[] = [];
  for (const [key, what, cls] of [
    ["↑", "last message", "is-optional"],
    ["Esc", "stop · back", ""],
  ] as const) {
    const item = el("span", cls);
    item.append(el("kbd", "", key), what);
    items.push(item);
  }
  hints.append(send, talk, ...items);
  parent.append(hints);
  let shown = "";
  let sending: boolean | null = null;
  const render = (s: ViewState): void => {
    const busy = queues(s);
    if (busy !== sending) {
      sending = busy;
      hints.classList.toggle("is-busy", busy);
      send.replaceChildren(
        ...sendHints(busy).map(([key, what], i) => {
          const item = el("span", i > 0 ? "is-then" : "");
          item.append(el("kbd", "", key), what);
          return item;
        }),
      );
    }
    const text = talkHint(modeOf(s.listen), s.plan?.assistant.name ?? "");
    if (text === shown) return;
    shown = text;
    const [before, after] = text.split("Space");
    talk.replaceChildren(...(after === undefined ? [text] : [before ?? "", el("kbd", before ? "inline" : "", "Space"), after]));
  };
  render(store.get());
  store.subscribe(render);
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
  const composer = makeComposer(talk, () => daemon.send(envelope("input.interrupt", {})));
  const { field } = composer;
  dock.root.append(composer.row);
  const images = imageSource(daemon.images);
  dock.provideImages(images);
  const attach = mountAttach(composer, store, images, true);
  mountHints(parent, store);
  const log = new SentLog();
  const steps: EscapeStep[] = [() => dock.collapse(), ...escapeSteps];

  const showListening = (): void => {
    const s = store.get();
    const name = s.plan?.assistant.name ?? "";
    composer.setTalk(talkLabel(s.listen, talk.held, name), talk.held || s.assistant === "listening");
    composer.setPrompt(fieldPrompt(s.listen, name));
  };
  showListening();
  const showBusy = (s: ViewState): void => composer.setBusy(queues(s), answering(s.assistant));
  showBusy(store.get());
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan || s.assistant !== prev.assistant || s.listen !== prev.listen) showListening();
    if (s.assistant !== prev.assistant || s.queue !== prev.queue) showBusy(s);
  });
  if (history) void dock.load(history);

  /** The words of the messages sent from here that may still wait, so one taken back can come back to the field. */
  const drafts = new Map<string, string>();
  dock.waiting = {
    sendNow: (id) => daemon.send(envelope("input.send_now", { id })),
    takeBack: (id) => {
      daemon.send(envelope("input.take_back", { id }));
      const words = drafts.get(id);
      drafts.delete(id);
      if (words === undefined || field.value !== "") return;
      field.value = words;
      field.focus();
      composer.fit();
    },
  };

  /** Enter: at once when the assistant is free, else it waits; `now` (Cmd+Enter) stops the reply and sends. */
  const send = (now: boolean): void => {
    const s = store.get();
    const busy = queues(s);
    if (busy && !now && queueFull(s.queue)) return store.dispatch({ kind: "toast", level: "warn", text: FULL_LINE });
    const text = field.value.trim();
    // Nothing to send, or images that cannot go yet: the box says why.
    const images = attach.take(text);
    if (images === null) return;
    const id = newMessageId();
    const message = envelope("input.text", {
      text,
      id,
      ...(images.length > 0 ? { images: images.map((i) => i.id) } : {}),
      ...(now && busy ? { now: true } : {}),
    });
    // Not connected: the daemon client says so, and the draft stays.
    if (s.connection !== "open") return daemon.send(message);
    // Shown first when it goes at once or may answer a request (the echo may come back before
    // `send` returns); a message that waits shows in the waiting list instead.
    if (!busy || s.gates.length > 0) dock.sent(text, images, id);
    if (text) drafts.set(id, text);
    if (drafts.size > 20) drafts.delete(drafts.keys().next().value ?? "");
    daemon.send(message);
    if (text) log.remember(text);
    field.value = "";
    attach.sent();
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
        return send(false);
      case "send-now":
        return send(true);
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
        answering: answering(store.get().assistant),
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
