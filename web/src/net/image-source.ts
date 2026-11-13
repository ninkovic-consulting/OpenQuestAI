// The images the window shows, fetched once each with the token and handed
// out as object URLs. Each user takes a URL and gives it back; the last one
// to give it back frees it. The daemon's limits are asked for once.

import { DEFAULT_LIMITS, type ImageLimits } from "./image-types";
import type { ImagesApi } from "./images-api";

interface Held {
  url: Promise<string | null>;
  users: number;
}

export class ImageSource {
  private readonly held = new Map<string, Held>();
  private known: Promise<ImageLimits> | null = null;

  constructor(readonly api: ImagesApi) {}

  /** The daemon's limits; its defaults while it cannot be asked. */
  limits(): Promise<ImageLimits> {
    this.known ??= this.api.limits().then((r) => (r.ok ? r.value : DEFAULT_LIMITS));
    return this.known;
  }

  /** An object URL for the image, or null when the daemon no longer has it. */
  take(id: string): Promise<string | null> {
    let h = this.held.get(id);
    if (!h) {
      const url = this.api.get(id).then((r) => (r.ok && r.value ? URL.createObjectURL(r.value) : null));
      h = { url, users: 0 };
      this.held.set(id, h);
    }
    h.users += 1;
    return h.url;
  }

  /** The element that showed it has gone. */
  give(id: string): void {
    const h = this.held.get(id);
    if (!h) return;
    h.users -= 1;
    if (h.users > 0) return;
    this.held.delete(id);
    void h.url.then((url) => {
      if (url) URL.revokeObjectURL(url);
    });
  }
}

const sources = new WeakMap<ImagesApi, ImageSource>();

/** One source per daemon client, shared by the thread, the field and the widget. */
export function imageSource(api: ImagesApi): ImageSource {
  let s = sources.get(api);
  if (!s) {
    s = new ImageSource(api);
    sources.set(api, s);
  }
  return s;
}
