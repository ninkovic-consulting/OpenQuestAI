import { describe, expect, it } from "vitest";
import { MockDaemon } from "./mock";
import { samplePlan } from "./sample-plan";
import { Store } from "./store";

describe("mock daemon rooms", () => {
  it("refuses the host for a new room the way the daemon does", async () => {
    const daemon = new MockDaemon(new Store());
    const slot = samplePlan().free_slots[0];
    if (!slot) throw new Error("the sample plan has a free slot");
    const result = await daemon.postRoom({ name: "Den", agent: "host", at: slot });
    expect(result).toEqual({
      ok: false,
      message: "Vision orchestrates from the Hall and cannot run another room. Choose one of: Brass, Wren, Tink, Tock, Rook.",
    });
  });

  it("gives the sample Library to the steward, so only the Hall is the host's", () => {
    const plan = samplePlan();
    expect(plan.rooms.filter((r) => r.agent === "host").map((r) => r.id)).toEqual(["hall"]);
  });
});
