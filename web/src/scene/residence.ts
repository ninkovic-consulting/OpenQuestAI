// Which room each figure stands in and what it is doing. A resident on a job
// is in the job's room, which may be another resident's (any room but the
// Hall); otherwise an agent with several rooms shows up in
// one: the first that is active, else its first room in plan order. The
// residents list in the panel names the same room.

import type { AgentStatus, AgentWork, Job } from "../net/job-types";
import type { Plan, Room, RoomLight } from "../net/types";
import { characterOf } from "./cast";

/** The part of the job board that says where residents work. */
export interface Board {
  agents: Readonly<Record<string, AgentStatus>>;
  jobs: Readonly<Record<string, Job>>;
}

export const NO_BOARD: Board = { agents: {}, jobs: {} };

export interface Residence {
  agent: string;
  room: Room;
  light: RoomLight;
  work: AgentWork;
  /** The job the agent is on, if any. */
  job: Job | null;
}

/** The room an agent is in, with its light and its work; null when the agent runs no room. */
export function residenceOf(plan: Plan, agent: string, lights: Readonly<Record<string, RoomLight>>, board: Board = NO_BOARD): Residence | null {
  const status = board.agents[agent];
  const work = status?.state ?? "idle";
  const job = work !== "idle" && status?.job ? (board.jobs[status.job] ?? null) : null;
  const rooms = plan.rooms.filter((r) => r.agent === agent);
  const light = (r: Room): RoomLight => lights[r.id] ?? r.state;
  const room = plan.rooms.find((r) => job !== null && r.id === job.room) ?? rooms.find((r) => light(r) === "active") ?? rooms[0];
  return room ? { agent, room, light: light(room), work, job } : null;
}

/** Where every agent that has a figure stands, in the plan's agent order. */
export function residences(plan: Plan, lights: Readonly<Record<string, RoomLight>>, board: Board = NO_BOARD): Residence[] {
  return plan.agents
    .filter((a) => characterOf(a.id) !== null)
    .map((a) => residenceOf(plan, a.id, lights, board))
    .filter((r): r is Residence => r !== null);
}
