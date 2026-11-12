// Editing one room, apart from the DOM: the editable values a room starts
// with, and the PATCH body with only what changed.

import { hostAgentId, roomAgents } from "../../net/plan";
import type { RoomPatch } from "../../net/settings-types";
import type { Agent, Plan, Room } from "../../net/types";
import { pickedIds, type ToolPicks } from "../room-form";

export interface RoomEdit {
  name: string;
  agent: string;
  project: string;
  /** "" is the agent's own model. */
  model: string;
}

/** A room's values; a model equal to its agent's counts as the agent's own. */
export function roomEditFrom(plan: Plan, room: Room): RoomEdit {
  const agent = plan.agents.find((a) => a.id === room.agent);
  return { name: room.name, agent: room.agent, project: room.project ?? "", model: agent && room.model === agent.model ? "" : room.model };
}

/** The Hall belongs to the host and keeps it. */
export function isHostRoom(plan: Plan, room: Room): boolean {
  return room.id === "hall" || (room.agent === hostAgentId(plan) && !plan.rooms.some((r) => r.id === "hall"));
}

/** Who may run this room: nobody else for the Hall; everyone but the host for the rest. */
export function agentsFor(plan: Plan, room: Room): Agent[] {
  if (isHostRoom(plan, room)) return plan.agents.filter((a) => a.id === room.agent);
  return roomAgents(plan);
}

/**
 * The body for `PATCH /api/house/rooms/{id}`. Clearing the folder clears the
 * project tools too; tools are sent when the folder changed or a toggle was
 * pressed, and only for a proposal of this exact folder.
 */
export function roomPatch(before: RoomEdit, edit: RoomEdit, picks: ToolPicks | null, toolsTouched: boolean, hostRoom: boolean): RoomPatch {
  const patch: RoomPatch = {};
  const name = edit.name.trim();
  const project = edit.project.trim();
  if (name !== before.name) patch.name = name;
  if (!hostRoom && edit.agent !== before.agent) patch.agent = edit.agent;
  if (edit.model !== before.model) patch.model = edit.model === "" ? null : edit.model;
  if (project !== before.project) patch.project = project === "" ? null : project;
  if (project === "" && before.project !== "") patch.tools = null;
  else if (project !== "" && picks && picks.project === project && picks.tools.length > 0 && (toolsTouched || project !== before.project)) {
    patch.tools = pickedIds(picks);
  }
  return patch;
}
