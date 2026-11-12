import { describe, expect, it } from "vitest";
import { samplePlan } from "../net/sample-plan";
import { CAST, characterOf } from "./cast";
import { residenceOf, residences } from "./residence";

describe("residenceOf", () => {
  it("puts an agent in its first room in plan order when none is active", () => {
    const plan = samplePlan();
    expect(residenceOf(plan, "maker", {})?.room.id).toBe("kitchen");
    expect(residenceOf(plan, "steward", {})?.room.id).toBe("library");
  });

  it("puts an agent in its active room, and back when the light goes out", () => {
    const plan = samplePlan();
    const there = residenceOf(plan, "maker", { workshop: "active" });
    expect(there?.room.id).toBe("workshop");
    expect(there?.light).toBe("active");
    expect(residenceOf(plan, "maker", { workshop: "idle" })?.room.id).toBe("kitchen");
  });

  it("reads the plan's own state when no event has come in", () => {
    const plan = samplePlan();
    const garage = plan.rooms.find((r) => r.id === "garage");
    if (garage) garage.state = "active";
    expect(residenceOf(plan, "maker", {})?.room.id).toBe("garage");
    expect(residenceOf(plan, "maker", { garage: "dark" })?.room.id).toBe("kitchen");
  });

  it("takes the first active room when several are", () => {
    expect(residenceOf(samplePlan(), "maker", { workshop: "active", "game-room": "active" })?.room.id).toBe("game-room");
  });

  it("has nowhere for an agent without rooms", () => {
    expect(residenceOf(samplePlan(), "nobody", {})).toBeNull();
  });
});

describe("residences", () => {
  it("places every agent with a figure exactly once, and never the host", () => {
    const homes = residences(samplePlan(), { attic: "active" });
    expect(homes.map((h) => h.agent)).toEqual(["steward", "envoy", "maker", "checker", "scout"]);
    expect(homes.find((h) => h.agent === "scout")?.room.id).toBe("attic");
  });

  it("gives no figure to an agent outside the cast", () => {
    const plan = samplePlan();
    plan.agents.push({ id: "stranger", name: "Stranger", model: "m" });
    plan.rooms.push({ ...plan.rooms[1]!, id: "den", agent: "stranger" });
    expect(characterOf("stranger")).toBeNull();
    expect(characterOf("toString")).toBeNull();
    expect(residences(plan, {}).some((h) => h.agent === "stranger")).toBe(false);
  });

  it("casts a figure for each of the five other agents", () => {
    expect(Object.keys(CAST).sort()).toEqual(["checker", "envoy", "maker", "scout", "steward"]);
  });
});
