// Mock mode's images: the daemon's checks and refusals, its 32-hex ids, and
// the bytes kept as blobs so they can be fetched back. Two small sketches are
// drawn on a canvas for an earlier turn of the conversation.

import { DEFAULT_LIMITS, type ImageLimits, type ImageRef, type StoredImage } from "./image-types";
import { headOf, imageRefusal, sniffImage } from "./image-sniff";
import type { ImagesApi } from "./images-api";
import { ok, refused, type Result } from "./settings-api";

const hex = (bytes: Uint8Array): string => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
const newId = (): string => hex(crypto.getRandomValues(new Uint8Array(16)));

/** The size the daemon stores: the long edge brought down to the limit, never up. */
export function scaledSize(width: number, height: number, longEdge: number): { width: number; height: number } {
  const s = Math.min(1, longEdge / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * s)), height: Math.max(1, Math.round(height * s)) };
}

async function measure(file: Blob): Promise<{ width: number; height: number } | null> {
  try {
    const bitmap = await createImageBitmap(file);
    const size = { width: bitmap.width, height: bitmap.height };
    bitmap.close();
    return size;
  } catch {
    return null;
  }
}

/** A small sketch in the house's colours, as a PNG. */
function sketch(width: number, height: number, draw: (g: CanvasRenderingContext2D) => void): Promise<Blob | null> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const g = canvas.getContext("2d");
  if (!g) return Promise.resolve(null);
  g.fillStyle = "#2a1712";
  g.fillRect(0, 0, width, height);
  g.strokeStyle = "#e2a62b";
  g.fillStyle = "#e2a62b";
  g.lineWidth = 3;
  draw(g);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

/** A workbench seen from the side. */
const workbench = (g: CanvasRenderingContext2D): void => {
  g.strokeRect(60, 110, 360, 26);
  for (const x of [80, 380]) g.strokeRect(x, 136, 20, 130);
  g.strokeRect(150, 70, 70, 40);
  g.beginPath();
  g.arc(320, 92, 18, 0, Math.PI * 2);
  g.stroke();
  g.fillStyle = "#a8957c";
  g.font = "16px sans-serif";
  g.fillText("bench · 1.8 m", 60, 300);
};

/** The house's ground floor, from above. */
const floorPlan = (g: CanvasRenderingContext2D): void => {
  g.strokeRect(30, 30, 260, 340);
  g.beginPath();
  g.moveTo(30, 190);
  g.lineTo(290, 190);
  g.moveTo(160, 190);
  g.lineTo(160, 370);
  g.stroke();
  g.fillRect(200, 260, 50, 24);
  g.fillStyle = "#a8957c";
  g.font = "15px sans-serif";
  g.fillText("Hall", 130, 115);
  g.fillText("Workshop", 180, 240);
  g.fillText("Library", 55, 280);
};

export class MockImages implements ImagesApi {
  private readonly stored = new Map<string, { blob: Blob; ref: ImageRef }>();
  private seeded: Promise<ImageRef[]> | null = null;

  limits(): Promise<Result<ImageLimits>> {
    return Promise.resolve(ok(structuredClone(DEFAULT_LIMITS)));
  }

  async upload(file: Blob): Promise<Result<StoredImage>> {
    const head = await headOf(file);
    const why = imageRefusal(file.size, head, DEFAULT_LIMITS);
    if (why !== null) return refused(why);
    const size = await measure(file);
    if (size === null) return refused("That image could not be read.");
    if (size.width * size.height > DEFAULT_LIMITS.max_pixels) return refused("That image has more than 50 megapixels.");
    const ref = { id: newId(), ...scaledSize(size.width, size.height, DEFAULT_LIMITS.long_edge) };
    this.stored.set(ref.id, { blob: file, ref });
    return ok({ ...ref, media_type: sniffImage(head) ?? "image/png", bytes: file.size });
  }

  get(id: string): Promise<Result<Blob | null>> {
    return Promise.resolve(ok(this.stored.get(id)?.blob ?? null));
  }

  remove(id: string): Promise<Result<true>> {
    if (!this.stored.delete(id)) return Promise.resolve(refused("There is no such image."));
    return Promise.resolve(ok(true));
  }

  /** The images a message names, or null when one of them is no longer here. */
  refs(ids: readonly string[]): ImageRef[] | null {
    const refs = ids.map((id) => this.stored.get(id)?.ref);
    return refs.every((r): r is ImageRef => r !== undefined) ? refs : null;
  }

  /** The two sketches of the earlier turn, drawn once. */
  sketches(): Promise<ImageRef[]> {
    this.seeded ??= Promise.all([sketch(480, 320, workbench), sketch(320, 400, floorPlan)]).then((blobs) =>
      blobs.flatMap((blob, i) => {
        if (!blob) return [];
        const ref = { id: newId(), width: i === 0 ? 480 : 320, height: i === 0 ? 320 : 400 };
        this.stored.set(ref.id, { blob, ref });
        return [ref];
      }),
    );
    return this.seeded;
  }
}
