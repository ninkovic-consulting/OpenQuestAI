// The add-room form's logic, apart from the DOM: which proposed tools are
// switched on, and the body that is posted.

import { roomAgents } from "../net/plan";
import { cleanFolders, sameFolderSet } from "./folders";
import type { Agent, Cell, NewRoom, Plan, ToolRef } from "../net/types";

/** The tools proposed for a room's folders and which of them are on. */
export interface ToolPicks {
  /** The folders the proposal was made for. */
  folders: readonly string[];
  tools: readonly ToolRef[];
  on: ReadonlySet<string>;
}

/**
 * A fresh proposal: every tool whose program is on this Mac starts on, the
 * rest off. With `on` (a room's current tools) exactly those proposed start on.
 */
export function fromProposal(folders: readonly string[], tools: readonly ToolRef[], on?: readonly string[]): ToolPicks {
  const start = on ? tools.filter((t) => on.includes(t.id)) : tools.filter((t) => t.available);
  return { folders, tools, on: new Set(start.map((t) => t.id)) };
}

/** What several folders look like they need together: each tool once, in the order first proposed. */
export function unionTools(proposals: readonly (readonly ToolRef[])[]): ToolRef[] {
  const seen = new Map<string, ToolRef>();
  for (const tool of proposals.flat()) if (!seen.has(tool.id)) seen.set(tool.id, tool);
  return [...seen.values()];
}

/**
 * The ids to switch on after the folders changed: what was on stays on, what
 * was off stays off, and a tool the earlier folders did not propose starts on
 * when its program is installed.
 */
export function carriedOn(previous: ToolPicks | null, tools: readonly ToolRef[]): string[] | undefined {
  if (!previous) return undefined;
  const known = new Set(previous.tools.map((t) => t.id));
  return tools.filter((t) => previous.on.has(t.id) || (!known.has(t.id) && t.available)).map((t) => t.id);
}

/** The switched-on tools in proposal order, as a room stores them. */
export function pickedIds(picks: ToolPicks): string[] {
  return picks.tools.filter((t) => picks.on.has(t.id)).map((t) => t.id);
}

export function toggle(picks: ToolPicks, id: string): ToolPicks {
  if (!picks.tools.some((t) => t.id === id)) return picks;
  const on = new Set(picks.on);
  if (on.has(id)) on.delete(id);
  else on.add(id);
  return { ...picks, on };
}

export interface RoomFields {
  name: string;
  agent: string;
  at: Cell;
  /** The project's name; left out or blank, the room has none. */
  project?: string;
  folders: string[];
  model: string;
}

/**
 * The body for `POST /api/house/rooms`. Tools are sent only when a proposal
 * for exactly these folders was shown and had tools in it; otherwise the room
 * uses its agent's tools.
 */
export function newRoom(fields: RoomFields, picks: ToolPicks | null): NewRoom {
  const room: NewRoom = { name: fields.name.trim(), agent: fields.agent, at: fields.at };
  const folders = cleanFolders(fields.folders);
  const model = fields.model.trim();
  const project = (fields.project ?? "").trim();
  if (project) room.project = project;
  if (folders.length > 0) room.folders = folders;
  if (model) room.model = model;
  if (folders.length > 0 && picks && sameFolderSet(picks.folders, folders) && picks.tools.length > 0) {
    room.tools = pickedIds(picks);
  }
  return room;
}

/** What the form's agent list offers: the agents a room may have, and the one chosen at first. */
export interface AgentChoices {
  agents: Agent[];
  selected: string | null;
}

/** Everyone but the host; the first of them is selected. With nobody left the form cannot be submitted. */
export function agentChoices(plan: Plan): AgentChoices {
  const agents = roomAgents(plan);
  return { agents, selected: agents[0]?.id ?? null };
}
