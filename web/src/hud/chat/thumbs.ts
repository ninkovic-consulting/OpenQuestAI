// The owner's images in the thread: one row of thumbnails under their words,
// each a button that opens the image larger over the window. Each keeps the
// image's shape while it loads, so nothing jumps; one the daemon no longer
// has is a quiet "Image removed" of the same size.

import type { ImageRef } from "../../net/image-types";
import type { ImageSource } from "../../net/image-source";
import { el } from "../dom";

/** Alt text for an image the owner sent: "Image you sent, 1 of 3". */
export const sentAlt = (index: number, count: number): string => `Image you sent, ${index + 1} of ${count}`;

/** The mark beside the owner's words: "1 image", "3 images"; empty for none. */
export function imageMark(count: number): string {
  if (count === 0) return "";
  return count === 1 ? "1 image" : `${count} images`;
}

/** The thumbnails' alt texts, in order, as the thread shows them. */
export const thumbAlts = (images: readonly ImageRef[]): string[] => images.map((_, i) => sentAlt(i, images.length));

export interface ThumbRow {
  root: HTMLElement;
  /** The row left the page: its images are given back. */
  dispose(): void;
}

function shaped(node: HTMLElement, ref: ImageRef): void {
  node.style.aspectRatio = `${ref.width} / ${ref.height}`;
}

function gone(ref: ImageRef): HTMLElement {
  const box = el("div", "thumb is-gone caps", "Image removed");
  shaped(box, ref);
  return box;
}

export function thumbRow(images: readonly ImageRef[], source: Promise<ImageSource>): ThumbRow {
  const root = el("div", "thumbs");
  const alts = thumbAlts(images);
  let taken: { src: ImageSource; ids: string[] } | null = null;
  let live = true;
  const buttons = images.map((ref, i) => {
    const b = el("button", "thumb is-loading");
    b.type = "button";
    shaped(b, ref);
    const img = el("img");
    img.alt = alts[i] ?? "";
    img.decoding = "async";
    b.append(img);
    b.addEventListener("click", () => {
      void source.then((src) => openLightbox(images, i, src, b));
    });
    return b;
  });
  root.append(...buttons);
  void source.then((src) => {
    if (!live) return;
    taken = { src, ids: images.map((r) => r.id) };
    images.forEach((ref, i) => {
      const b = buttons[i];
      if (!b) return;
      void src.take(ref.id).then((url) => {
        if (!live) return;
        if (url === null) return b.replaceWith(gone(ref));
        const img = b.querySelector("img");
        if (img) img.src = url;
        b.classList.remove("is-loading");
      });
    });
  });
  return {
    root,
    dispose(): void {
      live = false;
      if (taken) for (const id of taken.ids) taken.src.give(id);
    },
  };
}

/**
 * One image large over the window. Escape, the close button or a click beside
 * the image closes it, and focus goes back to the thumbnail it came from.
 */
export function openLightbox(images: readonly ImageRef[], index: number, source: ImageSource, from: HTMLElement): void {
  const ref = images[index];
  if (!ref) return;
  const alt = sentAlt(index, images.length);
  const veil = el("div", "lightbox");
  veil.setAttribute("role", "dialog");
  veil.setAttribute("aria-modal", "true");
  veil.setAttribute("aria-label", alt);
  const figure = el("figure", "lightbox-figure");
  const frame = el("div", "lightbox-frame is-loading");
  frame.style.aspectRatio = `${ref.width} / ${ref.height}`;
  frame.style.setProperty("--w", `${ref.width}px`);
  frame.style.setProperty("--ar", (ref.width / ref.height).toFixed(4));
  const img = el("img");
  img.alt = alt;
  frame.append(img);
  const caption = el("figcaption", "lightbox-caption caps");
  caption.append(el("span", "", images.length > 1 ? `Image ${index + 1} of ${images.length}` : "Image you sent"));
  const close = el("button", "lightbox-close caps", "Close");
  close.type = "button";
  caption.append(close);
  figure.append(frame, caption);
  veil.append(figure);
  document.body.append(veil);

  let open = true;
  void source.take(ref.id).then((url) => {
    if (!open) return;
    frame.classList.remove("is-loading");
    if (url === null) frame.replaceChildren(el("span", "caps", "Image removed"));
    else img.src = url;
  });
  const shut = (): void => {
    if (!open) return;
    open = false;
    veil.remove();
    source.give(ref.id);
    from.focus();
  };
  close.addEventListener("click", shut);
  veil.addEventListener("click", (ev) => {
    if (ev.target === veil || ev.target === figure) shut();
  });
  veil.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      shut();
    } else if (ev.key === "Tab") {
      // The close button is the only stop inside; focus stays with it.
      ev.preventDefault();
      close.focus();
    }
  });
  close.focus();
}
