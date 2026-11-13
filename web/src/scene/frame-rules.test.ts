import { describe, expect, it } from "vitest";
import { activityOf, labelsDue, LABEL_REFRESH_PER_S, shadowsDue, STILL, SWAY_SHADOWS_PER_S } from "./frame-rules";

describe("what a frame asks of the pacing", () => {
  it("asks for nothing when nothing moves", () => {
    expect(activityOf(STILL)).toBe("still");
  });

  it("treats idle figures and the faint streaks as ambient", () => {
    expect(activityOf({ ...STILL, figuresAnimating: true })).toBe("ambient");
    expect(activityOf({ ...STILL, ambient: true })).toBe("ambient");
  });

  it("treats walking, rising, easing lights and blur, and the voice as motion", () => {
    for (const k of ["figuresMoving", "rising", "lights", "blur", "voice"] as const) {
      expect(activityOf({ ...STILL, ambient: true, [k]: true })).toBe("motion");
    }
  });

  it("puts the camera above everything", () => {
    expect(activityOf({ ...STILL, figuresMoving: true, camera: true })).toBe("interaction");
  });
});

describe("the shadow map", () => {
  it("costs nothing while the house stands still", () => {
    expect(shadowsDue({ ...STILL, ambient: true, lights: true, camera: true }, false, 10_000)).toBe(false);
  });

  it("is redrawn after a rebuild, and whenever a figure walks or a room rises", () => {
    expect(shadowsDue(STILL, true, 0)).toBe(true);
    expect(shadowsDue({ ...STILL, figuresMoving: true }, false, 0)).toBe(true);
    expect(shadowsDue({ ...STILL, rising: true }, false, 0)).toBe(true);
  });

  it("follows a figure's sway only now and then", () => {
    const gap = 1000 / SWAY_SHADOWS_PER_S;
    expect(shadowsDue({ ...STILL, figuresAnimating: true }, false, gap - 1)).toBe(false);
    expect(shadowsDue({ ...STILL, figuresAnimating: true }, false, gap)).toBe(true);
  });
});

describe("the room labels", () => {
  it("follow the camera, a rising room and new room states at once", () => {
    expect(labelsDue({ ...STILL, camera: true }, false, 0)).toBe(true);
    expect(labelsDue({ ...STILL, rising: true }, false, 0)).toBe(true);
    expect(labelsDue(STILL, true, 0)).toBe(true);
  });

  it("are otherwise checked only a few times a second", () => {
    expect(labelsDue({ ...STILL, figuresMoving: true }, false, 10)).toBe(false);
    expect(labelsDue(STILL, false, 1000 / LABEL_REFRESH_PER_S)).toBe(true);
  });
});
