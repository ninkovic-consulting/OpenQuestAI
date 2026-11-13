// What kind of image a file is, from its first bytes. A file's name and its
// declared type can say anything; the magic numbers cannot.

import type { ImageLimits, ImageType } from "./image-types";

/** Enough of the head of a file for every kind below. */
export const SNIFF_BYTES = 12;

const startsWith = (b: Uint8Array, at: number, sig: readonly number[]): boolean => sig.every((v, i) => b[at + i] === v);
const ascii = (s: string): number[] => [...s].map((c) => c.charCodeAt(0));

export function sniffImage(head: Uint8Array): ImageType | null {
  if (startsWith(head, 0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return "image/png";
  if (startsWith(head, 0, [0xff, 0xd8, 0xff])) return "image/jpeg";
  if (startsWith(head, 0, ascii("GIF87a")) || startsWith(head, 0, ascii("GIF89a"))) return "image/gif";
  if (startsWith(head, 0, ascii("RIFF")) && startsWith(head, 8, ascii("WEBP"))) return "image/webp";
  return null;
}

/** The head of a file, read without reading the whole of it. */
export async function headOf(file: Blob): Promise<Uint8Array> {
  return new Uint8Array(await file.slice(0, SNIFF_BYTES).arrayBuffer());
}

const megabytes = (bytes: number): string => `${Math.round((bytes / (1024 * 1024)) * 10) / 10} MB`;

/** Why a file cannot be sent, in the daemon's words, or null when it may be uploaded. */
export function imageRefusal(size: number, head: Uint8Array, limits: Pick<ImageLimits, "types" | "max_bytes">): string | null {
  const kind = sniffImage(head);
  if (kind === null || !limits.types.includes(kind)) return "That file is not a PNG, JPEG, GIF or WebP image.";
  if (size > limits.max_bytes) return `That image is larger than ${megabytes(limits.max_bytes)}.`;
  return null;
}
