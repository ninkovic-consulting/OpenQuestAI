// The widget: the Mac app's small floating window onto the assistant. The
// name and state on top (the panel is dragged by them), a request waiting for
// a yes, the latest exchange, and the message field with hold to talk. It
// shares the house's store, connection, composer, keys and gate card; the
// shell sizes its panel to this page and calls `window.visionWidget` from its
// global shortcuts.

import type { Daemon } from "../../net/daemon";
import { nativeHelpers } from "../../net/native";
import type { Store } from "../../net/store";
import { envelope } from "../../net/types";
import { makeComposer } from "../chat/composer";
import type { HistoryTurn } from "../chat/entries";
import { asTurns } from "../chat/history";
import { routeKey } from "../chat/keys";
import { SentLog } from "../chat/recall";
import { Talk } from "../chat/talk";
import { el, setText } from "../dom";
import { mountGate } from "../gate";
import { type Exchange, placeholder, replyRestarted, widgetView } from "./model";

/** What the shell calls: the summon shortcut, and push to talk held or let go. */
export interface WidgetHooks {
  summon(): void;
  talk(down: boolean): void;
}

declare global {
  interface Window {
    visionWidget?: WidgetHooks;
  }
}

function button(className: string, text: string, label: string): HTMLButtonElement {
  const b = el("button", className, text);
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  return b;
}

/** `preview` (mock mode) shows the shell's controls even where there is no shell, for screenshots. */
export function mountWidget(parent: HTMLElement, store: Store, daemon: Daemon, preview = false): void {
  const native = nativeHelpers();
  const root = el("div", "widget");

  const head = el("header", "w-head");
  const id = el("div", "w-id");
  const name = el("span", "w-name caps");
  const word = el("span", "w-state caps");
  id.append(el("span", "dot"), name, word);
  const actions = el("div", "w-actions");
  const house = button("w-house caps", "House", "Open the house");
  const hide = button("w-hide caps", "Hide", "Hide the widget");
  house.hidden = native.openHouse === null && !preview;
  hide.hidden = native.showWidget === null && !preview;
  house.addEventListener("click", () => void native.openHouse?.());
  hide.addEventListener("click", () => void native.showWidget?.(false));
  actions.append(house, hide);
  head.append(id, actions);

  const gateSlot = el("div", "w-gate");
  const exchange = el("section", "w-exchange");
  exchange.setAttribute("aria-live", "polite");
  const who = el("p", "w-who caps");
  const user = el("p", "w-user");
  const reply = el("div", "w-reply");
  reply.tabIndex = 0;
  const status = el("p", "w-status caps");
  exchange.append(who, user, reply, status);

  let pending: string | null = null;
  let earlier: HistoryTurn | null = null;
  let shown: Exchange | null = null;

  const talk = new Talk((down) => {
    daemon.send(envelope("input.ptt", { down }));
    render();
  });
  const composer = makeComposer(talk);
  const { field } = composer;
  const compose = el("div", "w-compose");
  compose.append(composer.row);

  root.append(head, gateSlot, exchange, compose);
  parent.append(root);
  mountGate(gateSlot, store, daemon);

  function render(): void {
    const s = store.get();
    const v = widgetView(s, talk.held, pending, earlier);
    root.dataset["state"] = v.state;
    setText(name, v.name);
    setText(word, v.state);
    document.title = v.name || document.title;
    field.placeholder = placeholder(v.name);
    composer.setListening(v.state === "listening");
    exchange.hidden = v.exchange === null;
    if (v.exchange) {
      setText(who, v.exchange.who);
      setText(user, v.exchange.user);
      user.hidden = v.exchange.user === "";
      setText(reply, v.exchange.reply);
      reply.hidden = v.exchange.reply === "";
      reply.classList.toggle("is-streaming", v.exchange.streaming);
      setText(status, v.exchange.status);
      status.hidden = v.exchange.status === "";
    }
    if (replyRestarted(shown, v.exchange)) reply.scrollTop = 0;
    shown = v.exchange;
    more();
  }

  /** A reply longer than its box fades at the bottom while there is more to read. */
  const more = (): void => {
    reply.classList.toggle("has-more", reply.scrollHeight - reply.scrollTop - reply.clientHeight > 2);
  };
  reply.addEventListener("scroll", more);

  store.subscribe((s, prev) => {
    if (s.caption !== prev.caption) pending = null;
    render();
  });
  render();
  void daemon.history().then((r) => {
    if (!r.ok) return;
    earlier = asTurns(r.value).at(-1) ?? null;
    render();
  });

  const log = new SentLog();
  const send = (): void => {
    const text = field.value.trim();
    if (!text) return;
    // Not connected: the daemon client says so, and the draft stays.
    if (store.get().connection !== "open") return daemon.send(envelope("input.text", { text }));
    pending = text;
    daemon.send(envelope("input.text", { text }));
    log.remember(text);
    field.value = "";
    composer.fit();
    render();
  };
  const dismiss = (): void => {
    field.blur();
    void native.dismissWidget?.();
  };

  field.addEventListener("keydown", (ev) => {
    const action = routeKey(
      { key: ev.key, code: ev.code, shift: ev.shiftKey, ctrl: ev.ctrlKey, meta: ev.metaKey, alt: ev.altKey, composing: ev.isComposing },
      { focus: "field", overlay: false, fieldEmpty: field.value === "", speaking: store.get().assistant === "speaking" },
    );
    switch (action.kind) {
      case "send":
        ev.preventDefault();
        return send();
      case "recall":
        ev.preventDefault();
        field.value = log.recall();
        field.setSelectionRange(field.value.length, field.value.length);
        return composer.fit();
      case "interrupt":
        return daemon.send(envelope("input.interrupt", {}));
      case "blur":
        return dismiss();
      default:
        return;
    }
  });
  window.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && ev.target !== field && !ev.defaultPrevented) dismiss();
  });
  // A hold with the pointer ends when the panel loses focus; one with the shortcut ends at its key up.
  let shortcutHeld = false;
  window.addEventListener("blur", () => {
    if (!shortcutHeld) talk.cancel();
  });

  window.visionWidget = Object.freeze({
    summon(): void {
      field.focus();
      field.setSelectionRange(field.value.length, field.value.length);
    },
    talk(down: boolean): void {
      shortcutHeld = down;
      if (down) talk.down("shortcut");
      else talk.up("shortcut");
    },
  });

  // The shell sizes the panel to the page, and lets it be dragged by the name and state.
  const fit = (): void => {
    const box = id.getBoundingClientRect();
    const handle = [0, 0, Math.round(box.right), Math.round(head.getBoundingClientRect().bottom)];
    void native.fitWidget?.(Math.ceil(root.getBoundingClientRect().height), handle);
  };
  new ResizeObserver(fit).observe(root);
}
