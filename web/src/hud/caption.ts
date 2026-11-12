// The caption band along the bottom of the scene: your words small, the
// reply large, updating as `vision.delta` streams in.

import type { Store, ViewState } from "../net/store";
import { el, setText } from "./dom";

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

  const render = (s: ViewState): void => {
    setText(name, s.plan?.assistant.name ?? "");
    setText(user, s.caption.user);
    setText(replyText, s.caption.reply);
    userCol.style.visibility = s.caption.user ? "visible" : "hidden";
    replyCol.style.visibility = s.caption.reply ? "visible" : "hidden";
    root.classList.toggle("is-empty", !s.caption.user && !s.caption.reply);
  };
  render(store.get());
  store.subscribe((s, prev) => {
    if (s.caption !== prev.caption || s.plan !== prev.plan) render(s);
  });
}
