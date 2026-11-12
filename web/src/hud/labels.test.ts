import { describe, expect, it } from "vitest";
import { resolveOverlaps, type LabelBox } from "./labels";

const chip = (id: string, x: number, y: number, rank: number, w = 100, h = 24): LabelBox => ({ id, x, y, w, h, rank });

describe("room label overlaps", () => {
  it("shows every chip when none touch", () => {
    const shown = resolveOverlaps([chip("hall", 100, 100, 1), chip("library", 300, 100, 2), chip("garage", 100, 200, 3)]);
    expect([...shown].sort()).toEqual(["garage", "hall", "library"]);
  });

  it("keeps the better-ranked chip of two that overlap", () => {
    const shown = resolveOverlaps([chip("library", 120, 105, 2), chip("hall", 100, 100, 1)]);
    expect([...shown]).toEqual(["hall"]);
  });

  it("lets a hidden chip's neighbours show", () => {
    // B loses to A; C overlaps only B, so it shows.
    const shown = resolveOverlaps([chip("a", 100, 100, 0), chip("b", 180, 100, 1), chip("c", 260, 100, 2)]);
    expect([...shown].sort()).toEqual(["a", "c"]);
  });

  it("keeps a gap between chips that would only touch", () => {
    expect(resolveOverlaps([chip("a", 100, 100, 0), chip("b", 202, 100, 1)], 4).size).toBe(1);
    expect(resolveOverlaps([chip("a", 100, 100, 0), chip("b", 210, 100, 1)], 4).size).toBe(2);
  });
});
