// A download's state with a Download button, polling `GET /api/downloads`
// once a second while it runs. Polling stops when the control leaves the page.

import type { SettingsApi } from "../../net/settings-api";
import type { Download, DownloadWhat } from "../../net/settings-types";
import { el } from "../dom";
import { button, downloadRow } from "./fields";

const POLL_MS = 1000;

export function downloadControl(api: SettingsApi, what: DownloadWhat, onDone: () => void = () => {}): HTMLElement {
  const root = el("div", "download-control");
  const start = button("Download", "primary");
  const message = el("p", "field-error");
  message.hidden = true;
  let shown: Download | null = null;

  const draw = (d: Download): void => {
    const finished = shown?.state === "running" && d.state === "done";
    shown = d;
    start.hidden = d.state === "done" || d.state === "running";
    start.textContent = d.state === "failed" ? "Try again" : "Download";
    root.replaceChildren(downloadRow(d), start, message);
    if (finished) onDone();
    if (d.state === "running") setTimeout(poll, POLL_MS);
  };
  const fail = (text: string): void => {
    message.textContent = text;
    message.hidden = false;
  };
  const poll = (): void => {
    if (!root.isConnected) return;
    void api.downloads().then((r) => (r.ok ? draw(r.value[what]) : fail(r.message)));
  };
  start.addEventListener("click", () => {
    start.disabled = true;
    message.hidden = true;
    void api.startDownload(what).then((r) => {
      start.disabled = false;
      if (r.ok) draw(r.value[what]);
      else fail(r.message);
    });
  });
  root.append(el("p", "field-note", "Checking…"));
  void api.downloads().then((r) => (r.ok ? draw(r.value[what]) : fail(r.message)));
  return root;
}
