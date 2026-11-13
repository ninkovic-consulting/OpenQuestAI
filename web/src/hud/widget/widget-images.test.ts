import { describe, expect, it } from "vitest";
import type { Caption } from "../../net/store";
import { latestExchange, withImageMark } from "./model";

const ID = "0123456789abcdef0123456789abcdef";

describe("the widget's exchange with images", () => {
  const caption = (more: Partial<Caption>): Caption => ({ user: "", source: "text", reply: "", streaming: false, ...more });

  it("marks how many images went with the words", () => {
    expect(withImageMark("You · typed", 0)).toBe("You · typed");
    expect(withImageMark("You · typed", 2)).toBe("You · typed · 2 images");
  });

  it("an image sent alone from the widget shows as sent, with its mark", () => {
    expect(latestExchange(caption({}), "idle", "", null, 1)).toMatchObject({ who: "You · typed · 1 image", user: "", status: "Sent" });
  });

  it("an utterance that is only images is still the latest exchange", () => {
    const e = latestExchange(caption({ images: [{ id: ID, width: 4, height: 3 }] }), "thinking", null, null);
    expect(e).toMatchObject({ who: "You · typed · 1 image", status: "Waiting for the reply" });
  });

  it("an earlier turn's images are marked; one without the field has none", () => {
    const turn = { startedAt: 1, origin: "text" as const, user: "Here", reply: "Seen", status: "ok" as const };
    expect(latestExchange(caption({ source: null }), "idle", null, { ...turn, images: [{ id: ID, width: 4, height: 3 }, { id: ID, width: 4, height: 3 }] })?.who).toBe("You · typed · 2 images");
    expect(latestExchange(caption({ source: null }), "idle", null, turn)?.who).toBe("You · typed");
  });
});
