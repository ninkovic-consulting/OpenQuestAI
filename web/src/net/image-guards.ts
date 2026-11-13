// Narrowing the image routes' JSON, and the images a turn carries, to their
// types. The daemon names an image by 32 lowercase hex characters.

import type { ImageLimits, ImageRef, StoredImage } from "./image-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isSize = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v > 0;

const ID = /^[0-9a-f]{32}$/;

export const isImageId = (v: unknown): v is string => typeof v === "string" && ID.test(v);

export function asImageLimits(v: unknown): ImageLimits | null {
  if (!isObj(v) || !isObj(v["limits"])) return null;
  const l = v["limits"];
  const ok =
    Array.isArray(l["types"]) &&
    l["types"].every((t) => typeof t === "string") &&
    isSize(l["max_bytes"]) &&
    isSize(l["max_pixels"]) &&
    isSize(l["max_per_message"]) &&
    isSize(l["long_edge"]);
  return ok ? (l as unknown as ImageLimits) : null;
}

export function asStoredImage(v: unknown): StoredImage | null {
  if (!isObj(v) || !isObj(v["image"])) return null;
  const i = v["image"];
  const ok = isImageId(i["id"]) && typeof i["media_type"] === "string" && isSize(i["width"]) && isSize(i["height"]) && isSize(i["bytes"]);
  return ok ? { id: i["id"] as string, media_type: i["media_type"] as string, width: i["width"] as number, height: i["height"] as number, bytes: i["bytes"] as number } : null;
}

function asRef(v: unknown): ImageRef | null {
  if (!isObj(v) || !isImageId(v["id"]) || !isSize(v["width"]) || !isSize(v["height"])) return null;
  return { id: v["id"], width: v["width"], height: v["height"] };
}

/** The images of a turn; missing (an older daemon) is none, and a malformed one is left out. */
export function asImageRefs(v: unknown): ImageRef[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((r) => {
    const ref = asRef(r);
    return ref ? [ref] : [];
  });
}
