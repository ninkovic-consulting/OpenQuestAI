// Mock mode's "start a project …": the host's start_project, worked out the
// way the daemon works it out, so the gate card shows the same kind of text
// and a yes adds the same kind of room. The agent follows the words: research
// to the scout, writing to the envoy, upkeep to the steward, else the maker.

import type { Cell, Plan, Room, ToolRef } from "./types";

/** "start a project …", "start a new project for me: …". */
export const START_PROJECT = /^\s*start\s+a\s+(?:new\s+)?project\b[\s,:]*(?:for\s+me\b[\s,:]*)?/i;

export interface MockProject {
  agent: string;
  /** The gate card's preformatted detail, line by line as the daemon writes it. */
  detail: string;
  room: Room;
  firstJob: string;
}

const PICKS: readonly [RegExp, string, string][] = [
  [/\b(research|find out|compare|survey|look into)\b/i, "scout", "It is research, and the scout reads the web."],
  [/\b(write|letter|newsletter|post|blog|email)\b/i, "envoy", "It is writing, the envoy's work."],
  [/\b(clean ?up|backup|upkeep|disk|maintain)\b/i, "steward", "It is upkeep of this Mac, the steward's work."],
];

const GIT: ToolRef = { id: "git", title: "Git", available: true, built_in: false };

/** "a small tool that renames photos" -> "Small Tool That Renames": a name from the first words. */
function nameFrom(words: string): string {
  const kept = words
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .split(/\s+/)
    .filter((w) => w && !/^(a|an|the|for|me|to|of)$/i.test(w))
    .slice(0, 3);
  const name = kept.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(" ");
  return name || "Photo Renamer";
}

function folderOf(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "project";
}

/** The project the words ask for, placed in `at`; the card says it all before anything happens. */
export function mockProject(words: string, plan: Plan, at: Cell, beside: string | null): MockProject {
  const description = words.trim() || "A small command-line tool that renames photos by the date they were taken.";
  const [, agentId, reason] = PICKS.find(([test]) => test.test(description)) ?? [null, "maker", "It is software to build, the maker's work."];
  const agent = plan.agents.find((a) => a.id === agentId) ?? plan.agents[0];
  const name = nameFrom(description);
  const folder = `~/Projects/${folderOf(name)}`;
  const firstJob = `Write a first plan for "${name}" in PLAN.md in the project folder: what it does, the steps to build it, and the open questions. The project: ${description}`;
  const agentName = agent?.name ?? agentId;
  const detail = [
    `Project: ${name}`,
    `Description: ${description}`,
    `Agent: ${agentName} (${agentId}). Why: ${reason}`,
    `Folder to create: /Users/you/Projects/${folderOf(name)}`,
    "Inside it: README.md with the name and description, and git init (git is installed).",
    `Room to add: "${name}", run by ${agentName}, at [${at[0]}, ${at[1]}]${beside ? ` next to the ${beside}` : ""}.`,
    "Room tools: Git.",
    `First job for ${agentName}, in that room:`,
    firstJob,
  ].join("\n");
  const room: Room = {
    id: folderOf(name),
    name,
    kind: "extra",
    shape: "rect",
    at,
    size: [1, 1],
    agent: agentId,
    model: agent?.model ?? "",
    folders: [folder],
    project: name,
    floor: "wood-floor",
    wall: "wallpaper",
    tools: [{ ...GIT }],
    state: "idle",
  };
  return { agent: agentId, detail, room, firstJob };
}
