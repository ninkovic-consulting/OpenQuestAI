// The add-room form's logic, apart from the DOM: which proposed tools are
// switched on, and the body that is posted.

import { roomAgents } from "../net/plan";
import type { Agent, Cell, NewRoom, Plan, ToolRef } from "../net/types";

/** The tools proposed for one project folder and which of them are on. */
export interface ToolPicks {
  project: string;
  tools: readonly ToolRef[];
  on: ReadonlySet<string>;
}

/**
 * A fresh proposal: every tool whose program is on this Mac starts on, the
 * rest off. With `on` (a room's current tools) exactly those proposed start on.
 */
export function fromProposal(project: string, tools: readonly ToolRef[], on?: readonly string[]): ToolPicks {
  const start = on ? tools.filter((t) => on.includes(t.id)) : tools.filter((t) => t.available);
  return { project, tools, on: new Set(start.map((t) => t.id)) };
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
  project: string;
  model: string;
}

/**
 * The body for `POST /api/house/rooms`. Tools are sent only when a proposal
 * for this exact project was shown and had tools in it; otherwise the room
 * uses its agent's tools.
 */
export function newRoom(fields: RoomFields, picks: ToolPicks | null): NewRoom {
  const room: NewRoom = { name: fields.name.trim(), agent: fields.agent, at: fields.at };
  const project = fields.project.trim();
  const model = fields.model.trim();
  if (project) room.project = project;
  if (model) room.model = model;
  if (project && picks && picks.project === project && picks.tools.length > 0) {
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
