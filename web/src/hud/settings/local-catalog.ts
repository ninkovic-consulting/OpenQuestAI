// One model of the catalog as a row: its size and memory first, since that is
// what decides between a 2 GB and a 20 GB download, then what it is good at,
// how it fits this Mac, what it does with tools, and what can be done with it.

import type { CustomModel, LocalDownload, LocalListing, LocalModelRow } from "../../net/brain-types";
import { el } from "../dom";
import { button, confirmButton, downloadRow, statusLine, type Tone } from "./fields";
import { formatBytes } from "./format";
import { deleteBlock, deleteQuestion, finePrint, fitHelp, fitTone, fitWords, inUse, toolsWords } from "./local-words";

/** What a row's buttons do; each answers the line to show afterwards, or null when there is nothing to say. */
export interface RowActions {
  download(repo: string): Promise<void>;
  use(repo: string): Promise<void>;
  remove(repo: string): Promise<string>;
}

/** A dot and a 1px border, small: a mark on a row. */
export function chip(tone: Tone | "mark", text: string, title = ""): HTMLElement {
  const node = el("span", `lm-chip is-${tone}`);
  node.append(el("span", "dot"), el("span", "", text));
  if (title) node.title = title;
  return node;
}

/** What the buttons of a row are about. */
interface Target {
  repo: string;
  title: string;
  /** What is on disk, null when nothing is. */
  bytes: number | null;
  /** What a download takes, when known. */
  size: number | null;
  fit: LocalModelRow["fit"] | null;
  download: LocalDownload;
}

function actions(t: Target, listing: LocalListing, act: RowActions): HTMLElement {
  const { repo, bytes, size, download: d } = t;
  const box = el("div", "row-actions lm-actions");
  if (d.state === "running") return box;
  if (bytes === null) {
    const plain = !(inUse(listing, repo) || listing.recommended === repo) || d.state === "failed";
    const label = d.state === "failed" ? "Try again" : t.fit === "too_big" ? "Download anyway" : size === null ? "Download" : `Download ${formatBytes(size)}`;
    const get = button(label, plain ? "plain" : "primary");
    get.addEventListener("click", () => {
      get.disabled = true;
      void act.download(repo);
    });
    box.append(get);
    return box;
  }
  if (inUse(listing, repo)) box.append(chip("mark", "In use"));
  else {
    const use = button("Use this model", "primary");
    use.addEventListener("click", () => {
      use.disabled = true;
      void act.use(repo);
    });
    box.append(use);
  }
  const blocked = deleteBlock(listing, repo);
  if (blocked) {
    const del = button(`Delete, frees ${formatBytes(bytes)}`);
    del.disabled = true;
    del.title = blocked;
    box.append(del);
  } else {
    box.append(confirmButton(`Delete, frees ${formatBytes(bytes)}`, { question: deleteQuestion(t.title, bytes), confirm: "Delete", danger: true }, () => act.remove(repo)));
  }
  return box;
}

function stateLine(bytes: number | null, d: LocalDownload): HTMLElement | null {
  if (d.state === "running" || d.state === "failed") return downloadRow(d);
  if (bytes !== null) return statusLine("ok", `On this Mac · ${formatBytes(bytes)}`);
  return null;
}

export function catalogRow(row: LocalModelRow, listing: LocalListing, act: RowActions): HTMLElement {
  const using = inUse(listing, row.id);
  const node = el("article", `lm-row${using ? " is-use" : ""}`);
  const size = el("div", "lm-size");
  size.append(el("strong", "", formatBytes(row.size_bytes)), el("span", "caps", "to download"), el("strong", "lm-memory", `${row.memory_gb} GB`), el("span", "caps", "memory"));

  const head = el("div", "lm-head");
  head.append(el("h5", "", row.title));
  if (listing.recommended === row.id) head.append(chip("mark", "Recommended for this Mac"));
  if (using) head.append(chip("mark", "In use"));

  const marks = el("div", "lm-marks");
  marks.append(
    chip(fitTone(row.fit), fitWords(row.fit), fitHelp(row.fit)),
    chip(row.tools_recommended ? "ok" : "idle", toolsWords(row)),
  );
  if (row.kind === "code") marks.append(chip("idle", "Made for code"));

  const main = el("div", "lm-main");
  main.append(head, el("p", "lm-good", row.good_at), marks, el("p", "lm-fine", finePrint(row)));
  const state = stateLine(row.on_disk_bytes, row.download);
  if (state) main.append(state);
  main.append(actions({ repo: row.id, title: row.title, bytes: row.on_disk_bytes, size: row.size_bytes, fit: row.fit, download: row.download }, listing, act));
  node.append(size, main);
  return node;
}

/** The chosen model when the catalog does not list it (typed by hand). */
export function customRow(model: CustomModel, listing: LocalListing, act: RowActions): HTMLElement {
  const using = inUse(listing, model.id);
  const node = el("article", `lm-row${using ? " is-use" : ""}`);
  const size = el("div", "lm-size");
  size.append(el("strong", "", model.on_disk_bytes === null ? "?" : formatBytes(model.on_disk_bytes)), el("span", "caps", model.on_disk_bytes === null ? "not downloaded" : "on disk"));
  const head = el("div", "lm-head");
  head.append(el("h5", "", model.id), chip("idle", "Not in the catalog"));
  if (using) head.append(chip("mark", "In use"));
  const main = el("div", "lm-main");
  main.append(head);
  const state = stateLine(model.on_disk_bytes, model.download);
  if (state) main.append(state);
  main.append(actions({ repo: model.id, title: model.id, bytes: model.on_disk_bytes, size: model.download.total_bytes, fit: null, download: model.download }, listing, act));
  node.append(size, main);
  return node;
}
