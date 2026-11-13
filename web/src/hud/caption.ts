// The conversation above the message field. Collapsed, it is the caption
// band: the latest exchange only, your words small, the reply large, readable
// from its first word (the type steps down for long replies and only what
// still does not fit scrolls). Scrolling up over it, or "Earlier", expands it
// to the earlier exchanges in a smaller size; a new reply collapses it again.

import type { Store } from "../net/store";
import { chatDock } from "./chat/dock";
import { type Entry, type Origin, replyStarted, type Thread } from "./chat/entries";
import { el, setText } from "./dom";

export type ReplySize = "normal" | "long" | "longer";

/** Characters up to which a reply keeps each size. */
const NORMAL_MAX = 140;
const LONG_MAX = 320;

export function replySize(text: string): ReplySize {
  if (text.length <= NORMAL_MAX) return "normal";
  return text.length <= LONG_MAX ? "long" : "longer";
}

/** Who the words came from. */
export function whoSaid(origin: Origin | null): string {
  if (origin === "phone") return "You, from the phone";
  if (origin === "job") return "Job report";
  return origin === "automation" ? "Automation" : "You";
}

/** The label above the user's words: who, and how when it was here at the Mac; for a job report, whose job. */
export function entryLabel(origin: Origin | null, agent?: string): string {
  if (origin === "text") return `${whoSaid(origin)} · typed`;
  if (origin === "job" && agent) return `${whoSaid(origin)} · ${agent}`;
  return origin === "voice" ? `${whoSaid(origin)} · spoken` : whoSaid(origin);
}

/** The line in the reply column while there is no reply, or under one that was cut short. */
export function entryStatus(e: Entry): string {
  switch (e.phase) {
    case "sending":
      return "Sent";
    case "waiting":
      return "Waiting for the reply";
    case "answer":
      return "Taken as the answer to the request";
    case "streaming":
      return "";
    case "done":
      if (e.ended === "interrupted") return e.reply ? "Stopped" : "No reply";
      return "";
  }
}

interface EntryView {
  root: HTMLElement;
  who: HTMLElement;
  user: HTMLElement;
  name: HTMLElement;
  reply: HTMLElement;
  status: HTMLElement;
  statusText: HTMLElement;
  shown: Entry | null;
}

function entryView(): EntryView {
  const root = el("article", "entry");
  const userCol = el("div", "user-col");
  const replyCol = el("div", "reply-col");
  const who = el("div", "who caps");
  const user = el("div", "user");
  const name = el("div", "who caps");
  const reply = el("div", "reply");
  const status = el("div", "entry-note caps");
  const statusText = el("span");
  status.append(el("span", "dot"), statusText);
  userCol.append(who, user);
  replyCol.append(name, reply, status);
  root.append(userCol, replyCol);
  return { root, who, user, name, reply, status, statusText, shown: null };
}

function paint(v: EntryView, e: Entry, assistant: string): void {
  setText(v.name, assistant);
  if (v.shown === e) return;
  v.shown = e;
  setText(v.who, entryLabel(e.origin, e.agent));
  setText(v.user, e.user);
  setText(v.reply, e.reply);
  v.reply.dataset["size"] = replySize(e.reply);
  const status = entryStatus(e);
  setText(v.statusText, status);
  v.status.hidden = status === "";
  v.root.dataset["phase"] = e.phase;
}

export function mountCaption(parent: HTMLElement, store: Store): void {
  const dock = chatDock(parent, store);
  const thread = el("section", "thread is-empty");
  thread.setAttribute("aria-label", "Conversation");
  const toggle = el("button", "thread-toggle caps");
  toggle.type = "button";
  const list = el("div", "thread-list");
  list.setAttribute("aria-live", "polite");
  thread.append(toggle, list);
  dock.root.prepend(thread);

  const views = new Map<number, EntryView>();
  let expanded = false;

  const latestReply = (): HTMLElement | null => views.get(dock.get().entries.at(-1)?.id ?? -1)?.reply ?? null;
  const toBottom = (): void => {
    list.scrollTop = list.scrollHeight;
  };

  const labelToggle = (): void => setText(toggle, expanded ? "Latest only" : `Earlier · ${dock.get().entries.length - 1}`);

  const setExpanded = (on: boolean): boolean => {
    const earlier = dock.get().entries.length > 1;
    const next = on && earlier;
    if (next === expanded) return false;
    expanded = next;
    thread.dataset["mode"] = expanded ? "expanded" : "collapsed";
    labelToggle();
    if (expanded) requestAnimationFrame(toBottom);
    else {
      list.scrollTop = 0;
      const reply = latestReply();
      if (reply) reply.scrollTop = 0;
    }
    return true;
  };
  dock.collapse = () => setExpanded(false);

  const render = (t: Thread, prev: Thread | null): void => {
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
    const assistant = store.get().plan?.assistant.name ?? "";
    const ids = new Set(t.entries.map((e) => e.id));
    for (const [id, v] of views) {
      if (!ids.has(id)) {
        v.root.remove();
        views.delete(id);
      }
    }
    t.entries.forEach((e, i) => {
      let v = views.get(e.id);
      if (!v) {
        v = entryView();
        views.set(e.id, v);
      }
      paint(v, e, assistant);
      v.root.classList.toggle("is-latest", i === t.entries.length - 1);
      if (list.children[i] !== v.root) list.insertBefore(v.root, list.children[i] ?? null);
    });
    toggle.hidden = t.entries.length < 2;
    labelToggle();
    thread.classList.toggle("is-empty", t.entries.length === 0);
    if (prev && replyStarted(prev, t)) setExpanded(false);
    else if (expanded && atBottom) toBottom();
  };

  thread.dataset["mode"] = "collapsed";
  render(dock.get(), null);
  dock.subscribe(render);
  store.subscribe((s, prev) => {
    if (s.plan !== prev.plan) render(dock.get(), null);
  });

  toggle.addEventListener("click", () => setExpanded(!expanded));
  // Scrolling up past the start of the latest reply opens the earlier ones.
  list.addEventListener(
    "wheel",
    (ev) => {
      if (expanded || ev.deltaY >= 0) return;
      const reply = latestReply();
      if (!reply || reply.scrollTop <= 0) setExpanded(true);
    },
    { passive: true },
  );
}
