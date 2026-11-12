// The message field, always at the bottom of the scene, and the hold-to-talk
// control beside it. The field grows with Shift+Enter up to a few lines.

import { el, setText } from "../dom";
import type { Talk } from "./talk";

export interface Composer {
  row: HTMLElement;
  field: HTMLTextAreaElement;
  /** Re-measure after the text changed from code. */
  fit(): void;
  setName(name: string): void;
  setListening(on: boolean): void;
}

export function makeComposer(talk: Talk): Composer {
  const row = el("div", "compose-row");
  const box = el("div", "composer");
  const dot = el("span", "dot");
  const field = el("textarea", "message-field");
  field.rows = 1;
  field.maxLength = 20_000;
  field.autocomplete = "off";
  field.spellcheck = true;
  field.setAttribute("aria-label", "Message");
  field.setAttribute("enterkeyhint", "send");
  const hint = el("span", "send-hint caps");
  hint.append(el("kbd", "", "Enter"), " send  ", el("kbd", "", "⇧ Enter"), " new line");
  box.append(dot, field, hint);

  const button = el("button", "talk caps");
  button.type = "button";
  button.setAttribute("aria-label", "Hold to talk");
  const label = el("span", "", "Hold to talk");
  button.append(el("span", "dot"), label);
  row.append(box, button);

  const fit = (): void => {
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight}px`;
    box.classList.toggle("has-text", field.value !== "");
  };
  field.addEventListener("input", fit);
  box.addEventListener("mousedown", (ev) => {
    if (ev.target === field) return;
    ev.preventDefault();
    field.focus();
  });

  // Held with the pointer; the field keeps its focus meanwhile.
  button.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    button.setPointerCapture(ev.pointerId);
    button.classList.add("is-held");
    talk.down("pointer");
  });
  const letGo = (): void => {
    button.classList.remove("is-held");
    talk.up("pointer");
  };
  button.addEventListener("pointerup", letGo);
  button.addEventListener("pointercancel", letGo);
  button.addEventListener("lostpointercapture", letGo);
  button.addEventListener("mousedown", (ev) => ev.preventDefault());

  return {
    row,
    field,
    fit,
    setName(name: string): void {
      field.placeholder = name ? `Write to ${name}, or hold Space to talk` : "Write a message, or hold Space to talk";
    },
    setListening(on: boolean): void {
      button.classList.toggle("is-listening", on);
      setText(label, on ? "Listening" : "Hold to talk");
    },
  };
}
