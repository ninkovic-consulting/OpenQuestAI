// Images sent with a message (`/api/images`, `input.text`'s `images`). Mirrors
// the daemon's image routes; the daemon checks every image again.

/** The four kinds of image the daemon takes, told apart by their first bytes. */
export type ImageType = "image/png" | "image/jpeg" | "image/gif" | "image/webp";

export const IMAGE_TYPES: readonly ImageType[] = ["image/png", "image/jpeg", "image/gif", "image/webp"];

/** `GET /api/images/limits`. */
export interface ImageLimits {
  types: string[];
  max_bytes: number;
  max_pixels: number;
  max_per_message: number;
  /** The stored image is scaled so its long edge is at most this. */
  long_edge: number;
}

/** What the window assumes until the daemon has said: the daemon's own defaults. */
export const DEFAULT_LIMITS: ImageLimits = {
  types: [...IMAGE_TYPES],
  max_bytes: 15 * 1024 * 1024,
  max_pixels: 50_000_000,
  max_per_message: 6,
  long_edge: 1568,
};

/** `POST /api/images`: the image as stored, already scaled and stripped of metadata. */
export interface StoredImage {
  id: string;
  media_type: string;
  width: number;
  height: number;
  bytes: number;
}

/** An image as a message carries it in `user.utterance` and `/api/history`. */
export interface ImageRef {
  id: string;
  width: number;
  height: number;
}
