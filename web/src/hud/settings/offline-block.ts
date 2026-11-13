// Offline mode: a switch, what it means, the model loading or in memory while
// it is on, and, when the daemon refuses to turn it on, why, with the download
// that fixes it when the model is missing.

import type { LocalDownload } from "../../net/brain-types";
import { el } from "../dom";
import { button, downloadRow, statusLine } from "./fields";
import { formatBytes } from "./format";
import type { LoadLine } from "./local-load";

export interface OfflineProps {
  on: boolean;
  busy: boolean;
  /** The model that answers offline, by name. */
  model: string;
  /** Whether it can use tools; null until known. */
  tools: boolean | null;
  /** The model loading, reading or in memory; null for a model on a server. */
  load: LoadLine | null;
  /** The daemon's refusal to turn it on. */
  refusal: string | null;
  /** Set when the refusal is for want of the model: what to download. */
  offer: { download: LocalDownload; size: number | null } | null;
  /** A line after the download finished. */
  ready: string | null;
}

export interface OfflineActions {
  toggle(on: boolean): void;
  download(): void;
}

const OFFLINE_MEANING = [
  "Everything runs on the local model on this Mac, and nothing is sent to Anthropic. Web search and loading pages do not work.",
  "A small model mostly talks; a larger one can also use tools and take jobs.",
];

/** A switch, here and in the left panel: a track and a thumb in a button. */
export function switchButton(label: string, on: boolean, small = false): HTMLButtonElement {
  const b = el("button", `switch${small ? " is-small" : ""}`);
  b.type = "button";
  b.setAttribute("role", "switch");
  b.setAttribute("aria-checked", String(on));
  b.setAttribute("aria-label", label);
  b.append(el("span", "switch-thumb"));
  return b;
}

export function offlineBlock(p: OfflineProps, act: OfflineActions): HTMLElement[] {
  const head = el("div", "offline-head");
  const toggle = switchButton("Offline mode", p.on);
  toggle.disabled = p.busy;
  toggle.addEventListener("click", () => act.toggle(!p.on));
  const words = el("div", "offline-words");
  words.append(el("strong", "offline-title", p.on ? "Offline mode is on" : "Offline mode is off"), ...OFFLINE_MEANING.map((t) => el("p", "field-note", t)));
  head.append(toggle, words);
  const parts: HTMLElement[] = [head];
  if (p.on) parts.push(statusLine("ok", `${p.model} answers, on this Mac.`));
  if (p.on && p.load) parts.push(statusLine(p.load.tone, p.load.text));
  if (p.on && p.tools === false) parts.push(statusLine("warn", "This model cannot use tools, so the agents cannot take jobs offline. Choose a larger one below if you want them to."));
  if (p.refusal) {
    const why = statusLine("bad", p.refusal);
    why.setAttribute("role", "alert");
    parts.push(why);
  }
  if (p.offer) {
    const offer = el("div", "offline-offer");
    if (p.offer.download.state === "running") offer.append(downloadRow(p.offer.download));
    else {
      const get = button(`Download ${p.model}${p.offer.size === null ? "" : `, ${formatBytes(p.offer.size)}`}`, "primary");
      get.addEventListener("click", () => {
        get.disabled = true;
        act.download();
      });
      offer.append(get);
      if (p.offer.download.state === "failed") offer.append(downloadRow(p.offer.download));
    }
    parts.push(offer);
  }
  if (p.ready) parts.push(statusLine("ok", p.ready));
  return parts;
}
