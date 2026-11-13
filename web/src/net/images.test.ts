import { describe, expect, it } from "vitest";
import { asBrainMode } from "./brain-guards";
import { asImageLimits, asImageRefs, asStoredImage, isImageId } from "./image-guards";
import { DEFAULT_LIMITS } from "./image-types";
import { imageRefusal, sniffImage } from "./image-sniff";
import { scaledSize } from "./mock-images";
import { initialState, reduce } from "./store";
import { asOutbound } from "./types";

const ID = "0123456789abcdef0123456789abcdef";
const bytes = (...b: number[]): Uint8Array => new Uint8Array(b);
const text = (s: string): Uint8Array => new TextEncoder().encode(s);

export const PNG = bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13);
export const JPEG = bytes(0xff, 0xd8, 0xff, 0xe0, 0, 16, 0x4a, 0x46, 0x49, 0x46, 0, 1);
const GIF = text("GIF89a\u0001\u0000\u0001\u0000\u0080\u0000");
const WEBP = text("RIFF\u0010\u0000\u0000\u0000WEBP");

describe("telling an image by its first bytes", () => {
  it("knows the four kinds", () => {
    expect(sniffImage(PNG)).toBe("image/png");
    expect(sniffImage(JPEG)).toBe("image/jpeg");
    expect(sniffImage(GIF)).toBe("image/gif");
    expect(sniffImage(text("GIF87a......"))).toBe("image/gif");
    expect(sniffImage(WEBP)).toBe("image/webp");
  });

  it("refuses what only looks like one: a PDF, text, a RIFF that is audio, a short head", () => {
    expect(sniffImage(text("%PDF-1.7\n%..."))).toBeNull();
    expect(sniffImage(text("hello, world"))).toBeNull();
    expect(sniffImage(text("RIFF\u0010\u0000\u0000\u0000WAVE"))).toBeNull();
    expect(sniffImage(bytes(0x89, 0x50))).toBeNull();
    expect(sniffImage(new Uint8Array())).toBeNull();
  });

  it("says why in the daemon's words: not an image, then too big", () => {
    expect(imageRefusal(10, text("not a picture"), DEFAULT_LIMITS)).toBe("That file is not a PNG, JPEG, GIF or WebP image.");
    expect(imageRefusal(DEFAULT_LIMITS.max_bytes + 1, PNG, DEFAULT_LIMITS)).toBe("That image is larger than 15 MB.");
    expect(imageRefusal(DEFAULT_LIMITS.max_bytes, PNG, DEFAULT_LIMITS)).toBeNull();
    expect(imageRefusal(10, GIF, { ...DEFAULT_LIMITS, types: ["image/png"] })).toBe("That file is not a PNG, JPEG, GIF or WebP image.");
  });
});

describe("the image routes' shapes", () => {
  it("an id is 32 lowercase hex characters, nothing else", () => {
    expect(isImageId(ID)).toBe(true);
    expect(isImageId(ID.toUpperCase())).toBe(false);
    expect(isImageId(`${ID}0`)).toBe(false);
    expect(isImageId("../../etc/passwd")).toBe(false);
    expect(isImageId(7)).toBe(false);
  });

  it("reads the limits", () => {
    expect(asImageLimits({ limits: DEFAULT_LIMITS })).toEqual(DEFAULT_LIMITS);
    expect(asImageLimits({ limits: { ...DEFAULT_LIMITS, max_per_message: "6" } })).toBeNull();
    expect(asImageLimits(DEFAULT_LIMITS)).toBeNull();
  });

  it("reads a stored image", () => {
    const image = { id: ID, media_type: "image/png", width: 1568, height: 1045, bytes: 400_000 };
    expect(asStoredImage({ image })).toEqual(image);
    expect(asStoredImage({ image: { ...image, id: "abc" } })).toBeNull();
    expect(asStoredImage({ detail: "That image is larger than 15 MB." })).toBeNull();
  });

  it("a turn's images: missing is none, a malformed one is left out", () => {
    expect(asImageRefs(undefined)).toEqual([]);
    expect(asImageRefs(null)).toEqual([]);
    expect(asImageRefs([{ id: ID, width: 4, height: 3 }, { id: "x", width: 4, height: 3 }, { id: ID, width: 0, height: 3 }])).toEqual([{ id: ID, width: 4, height: 3 }]);
  });

  it("brain.mode's local_images: missing is accepted, a wrong type is not", () => {
    const mode = { offline: true, answering: "local", local_backend: "mlx", local_model: "m", local_tools: true };
    expect(asBrainMode(mode)).not.toBeNull();
    expect(asBrainMode({ ...mode, local_images: false })).not.toBeNull();
    expect(asBrainMode({ ...mode, local_images: "no" })).toBeNull();
  });
});

describe("an utterance with images reaches the caption", () => {
  const utterance = (data: Record<string, unknown>) => {
    const event = asOutbound({ type: "user.utterance", ts: 1, data });
    if (!event) throw new Error("not an event");
    return reduce(initialState(), { kind: "event", event }).caption;
  };

  it("keeps them, even with no words", () => {
    const caption = utterance({ text: "", source: "text", images: [{ id: ID, width: 640, height: 480 }] });
    expect(caption.user).toBe("");
    expect(caption.images).toEqual([{ id: ID, width: 640, height: 480 }]);
  });

  it("an older daemon's utterance, or an empty list, carries none", () => {
    expect(utterance({ text: "Hello", source: "voice" }).images).toBeUndefined();
    expect(utterance({ text: "Hello", source: "text", images: [] }).images).toBeUndefined();
  });
});

describe("mock mode stores an image the size the daemon would", () => {
  it("brings the long edge down to the limit and never up", () => {
    expect(scaledSize(4000, 3000, 1568)).toEqual({ width: 1568, height: 1176 });
    expect(scaledSize(1000, 3000, 1568)).toEqual({ width: 523, height: 1568 });
    expect(scaledSize(320, 200, 1568)).toEqual({ width: 320, height: 200 });
  });
});
