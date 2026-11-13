// Images in the message field: pasted, dropped on the window (the house only)
// or chosen with the Image control. Each is checked here, uploaded at once,
// and waits above the field as a thumbnail with a remove button until Enter
// sends it with the text. A refusal shows in the box, in the alert colour,
// until something works. The rules are in tray.ts; this file is the page.

import { headOf } from "../../net/image-sniff";
import type { ImageRef } from "../../net/image-types";
import type { ImageSource } from "../../net/image-source";
import type { Store } from "../../net/store";
import { el, setText } from "../dom";
import type { Composer } from "./composer";
import { OVERLAYS } from "./keys";
import { BLOCKED, emptyTray, failed, imagesBlocked, offer, refuse, removeImage, removeLabel, type Tray, uploaded, readyToSend } from "./tray";

export interface Attach {
  /** What goes with the text on Enter, or null when nothing may be sent now (the line says why). */
  take(text: string): ImageRef[] | null;
  /** The message went: the tray empties and the line clears. */
  sent(): void;
}

const ACCEPT = "image/png,image/jpeg,image/gif,image/webp";

/** A small picture frame: the attach control's mark. */
function icon(): SVGSVGElement {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const frame = document.createElementNS(ns, "rect");
  for (const [k, v] of Object.entries({ x: "1.5", y: "2.5", width: "13", height: "11" })) frame.setAttribute(k, v);
  const hill = document.createElementNS(ns, "path");
  hill.setAttribute("d", "M1.5 11.5 L6 7.5 L9.5 10.5 L11.5 9 L14.5 11.5");
  const sun = document.createElementNS(ns, "circle");
  for (const [k, v] of Object.entries({ cx: "11", cy: "5.8", r: "1.2" })) sun.setAttribute(k, v);
  svg.append(frame, hill, sun);
  return svg;
}

/** `drop`: the whole window takes dropped images while the chat is in front (the house). */
export function mountAttach(composer: Composer, store: Store, source: ImageSource, drop = false): Attach {
  const { box, field } = composer;
  const trayEl = el("div", "attach-tray");
  trayEl.setAttribute("role", "list");
  trayEl.setAttribute("aria-label", "Images to send");
  const button = el("button", "attach caps");
  button.type = "button";
  button.append(icon(), el("span", "", "Image"));
  const picker = el("input", "attach-input");
  picker.type = "file";
  picker.accept = ACCEPT;
  picker.multiple = true;
  picker.tabIndex = -1;
  picker.setAttribute("aria-hidden", "true");
  const line = el("p", "attach-refusal");
  line.setAttribute("role", "status");
  const lineText = el("span");
  line.append(el("span", "dot"), lineText);
  box.prepend(trayEl);
  box.append(button, picker, line);

  let tray: Tray = emptyTray();
  /** The local file's picture, shown while it uploads and after. */
  const previews = new Map<number, string>();

  const blocked = (): boolean => imagesBlocked(store.get().mode);

  const forget = (key: number): void => {
    const url = previews.get(key);
    if (url) URL.revokeObjectURL(url);
    previews.delete(key);
  };

  const showBlocked = (): void => {
    const off = blocked();
    button.classList.toggle("is-off", off);
    button.setAttribute("aria-disabled", String(off));
    button.title = off ? BLOCKED : "Add images to send with the message";
    if (off) button.setAttribute("aria-description", BLOCKED);
    else button.removeAttribute("aria-description");
  };

  const render = (): void => {
    const n = tray.items.length;
    const focused = document.activeElement instanceof HTMLElement && trayEl.contains(document.activeElement) ? document.activeElement : null;
    const focusedAt = focused ? [...trayEl.querySelectorAll("button")].indexOf(focused as HTMLButtonElement) : -1;
    trayEl.replaceChildren(
      ...tray.items.map((w, i) => {
        const item = el("div", "tray-item");
        item.setAttribute("role", "listitem");
        item.dataset["state"] = w.state;
        const img = el("img");
        img.alt = `Image ${i + 1} of ${n} to send${w.state === "pending" ? ", uploading" : ""}`;
        img.src = previews.get(w.key) ?? "";
        const remove = el("button", "tray-remove", "×");
        remove.type = "button";
        remove.setAttribute("aria-label", removeLabel(i, n));
        remove.title = removeLabel(i, n);
        remove.addEventListener("click", () => takeOut(w.key));
        item.append(img, el("span", "dot"), remove);
        return item;
      }),
    );
    trayEl.hidden = n === 0;
    box.classList.toggle("has-images", n > 0);
    setText(lineText, tray.refusal ?? "");
    line.hidden = tray.refusal === null;
    box.classList.toggle("has-refusal", tray.refusal !== null);
    // Focus stays in the tray after a removal: on the button now in that place, else the field.
    if (focusedAt !== -1 && !trayEl.contains(document.activeElement)) {
      const buttons = trayEl.querySelectorAll("button");
      (buttons[Math.min(focusedAt, buttons.length - 1)] ?? field).focus();
    }
  };

  const takeOut = (key: number): void => {
    const was = tray.items.find((w) => w.key === key);
    tray = removeImage(tray, key);
    forget(key);
    if (was?.image) void source.api.remove(was.image.id);
    render();
  };

  const upload = async (key: number, file: File): Promise<void> => {
    const answer = await source.api.upload(file);
    if (answer.ok) {
      const image = { id: answer.value.id, width: answer.value.width, height: answer.value.height };
      const before = tray;
      tray = uploaded(tray, key, image);
      // Taken out while it uploaded: the daemon forgets it too.
      if (tray === before) void source.api.remove(image.id);
    } else {
      tray = failed(tray, key, answer.message);
      forget(key);
    }
    render();
  };

  const offerFiles = async (files: File[]): Promise<void> => {
    if (files.length === 0) return;
    const [limits, offered] = await Promise.all([source.limits(), Promise.all(files.map(async (f) => ({ size: f.size, head: await headOf(f) })))]);
    const r = offer(tray, offered, limits, blocked());
    tray = r.tray;
    for (const { index, key } of r.taken) {
      const file = files[index];
      if (!file) continue;
      previews.set(key, URL.createObjectURL(file));
      void upload(key, file);
    }
    render();
  };

  button.addEventListener("click", () => {
    if (blocked()) {
      tray = refuse(tray, BLOCKED);
      return render();
    }
    picker.click();
  });
  picker.addEventListener("change", () => {
    const files = [...(picker.files ?? [])];
    picker.value = "";
    field.focus();
    void offerFiles(files);
  });
  field.addEventListener("paste", (ev) => {
    const files = [...(ev.clipboardData?.files ?? [])];
    if (files.length === 0) return;
    ev.preventDefault();
    void offerFiles(files);
  });

  if (drop) mountDrop(box, () => blocked(), offerFiles);

  showBlocked();
  store.subscribe((s, prev) => {
    if (s.mode !== prev.mode) showBlocked();
  });
  render();

  return {
    take(text: string): ImageRef[] | null {
      const r = readyToSend(tray, text, blocked());
      if (r.ok) return r.images;
      if (r.why !== null) {
        tray = refuse(tray, r.why);
        render();
      }
      return null;
    },
    sent(): void {
      for (const key of [...previews.keys()]) forget(key);
      tray = { ...emptyTray(), nextKey: tray.nextKey };
      render();
    },
  };
}

/** The whole window as a drop target while the chat is in front, with a veil that says so. */
function mountDrop(box: HTMLElement, blocked: () => boolean, take: (files: File[]) => Promise<void>): void {
  const veil = el("div", "drop-veil");
  veil.hidden = true;
  const words = el("p", "drop-words caps");
  veil.append(words);
  document.body.append(veil);
  let depth = 0;

  const carriesFiles = (ev: DragEvent): boolean => ev.dataTransfer?.types.includes("Files") ?? false;
  // Settings, the Jobs panel, the wizard or the build form in front: the chat is not.
  const available = (): boolean => document.querySelector(OVERLAYS) === null;
  const show = (on: boolean): void => {
    veil.hidden = !on;
    box.classList.toggle("is-drop", on);
    const off = blocked();
    veil.classList.toggle("is-off", off);
    setText(words, off ? BLOCKED : "Drop images to send with your message");
  };

  window.addEventListener("dragenter", (ev) => {
    if (!carriesFiles(ev) || !available()) return;
    ev.preventDefault();
    depth += 1;
    show(true);
  });
  window.addEventListener("dragover", (ev) => {
    if (!carriesFiles(ev)) return;
    // A file let go anywhere else would replace the page; it goes nowhere instead.
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = available() ? "copy" : "none";
  });
  window.addEventListener("dragleave", (ev) => {
    if (!carriesFiles(ev) || depth === 0) return;
    depth -= 1;
    if (depth === 0) show(false);
  });
  window.addEventListener("drop", (ev) => {
    if (!carriesFiles(ev)) return;
    const handled = ev.defaultPrevented;
    ev.preventDefault();
    depth = 0;
    show(false);
    if (handled || !available()) return;
    void take([...(ev.dataTransfer?.files ?? [])]);
  });
}
