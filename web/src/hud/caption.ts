// The caption band along the bottom of the scene: your words small, the
// reply large, updating as `vision.delta` streams in. A reply is always
// readable from its first word: the band grows upward, the type steps down
// for long replies, and only a reply that still does not fit scrolls.

import type { Store, ViewState } from "../net/store";
import { el, setText } from "./dom";

export type ReplySize = "normal" | "long" | "longer";

/** Characters up to which a reply keeps each size. */
const NORMAL_MAX = 140;
const LONG_MAX = 320;

export function replySize(text: string): ReplySize {
  if (text.length <= NORMAL_MAX) return "normal";
  return text.length <= LONG_MAX ? "long" : "longer";
}

export function mountCaption(parent: HTMLElement, store: Store): void {
  const root = el("div", "caption is-empty");
  root.setAttribute("aria-live", "polite");
  const userCol = el("div", "user-col");
  const replyCol = el("div", "reply-col");
  const you = el("div", "who caps", "You");
  const user = el("div", "user");
  const name = el("div", "who caps");
  const reply = el("div", "reply");
  const replyText = el("span");
  reply.append(replyText);
  userCol.append(you, user);
  replyCol.append(name, reply);
  root.append(userCol, replyCol);
  parent.append(root);

  const render = (s: ViewState, prev: ViewState | null): void => {
    setText(name, s.plan?.assistant.name ?? "");
    setText(user, s.caption.user);
    setText(replyText, s.caption.reply);
    reply.dataset["size"] = replySize(s.caption.reply);
    // A new turn starts at its first word.
    if (prev && s.caption.user !== prev.caption.user) reply.scrollTop = 0;
    reply.classList.toggle("is-scrolling", reply.scrollHeight > reply.clientHeight + 1);
    userCol.style.visibility = s.caption.user ? "visible" : "hidden";
    replyCol.style.visibility = s.caption.reply ? "visible" : "hidden";
    root.classList.toggle("is-empty", !s.caption.user && !s.caption.reply);
  };
  render(store.get(), null);
  store.subscribe((s, prev) => {
    if (s.caption !== prev.caption || s.plan !== prev.plan) render(s, prev);
  });
}
