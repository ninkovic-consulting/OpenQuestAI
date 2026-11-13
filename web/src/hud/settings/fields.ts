// Small DOM pieces the settings groups and the wizard share: labelled fields
// with their notes and errors, segmented choices, status lines, buttons,
// inline confirmations and download rows.

import type { Download } from "../../net/settings-types";
import { el } from "../dom";
import { downloadShare, formatDownload } from "./format";

export type Tone = "ok" | "warn" | "bad" | "idle";

export function button(label: string, kind: "primary" | "plain" | "danger" = "plain"): HTMLButtonElement {
  const b = el("button", `btn caps${kind === "plain" ? "" : ` is-${kind}`}`, label);
  b.type = "button";
  return b;
}

/** A small dot and a line of text, coloured by tone. */
export function statusLine(tone: Tone, text: string): HTMLElement {
  const node = el("div", `status is-${tone}`);
  node.append(el("span", tone === "idle" ? "dot hollow" : "dot"), el("span", "", text));
  return node;
}

export interface FieldOptions {
  note?: string;
  /** Marks a value that only a restart applies. */
  restart?: boolean;
  error?: string | undefined;
}

/** A label, the control, a note, and room for an error, all in one row. */
export function fieldRow(label: string, control: HTMLElement, opts: FieldOptions = {}): HTMLElement {
  const row = el("div", "field");
  const head = el("div", "field-head");
  const name = el("label", "caps", label);
  const target = control.matches("input, select, textarea") ? control : control.querySelector("input, select, textarea");
  if (target) {
    target.id ||= `f-${Math.random().toString(36).slice(2, 9)}`;
    name.htmlFor = target.id;
  }
  head.append(name);
  if (opts.restart) head.append(el("span", "tag restart-tag", "after a restart"));
  row.append(head, control);
  if (opts.note) row.append(el("p", "field-note", opts.note));
  const error = el("p", "field-error", opts.error ?? "");
  error.setAttribute("role", "alert");
  error.hidden = !opts.error;
  row.append(error);
  return row;
}

/** A titled part of a group. */
export function block(title: string, ...children: HTMLElement[]): HTMLElement {
  const node = el("section", "block");
  node.append(el("h4", "caps", title), ...children);
  return node;
}

export interface Segment {
  value: string;
  label: string;
  /** A choice that cannot be picked, with the reason shown beside it. */
  locked?: string;
}

/** A row of mutually exclusive choices. */
export function segmented(label: string, segments: readonly Segment[], value: string, onChange: (value: string) => void): HTMLElement {
  const group = el("div", "segmented");
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-label", label);
  const buttons = segments.map((s) => {
    const b = el("button", "segment caps", s.label);
    b.type = "button";
    b.setAttribute("role", "radio");
    if (s.locked) {
      b.disabled = true;
      b.title = s.locked;
      b.classList.add("is-locked");
    }
    b.addEventListener("click", () => {
      select(s.value);
      onChange(s.value);
    });
    return b;
  });
  const select = (v: string): void => {
    segments.forEach((s, i) => buttons[i]?.setAttribute("aria-checked", String(s.value === v)));
  };
  select(value);
  group.append(...buttons);
  return group;
}

export interface ConfirmOptions {
  question: string;
  confirm: string;
  danger?: boolean;
  /** Text that must be typed before the confirm button works, e.g. the assistant's name. */
  typed?: string;
  /** Extra controls shown with the question (a checkbox, say). */
  extra?: HTMLElement;
}

/**
 * A button that, when pressed, turns into a question with Confirm and Cancel
 * in its place. `run` answers the line shown afterwards.
 */
export function confirmButton(label: string, opts: ConfirmOptions, run: () => Promise<string>): HTMLElement {
  const root = el("div", "confirm");
  const start = button(label, opts.danger ? "danger" : "plain");
  const result = el("p", "field-note confirm-result");
  result.setAttribute("role", "status");
  root.append(start, result);

  const ask = (): void => {
    const box = el("div", "confirm-box");
    box.append(el("p", "confirm-question", opts.question));
    if (opts.extra) box.append(opts.extra);
    const yes = button(opts.confirm, opts.danger ? "danger" : "primary");
    const no = button("Cancel");
    let typed: HTMLInputElement | null = null;
    if (opts.typed !== undefined) {
      const want = opts.typed;
      typed = el("input");
      typed.autocomplete = "off";
      typed.spellcheck = false;
      typed.placeholder = want;
      yes.disabled = true;
      typed.addEventListener("input", () => {
        yes.disabled = typed?.value.trim() !== want;
      });
      box.append(fieldRow(`Type ${want} to confirm`, typed));
    }
    const actions = el("div", "row-actions");
    actions.append(yes, no);
    box.append(actions);
    root.replaceChildren(box, result);
    (typed ?? yes).focus();
    no.addEventListener("click", () => {
      root.replaceChildren(start, result);
      start.focus();
    });
    yes.addEventListener("click", () => {
      yes.disabled = no.disabled = true;
      result.textContent = "Working…";
      void run().then((text) => {
        result.textContent = text;
        root.replaceChildren(start, result);
      });
    });
  };
  start.addEventListener("click", ask);
  return root;
}

/** A download's state and a thin progress bar. */
export function downloadRow(d: Download): HTMLElement {
  const row = el("div", `download is-${d.state}`);
  const tone: Tone = d.state === "done" ? "ok" : d.state === "failed" ? "bad" : d.state === "running" ? "warn" : "idle";
  row.append(statusLine(tone, formatDownload(d)));
  const share = downloadShare(d);
  if (d.state === "running") {
    const bar = el("div", "progress");
    const fill = el("span");
    fill.style.width = `${((share ?? 0) * 100).toFixed(1)}%`;
    bar.append(fill);
    row.append(bar);
  }
  return row;
}

/** A note line that can be filled later. */
export function note(text = ""): HTMLParagraphElement {
  const p = el("p", "field-note", text);
  p.setAttribute("role", "status");
  return p;
}
