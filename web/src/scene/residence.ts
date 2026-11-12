// Which room each figure stands in. An agent with several rooms shows up in
// one: the first that is active, else its first room in plan order. The
// residents list in the panel names the same room.

import type { Plan, Room, RoomLight } from "../net/types";
import { characterOf } from "./cast";

export interface Residence {
  agent: string;
  room: Room;
  light: RoomLight;
}

/** The room an agent is in, with its light; null when the agent runs no room. */
export function residenceOf(plan: Plan, agent: string, lights: Readonly<Record<string, RoomLight>>): Residence | null {
  const rooms = plan.rooms.filter((r) => r.agent === agent);
  const light = (r: Room): RoomLight => lights[r.id] ?? r.state;
  const room = rooms.find((r) => light(r) === "active") ?? rooms[0];
  return room ? { agent, room, light: light(room) } : null;
}

/** Where every agent that has a figure stands, in the plan's agent order. */
export function residences(plan: Plan, lights: Readonly<Record<string, RoomLight>>): Residence[] {
  return plan.agents
    .filter((a) => characterOf(a.id) !== null)
    .map((a) => residenceOf(plan, a.id, lights))
    .filter((r): r is Residence => r !== null);
}
