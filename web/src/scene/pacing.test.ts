import { describe, expect, it } from "vitest";
import type { BrainMode } from "../net/brain-types";
import { decidePace, due, nextDue, SLACK_MS, strongest, workingHere } from "./pacing";
import { LEVELS, STEP_BACK } from "./quality";

const mode = (answering: BrainMode["answering"]): BrainMode => ({
  offline: answering === "local",
  answering,
  local_backend: "mlx",
  local_model: "m",
  local_tools: null,
});

const quiet = { assistant: "idle", brain: null, mode: null, agents: {} } as const;

describe("the pace of drawing", () => {
  it("draws nothing while the page is hidden, whatever moves", () => {
    expect(decidePace({ visible: false, activity: "interaction", stepBack: false, quality: "high" }).fps).toBe(0);
  });

  it("draws nothing when nothing moves", () => {
    expect(decidePace({ visible: true, activity: "still", stepBack: false, quality: "balanced" }).fps).toBe(0);
  });

  it("gives idle motion its own low rate and keeps the display's rate for the owner's hand", () => {
    const at = (activity: "ambient" | "motion" | "interaction"): number => decidePace({ visible: true, activity, stepBack: false, quality: "balanced" }).fps;
    expect(at("ambient")).toBe(24);
    expect(at("motion")).toBe(60);
    expect(at("interaction")).toBe(Infinity);
  });

  it("follows the quality level's rates", () => {
    for (const quality of ["low", "balanced", "high"] as const) {
      expect(decidePace({ visible: true, activity: "ambient", stepBack: false, quality }).fps).toBe(LEVELS[quality].rates.ambient);
    }
  });

  it("steps back to the lightest rates, whatever the level", () => {
    for (const quality of ["low", "balanced", "high"] as const) {
      const p = decidePace({ visible: true, activity: "interaction", stepBack: true, quality });
      expect(p.fps).toBe(STEP_BACK.rates.interaction);
      expect(p.label).toMatch(/^stepped back/);
    }
  });

  it("ranks activity", () => {
    expect(strongest("ambient", "motion")).toBe("motion");
    expect(strongest("interaction", "still")).toBe("interaction");
  });
});

describe("stepping back for the assistant", () => {
  it("steps back while the voice speaks, on any model", () => {
    expect(workingHere({ ...quiet, assistant: "speaking", brain: "claude", mode: mode("claude") })).toBe(true);
  });

  it("steps back while a local model thinks, by the turn's brain or by offline mode", () => {
    expect(workingHere({ ...quiet, assistant: "thinking", brain: "local" })).toBe(true);
    expect(workingHere({ ...quiet, assistant: "thinking", brain: "claude", mode: mode("local") })).toBe(true);
  });

  it("does not step back while Claude thinks, or at rest", () => {
    expect(workingHere({ ...quiet, assistant: "thinking", brain: "claude", mode: mode("claude") })).toBe(false);
    expect(workingHere({ ...quiet, assistant: "listening" })).toBe(false);
    expect(workingHere(quiet)).toBe(false);
  });

  it("steps back while a resident works on the local model in offline mode", () => {
    const agents = { maker: { state: "working", job: "j1" } } as const;
    expect(workingHere({ ...quiet, mode: mode("local"), agents })).toBe(true);
    expect(workingHere({ ...quiet, mode: mode("claude"), agents })).toBe(false);
    expect(workingHere({ ...quiet, mode: mode("local"), agents: { maker: { state: "waiting", job: "j1" } } })).toBe(false);
  });
});

describe("the frame rhythm", () => {
  /** Frames drawn in a second of display ticks at `hz`, aiming at `fps`. */
  const drawn = (hz: number, fps: number): number => {
    let next = 0;
    let n = 0;
    for (let t = 0; t < 1000; t += 1000 / hz) {
      if (!due(t, next)) continue;
      n++;
      next = nextDue(next, t, fps);
    }
    return n;
  };

  it("keeps its rate on 60 and 120 Hz displays", () => {
    expect(drawn(120, 24)).toBe(24);
    expect(drawn(120, 60)).toBe(60);
    expect(drawn(60, 24)).toBeGreaterThanOrEqual(23);
    expect(drawn(60, 24)).toBeLessThanOrEqual(25);
    expect(drawn(120, Infinity)).toBe(120);
  });

  it("does not try to catch up after a pause", () => {
    expect(nextDue(0, 5000, 24)).toBeCloseTo(5000 + 1000 / 24);
  });

  it("allows a tick that comes a little early", () => {
    expect(due(100 - SLACK_MS, 100)).toBe(true);
    expect(due(100 - SLACK_MS - 1, 100)).toBe(false);
  });
});
