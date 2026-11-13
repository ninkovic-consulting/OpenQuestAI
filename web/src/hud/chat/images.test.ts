import { describe, expect, it } from "vitest";
import type { BrainMode } from "../../net/brain-types";
import { DEFAULT_LIMITS, type ImageRef } from "../../net/image-types";
import type { Caption } from "../../net/store";
import { emptyThread, fromCaption, sent, withHistory } from "./entries";
import { asTurns } from "./history";
import { imageMark, sentAlt, thumbAlts } from "./thumbs";
import { BLOCKED, emptyTray, failed, imagesBlocked, offer, type Offered, readyToSend, removeImage, removeLabel, type Tray, uploaded } from "./tray";

const head = (...b: number[]): Uint8Array => new Uint8Array(b);
const png = (size = 1000): Offered => ({ size, head: head(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13) });
const jpeg = (size = 1000): Offered => ({ size, head: head(0xff, 0xd8, 0xff, 0xe1, 0, 0, 0, 0, 0, 0, 0, 0) });
/** A text file renamed `photo.png` and declared as one: only its bytes count. */
const renamed: Offered = { size: 40, head: new TextEncoder().encode("just some te") };

const ref = (n: number): ImageRef => ({ id: n.toString(16).padStart(32, "0"), width: 640, height: 480 });
const mode = (offline: boolean, local_images?: boolean): BrainMode => ({
  offline,
  answering: offline ? "local" : "claude",
  local_backend: "mlx",
  local_model: "m",
  local_tools: true,
  ...(local_images === undefined ? {} : { local_images }),
});

const fill = (n: number): Tray => {
  let t = offer(emptyTray(), Array.from({ length: n }, () => png()), DEFAULT_LIMITS, false).tray;
  for (const w of t.items) t = uploaded(t, w.key, ref(w.key));
  return t;
};

describe("the images waiting in the field", () => {
  it("takes images as pending, in order, each with its own key", () => {
    const r = offer(emptyTray(), [png(), jpeg()], DEFAULT_LIMITS, false);
    expect(r.taken).toEqual([
      { index: 0, key: 1 },
      { index: 1, key: 2 },
    ]);
    expect(r.tray.items.map((w) => w.state)).toEqual(["pending", "pending"]);
    expect(r.tray.refusal).toBeNull();
  });

  it("refuses a file that is not an image by its bytes, a renamed one included, and takes the rest", () => {
    const r = offer(emptyTray(), [renamed, png()], DEFAULT_LIMITS, false);
    expect(r.taken).toEqual([{ index: 1, key: 1 }]);
    expect(r.tray.refusal).toBe("That file is not a PNG, JPEG, GIF or WebP image.");
  });

  it("refuses an image that is too big", () => {
    const r = offer(emptyTray(), [png(DEFAULT_LIMITS.max_bytes + 1)], DEFAULT_LIMITS, false);
    expect(r.taken).toEqual([]);
    expect(r.tray.refusal).toBe("That image is larger than 15 MB.");
  });

  it("takes no more than the most one message carries", () => {
    const r = offer(fill(5), [png(), png(), png()], DEFAULT_LIMITS, false);
    expect(r.taken).toHaveLength(1);
    expect(r.tray.items).toHaveLength(6);
    expect(r.tray.refusal).toBe("At most 6 images go with one message.");
  });

  it("a refusal clears at the next thing that works", () => {
    const refused = offer(emptyTray(), [renamed], DEFAULT_LIMITS, false).tray;
    expect(offer(refused, [png()], DEFAULT_LIMITS, false).tray.refusal).toBeNull();
    expect(removeImage(fill(2), 1).refusal).toBeNull();
  });

  it("an upload the daemon refused leaves the tray with its reason; one removed meanwhile stays removed", () => {
    const t = offer(emptyTray(), [png(), png()], DEFAULT_LIMITS, false).tray;
    const bad = failed(t, 1, "That image has more than 50 megapixels.");
    expect(bad.items.map((w) => w.key)).toEqual([2]);
    expect(bad.refusal).toBe("That image has more than 50 megapixels.");
    const gone = removeImage(t, 2);
    expect(uploaded(gone, 2, ref(2))).toBe(gone);
  });

  it("names each remove button by place", () => {
    expect(removeLabel(1, 3)).toBe("Remove image 2 of 3");
  });
});

describe("Enter with images", () => {
  it("sends the text with the ready images, or the images alone", () => {
    const t = fill(2);
    expect(readyToSend(t, "Which is better?", false)).toEqual({ ok: true, images: [ref(1), ref(2)] });
    expect(readyToSend(t, "", false)).toEqual({ ok: true, images: [ref(1), ref(2)] });
  });

  it("text alone sends as before; nothing at all is no send and no complaint", () => {
    expect(readyToSend(emptyTray(), "Hello", false)).toEqual({ ok: true, images: [] });
    expect(readyToSend(emptyTray(), "", false)).toEqual({ ok: false, why: null });
  });

  it("is refused plainly while an image still uploads", () => {
    const t = offer(fill(1), [png()], DEFAULT_LIMITS, false).tray;
    const r = readyToSend(t, "Look", false);
    expect(r.ok).toBe(false);
    expect(!r.ok && r.why).toMatch(/still uploading/);
  });
});

describe("offline mode with a text-only model", () => {
  it("blocks images only when offline and the local model cannot see; a missing flag is no", () => {
    expect(imagesBlocked(null)).toBe(false);
    expect(imagesBlocked(mode(false))).toBe(false);
    expect(imagesBlocked(mode(true))).toBe(true);
    expect(imagesBlocked(mode(true, false))).toBe(true);
    expect(imagesBlocked(mode(true, true))).toBe(false);
  });

  it("refuses new images and a send with images, saying why; text still goes", () => {
    const r = offer(emptyTray(), [png()], DEFAULT_LIMITS, true);
    expect(r.taken).toEqual([]);
    expect(r.tray.refusal).toBe(BLOCKED);
    expect(readyToSend(fill(1), "Look", true)).toEqual({ ok: false, why: BLOCKED });
    expect(readyToSend(emptyTray(), "Hello", true)).toEqual({ ok: true, images: [] });
  });
});

describe("the owner's images in the thread", () => {
  const idle: Caption = { user: "", source: null, reply: "", streaming: false };

  it("a sent message with images is claimed by its echo, even with no words", () => {
    let t = sent(emptyThread(), "", false, [ref(1)]);
    t = fromCaption(t, idle, { user: "", source: "text", reply: "", streaming: false, images: [ref(1)] });
    expect(t.entries).toHaveLength(1);
    expect(t.entries[0]).toMatchObject({ phase: "waiting", user: "", images: [ref(1)] });
  });

  it("an echo with other images is not the same message", () => {
    let t = sent(emptyThread(), "Look", false, [ref(1)]);
    t = fromCaption(t, idle, { user: "Look", source: "text", reply: "", streaming: false, images: [ref(2)] });
    expect(t.entries.map((e) => e.phase)).toEqual(["waiting", "sending"]);
  });

  it("an utterance from elsewhere with images opens a turn that shows them", () => {
    const t = fromCaption(emptyThread(), idle, { user: "", source: "phone", reply: "", streaming: false, images: [ref(3), ref(4)] });
    expect(t.entries[0]?.images).toEqual([ref(3), ref(4)]);
    expect(thumbAlts(t.entries[0]?.images ?? [])).toEqual(["Image you sent, 1 of 2", "Image you sent, 2 of 2"]);
  });

  it("history turns bring their images back after a reload; missing is none", () => {
    const turn = (images?: unknown) => ({ started_at: 1, source: "text", user_text: "Here", reply: "Seen", status: "ok", ...(images === undefined ? {} : { images }) });
    const turns = asTurns({ turns: [turn([ref(5), ref(6), ref(7)]), turn(), turn([{ id: "bad", width: 1, height: 1 }])] });
    expect(turns.map((h) => h.images)).toEqual([[ref(5), ref(6), ref(7)], undefined, undefined]);
    const t = withHistory(emptyThread(), turns.slice(0, 1));
    expect(thumbAlts(t.entries[0]?.images ?? [])).toEqual(["Image you sent, 1 of 3", "Image you sent, 2 of 3", "Image you sent, 3 of 3"]);
    expect(withHistory(emptyThread(), turns.slice(1, 2)).entries[0]?.images).toBeUndefined();
  });

  it("words for the mark and the alt text", () => {
    expect(imageMark(0)).toBe("");
    expect(imageMark(1)).toBe("1 image");
    expect(imageMark(3)).toBe("3 images");
    expect(sentAlt(0, 1)).toBe("Image you sent, 1 of 1");
  });
});
