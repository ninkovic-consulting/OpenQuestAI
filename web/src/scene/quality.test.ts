import { describe, expect, it } from "vitest";
import { DEFAULT_PREFS, DisplayPrefsStore, parsePrefs, STORAGE_KEY, type PrefsStorage } from "./display-prefs";
import { isQuality, LEVELS, pixelRatioRange, QUALITIES, samplesFor, STEP_BACK } from "./quality";

describe("quality levels", () => {
  it("defaults to Balanced, which draws as sharp as High", () => {
    expect(DEFAULT_PREFS.quality).toBe("balanced");
    expect(LEVELS.balanced.maxPixelRatio).toBe(LEVELS.high.maxPixelRatio);
    expect(LEVELS.balanced.effectScale).toBe(LEVELS.high.effectScale);
    expect(LEVELS.balanced.shadowMapSize).toBe(LEVELS.high.shadowMapSize);
  });

  it("orders the levels from light to heavy", () => {
    const [low, balanced, high] = QUALITIES.map((q) => LEVELS[q]);
    expect(low!.maxPixelRatio).toBeLessThanOrEqual(balanced!.maxPixelRatio);
    expect(low!.rates.ambient).toBeLessThan(balanced!.rates.ambient);
    expect(balanced!.rates.ambient).toBeLessThan(high!.rates.ambient);
    expect(balanced!.rates.motion).toBeLessThanOrEqual(high!.rates.motion);
    for (const level of [low!, balanced!, high!]) {
      expect(level.rates.ambient).toBeLessThan(level.rates.motion);
      expect(level.rates.motion).toBeLessThanOrEqual(level.rates.interaction);
      expect(level.rates.ambient).toBeGreaterThanOrEqual(20);
      expect(level.rates.ambient).toBeLessThanOrEqual(30);
      expect(level.summary.length).toBeGreaterThan(0);
    }
  });

  it("caps the pixel ratio by the level and the display, with the scaler's floor below", () => {
    expect(pixelRatioRange("balanced", 2, false)).toEqual({ max: 2, min: 2 * LEVELS.balanced.minScale });
    expect(pixelRatioRange("balanced", 1, false).max).toBe(1);
    expect(pixelRatioRange("low", 2, false).max).toBe(1);
    expect(pixelRatioRange("high", 3, false).max).toBe(2);
    expect(pixelRatioRange("high", 0, false).max).toBe(1);
  });

  it("drops to the lightest resolution while stepping back", () => {
    expect(pixelRatioRange("high", 2, true).max).toBe(STEP_BACK.maxPixelRatio);
  });

  it("halves Balanced's samples where Retina pixels hide the difference", () => {
    expect(samplesFor(LEVELS.balanced, 2)).toBe(2);
    expect(samplesFor(LEVELS.balanced, 1)).toBe(4);
    expect(samplesFor(LEVELS.high, 2)).toBe(4);
    expect(samplesFor(LEVELS.low, 1)).toBe(0);
  });

  it("knows its names", () => {
    expect(isQuality("high")).toBe(true);
    expect(isQuality("ultra")).toBe(false);
  });
});

describe("display preferences", () => {
  it("reads what was stored and keeps defaults for the rest", () => {
    expect(parsePrefs(null)).toEqual(DEFAULT_PREFS);
    expect(parsePrefs("not json")).toEqual(DEFAULT_PREFS);
    expect(parsePrefs(JSON.stringify({ quality: "low", readout: true }))).toEqual({ quality: "low", readout: true, stepBack: true });
    expect(parsePrefs(JSON.stringify({ quality: "ultra", stepBack: "no" }))).toEqual(DEFAULT_PREFS);
  });

  it("stores a change and tells its listeners", () => {
    const kept = new Map<string, string>();
    const storage: PrefsStorage = { getItem: (k) => kept.get(k) ?? null, setItem: (k, v) => void kept.set(k, v) };
    const store = new DisplayPrefsStore(storage);
    const heard: string[] = [];
    store.subscribe((p) => heard.push(p.quality));
    store.set({ quality: "high" });
    expect(heard).toEqual(["high"]);
    expect(new DisplayPrefsStore(storage).get().quality).toBe("high");
    expect(kept.has(STORAGE_KEY)).toBe(true);
  });

  it("still works when storage refuses", () => {
    const storage: PrefsStorage = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };
    const store = new DisplayPrefsStore(storage);
    store.set({ readout: true });
    expect(store.get().readout).toBe(true);
  });
});
