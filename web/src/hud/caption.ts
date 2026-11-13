// The conversation above the message field. Collapsed, it is the caption
// band: the latest exchange only, your words small, the reply large, readable
// from its first word (the type steps down for long replies and only what
// still does not fit scrolls). Scrolling up over it, or "Earlier", expands it
// to the earlier exchanges in a smaller size; a new reply collapses it again.
// What arrived while the owner was not looking sits under a quiet divider,
// "While you were away", and the thread opens to it when they are back; the
// divider goes once they have had it in front of them for a few seconds.
// Under the thread, what waits for the reply to end: each message with "Sends
// after this reply", and, for what was typed at the Mac, Send now and Take
// back (`chat/queue.ts`). The daemon holds the list, so every window shows it.

import type { Store, ViewState } from "../net/store";
import { followAttention, looking } from "./chat/attention";
import { type ChatDock, chatDock } from "./chat/dock";
import { awayStart, type Entry, type Origin, replyStarted, type Thread } from "./chat/entries";
import { waitingRows, type WaitingRow } from "./chat/queue";
import { imageMark, type ThumbRow, thumbRow } from "./chat/thumbs";
import { el, setText } from "./dom";

export type ReplySize = "normal" | "long" | "longer";

/** Characters up to which a reply keeps each size. */
const NORMAL_MAX = 140;
const LONG_MAX = 320;
/** How long the owner has the divider in front of them before it counts as seen. */
export const SEEN_MS = 6000;

/** The divider's words: "While you were away · 3". */
export function awayLabel(count: number): string {
  return `While you were away · ${count}`;
}

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
  mark: HTMLElement;
  user: HTMLElement;
  userCol: HTMLElement;
  thumbs: ThumbRow | null;
  /** Which images the thumbnails show, so they are rebuilt only when that changes. */
  thumbsKey: string;
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
  const whoText = el("span", "who-text");
  const mark = el("span", "image-mark");
  mark.hidden = true;
  who.append(whoText, mark);
  const user = el("div", "user");
  const name = el("div", "who caps");
  const reply = el("div", "reply");
  const status = el("div", "entry-note caps");
  const statusText = el("span");
  status.append(el("span", "dot"), statusText);
  userCol.append(who, user);
  replyCol.append(name, reply, status);
  root.append(userCol, replyCol);
  return { root, who: whoText, mark, user, userCol, thumbs: null, thumbsKey: "", name, reply, status, statusText, shown: null };
}

/** The owner's images under their words; drawn again only when they are other images. */
function paintImages(v: EntryView, e: Entry, source: ChatDock["images"]): void {
  const images = e.images ?? [];
  const key = images.map((i) => i.id).join(",");
  if (key === v.thumbsKey) return;
  v.thumbsKey = key;
  v.thumbs?.dispose();
  v.thumbs?.root.remove();
  v.thumbs = images.length > 0 ? thumbRow(images, source) : null;
  if (v.thumbs) v.userCol.append(v.thumbs.root);
  setText(v.mark, imageMark(images.length));
  v.mark.hidden = images.length === 0;
}

function paint(v: EntryView, e: Entry, assistant: string, source: ChatDock["images"]): void {
  setText(v.name, assistant);
  if (v.shown === e) return;
  v.shown = e;
  setText(v.who, entryLabel(e.origin, e.agent));
  setText(v.user, e.user);
  v.user.hidden = e.user === "";
  paintImages(v, e, source);
  setText(v.reply, e.reply);
  v.reply.dataset["size"] = replySize(e.reply);
  const status = entryStatus(e);
  setText(v.statusText, status);
  v.status.hidden = status === "";
  v.root.dataset["phase"] = e.phase;
}

function smallButton(className: string, text: string, label: string, act: () => void): HTMLButtonElement {
  const b = el("button", className, text);
  b.type = "button";
  b.setAttribute("aria-label", label);
  b.addEventListener("mousedown", (ev) => ev.preventDefault());
  b.addEventListener("click", act);
  return b;
}

function waitingRow(row: WaitingRow, dock: ChatDock): HTMLElement {
  const root = el("div", "waiting-row");
  root.dataset["id"] = row.id;
  const side = el("div", "waiting-side");
  side.append(el("div", "who caps", row.mark ? `${row.who} · ${row.mark}` : row.who));
  const note = el("div", "waiting-note caps");
  note.append(el("span", "dot"), row.note);
  side.append(note);
  const body = el("div", "waiting-body");
  body.append(el("p", "waiting-text", row.text));
  if (row.controls) {
    const actions = el("div", "waiting-actions");
    actions.append(
      smallButton("caps", "Send now", `Stop the reply and send: ${row.text}`, () => dock.waiting.sendNow(row.id)),
      smallButton("caps", "Take back", `Take back: ${row.text}`, () => dock.waiting.takeBack(row.id)),
    );
    body.append(actions);
  }
  root.append(side, body);
  return root;
}

/** The messages that wait for the reply to end, under the thread. */
function mountWaiting(after: HTMLElement, store: Store, dock: ChatDock): void {
  const list = el("section", "waiting-list");
  list.setAttribute("aria-label", "Waiting to be sent");
  list.setAttribute("aria-live", "polite");
  after.after(list);
  let shown: ViewState["queue"] | null = null;
  const render = (s: ViewState): void => {
    if (s.queue === shown) return;
    shown = s.queue;
    list.replaceChildren(...waitingRows(s.queue).map((row) => waitingRow(row, dock)));
    list.hidden = s.queue.length === 0;
  };
  render(store.get());
  store.subscribe(render);
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
  mountWaiting(thread, store, dock);

  const views = new Map<number, EntryView>();
  let expanded = false;
  const divider = el("div", "away-divider caps");
  divider.setAttribute("role", "separator");
  let seenTimer = 0;

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
        v.thumbs?.dispose();
        views.delete(id);
      }
    }
    const away = awayStart(t);
    const nodes: HTMLElement[] = [];
    t.entries.forEach((e, i) => {
      let v = views.get(e.id);
      if (!v) {
        v = entryView();
        views.set(e.id, v);
      }
      paint(v, e, assistant, dock.images);
      v.root.classList.toggle("is-latest", i === t.entries.length - 1);
      if (away?.id === e.id) nodes.push(divider);
      nodes.push(v.root);
    });
    if (away) setText(divider, awayLabel(away.count));
    else divider.remove();
    nodes.forEach((node, i) => {
      if (list.children[i] !== node) list.insertBefore(node, list.children[i] ?? null);
    });
    toggle.hidden = t.entries.length < 2;
    labelToggle();
    thread.classList.toggle("is-empty", t.entries.length === 0);
    if (prev && replyStarted(prev, t) && looking(document, store.get().presence)) setExpanded(false);
    else if (expanded && atBottom) toBottom();
  };

  // Back in front of the window with something waiting: open the thread at the divider,
  // and count it seen once it has been there a while.
  const attend = (): void => {
    window.clearTimeout(seenTimer);
    if (!looking(document, store.get().presence) || !awayStart(dock.get())) return;
    setExpanded(true);
    requestAnimationFrame(() => {
      list.scrollTop = Math.max(0, divider.offsetTop - list.offsetTop - 8);
    });
    seenTimer = window.setTimeout(() => {
      if (looking(document, store.get().presence)) dock.seen();
    }, SEEN_MS);
  };
  followAttention(store, attend);

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
