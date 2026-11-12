import { describe, expect, it } from "vitest";
import { asPlan, asToolRefs } from "../net/plan";
import { HOST_TOOLS, samplePlan } from "../net/sample-plan";
import type { ToolRef } from "../net/types";
import { replySize } from "./caption";
import { formatSpend } from "./money";
import { roomCardModel } from "./room-card";
import { fromProposal, newRoom, type RoomFields, toggle } from "./room-form";

const tool = (id: string, available: boolean): ToolRef => ({ id, title: id.toUpperCase(), available, built_in: false });
const proposal = [tool("git", true), tool("npm", true), tool("docker", false)];
const fields: RoomFields = { name: " Den ", agent: "maker", at: [4, 1], project: "~/Projects/shop", model: "" };

describe("tool picks", () => {
  it("start with every available tool on and the missing ones off", () => {
    const picks = fromProposal("~/Projects/shop", proposal);
    expect([...picks.on]).toEqual(["git", "npm"]);
  });

  it("toggle switches one tool and ignores ids that were not proposed", () => {
    let picks = fromProposal("~/Projects/shop", proposal);
    picks = toggle(picks, "git");
    picks = toggle(picks, "docker");
    expect([...picks.on].sort()).toEqual(["docker", "npm"]);
    expect(toggle(picks, "maven")).toBe(picks);
  });
});

describe("the new room body", () => {
  it("sends the switched-on tools in proposal order", () => {
    const picks = toggle(toggle(fromProposal("~/Projects/shop", proposal), "docker"), "git");
    expect(newRoom(fields, picks)).toEqual({ name: "Den", agent: "maker", at: [4, 1], project: "~/Projects/shop", tools: ["npm", "docker"] });
  });

  it("sends an empty list when every proposed tool was switched off", () => {
    const picks = toggle(toggle(fromProposal("~/Projects/shop", proposal), "git"), "npm");
    expect(newRoom(fields, picks).tools).toEqual([]);
  });

  it("leaves tools out without a project, without a proposal, or for a stale one", () => {
    expect(newRoom({ ...fields, project: "  " }, fromProposal("~/Projects/shop", proposal))).not.toHaveProperty("tools");
    expect(newRoom(fields, null)).not.toHaveProperty("tools");
    expect(newRoom(fields, fromProposal("~/Projects/shop", []))).not.toHaveProperty("tools");
    expect(newRoom(fields, fromProposal("~/Projects/other", proposal))).not.toHaveProperty("tools");
  });

  it("keeps an optional model", () => {
    expect(newRoom({ ...fields, model: " claude-sonnet-5-5 " }, null).model).toBe("claude-sonnet-5-5");
  });
});

describe("plans carry tools", () => {
  it("the mock plan gives the host's rooms the five built-in tools and the rest none", () => {
    const plan = samplePlan();
    const hall = plan.rooms.find((r) => r.id === "hall");
    expect(hall?.tools.map((t) => t.id)).toEqual(["remember", "recall", "open_app", "open_url", "shell"]);
    expect(hall?.tools.every((t) => t.built_in && t.available)).toBe(true);
    expect(plan.rooms.find((r) => r.id === "workshop")?.tools).toEqual([]);
    expect(asPlan(plan)).not.toBeNull();
  });

  it("a plan whose rooms lack tools is refused", () => {
    const plan = samplePlan() as unknown as { rooms: Record<string, unknown>[] };
    delete plan.rooms[0]!["tools"];
    expect(asPlan(plan)).toBeNull();
  });

  it("narrows tool lists", () => {
    expect(asToolRefs([...HOST_TOOLS])).toHaveLength(5);
    expect(asToolRefs([{ id: "git" }])).toBeNull();
    expect(asToolRefs("git")).toBeNull();
  });
});

describe("room card", () => {
  it("shows the agent, model, project and what each tool can do today", () => {
    const plan = samplePlan();
    plan.rooms.push({
      ...plan.rooms.find((r) => r.id === "garage")!,
      id: "den",
      name: "Den",
      kind: "extra",
      project: "~/Projects/shop",
      tools: [...HOST_TOOLS.slice(4), tool("git", true), tool("docker", false)],
    });
    const card = roomCardModel(plan, "den");
    expect(card).toMatchObject({ name: "Den", agent: "Tink", model: "claude-opus-5-5", project: "~/Projects/shop" });
    expect(card?.tools).toEqual([
      { title: "Shell", state: "runs" },
      { title: "GIT", state: "waits" },
      { title: "DOCKER", state: "missing" },
    ]);
    expect(card?.note).toContain("Only Vision's built-in tools run in this slice");
    expect(roomCardModel(plan, "nowhere")).toBeNull();
  });
});

describe("caption and spend", () => {
  it("steps the reply type down as it grows", () => {
    expect(replySize("Short and sweet.")).toBe("normal");
    expect(replySize("x".repeat(200))).toBe("long");
    expect(replySize("x".repeat(500))).toBe("longer");
  });

  it("shows a spend under a cent as <$0.01, never $0.00", () => {
    expect(formatSpend(0)).toBe("$0.00");
    expect(formatSpend(0.0004)).toBe("<$0.01");
    expect(formatSpend(0.0099)).toBe("<$0.01");
    expect(formatSpend(0.01)).toBe("$0.01");
    expect(formatSpend(18.424)).toBe("$18.42");
  });
});
