import { describe, expect, it } from "vitest";

import { asInset } from "../net/native";
import { insetParam } from "./safe-area";

describe("the notch's inset", () => {
  it("is pretended with ?inset= only when asked", () => {
    expect(insetParam("?mock=1&inset=38")).toBe(38);
    expect(insetParam("?mock=1")).toBeNull();
    expect(insetParam("?inset=-4")).toBeNull();
    expect(insetParam("?inset=tall")).toBeNull();
  });

  it("is a number of points from the shell, or 0", () => {
    expect(asInset(32)).toBe(32);
    expect(asInset(-1)).toBe(0);
    expect(asInset("32")).toBe(0);
    expect(asInset(Number.NaN)).toBe(0);
  });
});
