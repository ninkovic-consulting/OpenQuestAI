import { describe, expect, it } from "vitest";
import { asPlan, asToolRefs, hostRefusal } from "../net/plan";
import { HOST_TOOLS, samplePlan } from "../net/sample-plan";
import type { ToolRef } from "../net/types";
import { replySize } from "./caption";
import { formatSpend } from "./money";
import { roomCardModel } from "./room-card";
import { agentChoices, carriedOn, fromProposal, newRoom, type RoomFields, toggle, unionTools } from "./room-form";

const tool = (id: string, available: boolean): ToolRef => ({ id, title: id.toUpperCase(), available, built_in: false });
const proposal = [tool("git", true), tool("npm", true), tool("docker", false)];
const shop = ["~/Projects/shop", "~/Notes"];
const fields: RoomFields = { name: " Den ", agent: "maker", at: [4, 1], folders: ["~/Projects/shop", "~/Notes"], model: "" };

describe("tool picks", () => {
  it("start with every available tool on and the missing ones off", () => {
    const picks = fromProposal(shop, proposal);
    expect([...picks.on]).toEqual(["git", "npm"]);
  });

  it("toggle switches one tool and ignores ids that were not proposed", () => {
    let picks = fromProposal(shop, proposal);
    picks = toggle(picks, "git");
    picks = toggle(picks, "docker");
    expect([...picks.on].sort()).toEqual(["docker", "npm"]);
    expect(toggle(picks, "maven")).toBe(picks);
  });
});

describe("tools over several folders", () => {
  it("are the union, each tool once, in the order first proposed", () => {
    const merged = unionTools([[tool("git", true), tool("npm", true)], [tool("git", true), tool("docker", false)]]);
    expect(merged.map((t) => t.id)).toEqual(["git", "npm", "docker"]);
    expect(unionTools([])).toEqual([]);
  });

  it("keep what was on or off when a folder is added, and switch on a new installed tool", () => {
    const before = toggle(fromProposal(["~/a"], [tool("git", true), tool("npm", true)]), "npm");
    const next = [tool("git", true), tool("npm", true), tool("gh", true), tool("docker", false)];
    expect(carriedOn(before, next)).toEqual(["git", "gh"]);
    expect(carriedOn(null, next)).toBeUndefined();
  });
});

describe("the new room body", () => {
  it("sends the switched-on tools in proposal order", () => {
    const picks = toggle(toggle(fromProposal(shop, proposal), "docker"), "git");
    expect(newRoom(fields, picks)).toEqual({ name: "Den", agent: "maker", at: [4, 1], folders: ["~/Projects/shop", "~/Notes"], tools: ["npm", "docker"] });
  });

  it("sends an empty list when every proposed tool was switched off", () => {
    const picks = toggle(toggle(fromProposal(shop, proposal), "git"), "npm");
    expect(newRoom(fields, picks).tools).toEqual([]);
  });

  it("sends the folders in order, trimmed, and none when there are none", () => {
    expect(newRoom({ ...fields, folders: [" ~/b ", "", "~/a"] }, null).folders).toEqual(["~/b", "~/a"]);
    expect(newRoom({ ...fields, folders: ["  "] }, null)).not.toHaveProperty("folders");
  });

  it("takes a proposal made for the same folders in any order", () => {
    expect(newRoom({ ...fields, folders: ["~/Notes", "~/Projects/shop"] }, fromProposal(shop, proposal)).tools).toEqual(["git", "npm"]);
  });

  it("leaves tools out without a folder, without a proposal, or for a stale one", () => {
    expect(newRoom({ ...fields, folders: ["  "] }, fromProposal(shop, proposal))).not.toHaveProperty("tools");
    expect(newRoom(fields, fromProposal(["~/Projects/shop"], proposal))).not.toHaveProperty("tools");
    expect(newRoom(fields, null)).not.toHaveProperty("tools");
    expect(newRoom(fields, fromProposal(shop, []))).not.toHaveProperty("tools");
    expect(newRoom(fields, fromProposal(["~/Projects/other", "~/Notes"], proposal))).not.toHaveProperty("tools");
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

  it("a plan whose rooms lack folders, or hold a non-text one, or lack the limit is refused", () => {
    const plan = samplePlan() as unknown as { rooms: Record<string, unknown>[] };
    delete plan.rooms[0]!["folders"];
    expect(asPlan(plan)).toBeNull();
    const numbers = samplePlan() as unknown as { rooms: Record<string, unknown>[] };
    numbers.rooms[0]!["folders"] = [4];
    expect(asPlan(numbers)).toBeNull();
    const unlimited = samplePlan() as unknown as Record<string, unknown>;
    delete unlimited["max_room_folders"];
    expect(asPlan(unlimited)).toBeNull();
    expect(asPlan({ ...samplePlan(), rooms: samplePlan().rooms.map((r) => ({ ...r, folders: ["~/Projects/shop"] })) })).not.toBeNull();
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
  it("shows the agent, model, folders and what each tool can do today", () => {
    const plan = samplePlan();
    plan.rooms.push({
      ...plan.rooms.find((r) => r.id === "garage")!,
      id: "den",
      name: "Den",
      kind: "extra",
      folders: ["~/Projects/shop", "~/Notes/a-very-long-folder-name/with/more/parts"],
      tools: [...HOST_TOOLS.slice(4), tool("git", true), tool("docker", false)],
    });
    const card = roomCardModel(plan, "den");
    expect(card).toMatchObject({ name: "Den", agent: "Tink", model: "claude-opus-5-5", folders: ["~/Projects/shop", "~/Notes/a-very-long-folder-name/with/more/parts"] });
    expect(card?.tools).toEqual([
      { title: "Shell", state: "runs" },
      { title: "GIT", state: "runs" },
      { title: "DOCKER", state: "missing" },
    ]);
    expect(card?.note).toContain("Writing files and running these programs ask you first");
    const bare = roomCardModel({ ...plan, rooms: plan.rooms.map((r) => (r.id === "den" ? { ...r, folders: [] } : r)) }, "den");
    expect(bare?.tools[1]).toEqual({ title: "GIT", state: "waits" });
    expect(bare?.folders).toEqual([]);
    expect(bare?.note).toContain("Attach a project folder");
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

describe("the add-room form's agents", () => {
  it("leaves out the host and selects the first agent that is allowed", () => {
    const choices = agentChoices(samplePlan());
    expect(choices.agents.map((a) => a.id)).toEqual(["steward", "envoy", "maker", "checker", "scout"]);
    expect(choices.selected).toBe("steward");
  });

  it("decides the host from the Hall, not from the id", () => {
    const plan = samplePlan();
    const hall = plan.rooms.find((r) => r.id === "hall");
    if (hall) hall.agent = "scout";
    const choices = agentChoices(plan);
    expect(choices.agents.map((a) => a.id)).toEqual(["host", "steward", "envoy", "maker", "checker"]);
    expect(choices.selected).toBe("host");
  });

  it("has nothing to select when the host is the only agent", () => {
    const plan = samplePlan();
    plan.agents = plan.agents.filter((a) => a.id === "host");
    expect(agentChoices(plan)).toEqual({ agents: [], selected: null });
  });

  it("words the refusal with the host's display name and the agents that can be chosen", () => {
    expect(hostRefusal(samplePlan())).toBe(
      "Vision orchestrates from the Hall and cannot run another room. Choose one of: Brass, Wren, Tink, Tock, Rook.",
    );
  });
});
