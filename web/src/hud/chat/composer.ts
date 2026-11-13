// The message field, always at the bottom of the scene, and the hold-to-talk
// control beside it. The field grows with Shift+Enter up to a few lines and
// never blocks: while the assistant answers it takes the next message (which
// waits), its hint says so, and a Stop control sits beside it.

import { el, setText } from "../dom";
import { sendHints } from "./queue";
import type { Talk } from "./talk";

export interface Composer {
  row: HTMLElement;
  /** The bordered box around the field; attach.ts adds the images waiting to go, and their control. */
  box: HTMLElement;
  field: HTMLTextAreaElement;
  /** Re-measure after the text changed from code. */
  fit(): void;
  /** The field's prompt (`listen.ts`, `fieldPrompt`). */
  setPrompt(text: string): void;
  /** The hold-to-talk control's words (`listen.ts`, `talkLabel`), and whether it shows listening. */
  setTalk(label: string, listening: boolean): void;
  /** Whether Enter queues (`queue.ts`, `queues`) and whether Stop shows (the assistant answers). */
  setBusy(queues: boolean, answering: boolean): void;
}

/** `stop` interrupts the answer; the Stop control shows only while there is one. */
export function makeComposer(talk: Talk, stop: () => void): Composer {
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
  let hintFor: boolean | null = null;
  const showHint = (busy: boolean): void => {
    if (busy === hintFor) return;
    hintFor = busy;
    // In the box, where the draft needs the room, the short form; the hint bar says it in full.
    const pairs = busy ? ([["Enter", "queue"], ["⌘ Enter", "now"]] as const) : [...sendHints(false), ["⇧ Enter", "new line"] as const];
    hint.replaceChildren(...pairs.flatMap(([key, what], i) => [el("kbd", "", key), ` ${what}${i < pairs.length - 1 ? "  " : ""}`]));
  };
  showHint(false);
  box.append(dot, field, hint);

  const halt = el("button", "stop-reply caps");
  halt.type = "button";
  halt.title = "Stop the reply (Esc)";
  halt.setAttribute("aria-label", "Stop the reply");
  halt.append(el("span", "dot"), "Stop");
  halt.hidden = true;
  halt.addEventListener("mousedown", (ev) => ev.preventDefault());
  halt.addEventListener("click", stop);

  const button = el("button", "talk caps");
  button.type = "button";
  button.setAttribute("aria-label", "Hold to talk");
  const label = el("span", "", "Hold to talk");
  button.append(el("span", "dot"), label);
  row.append(box, halt, button);

  const fit = (): void => {
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight}px`;
    box.classList.toggle("has-text", field.value !== "");
  };
  field.addEventListener("input", fit);
  box.addEventListener("mousedown", (ev) => {
    if (ev.target === field || (ev.target instanceof Element && ev.target.closest("button"))) return;
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
    box,
    field,
    fit,
    setPrompt(text: string): void {
      field.placeholder = text;
    },
    setTalk(text: string, listening: boolean): void {
      button.classList.toggle("is-listening", listening);
      setText(label, text);
    },
    setBusy(queues: boolean, answering: boolean): void {
      showHint(queues);
      halt.hidden = !answering;
      box.classList.toggle("is-queueing", queues);
    },
  };
}
