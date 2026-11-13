// What the room card and an agent's room list say, apart from the DOM: which
// jobs belong to a room, what is happening there, and what each room shows.

import { hostAgentId } from "../../net/plan";
import { isOpen, type Job } from "../../net/job-types";
import type { Agent, Plan, Room, RoomLight, ToolRef } from "../../net/types";
import type { Board } from "../../scene/residence";
import { modelShort } from "../agent-choice";
import { clock } from "../jobs/model";
import { projectLine, type ProjectLine } from "./project";

/** Built-in tools always run; a project tool needs its program on this Mac and at least one project folder on the room. */
export type ToolState = "runs" | "waits" | "missing";

export const TOOL_WORD: Record<ToolState, string> = { runs: "ready", waits: "needs a project folder", missing: "not installed" };

function toolState(tool: ToolRef, hasFolder: boolean): ToolState {
  if (tool.built_in) return "runs";
  if (!tool.available) return "missing";
  return hasFolder ? "runs" : "waits";
}

/** How far a job has got, from the board. */
export type JobPhase = "working" | "waiting" | "queued";

export const PHASE_WORD: Record<JobPhase, string> = { working: "working", waiting: "waiting for your yes", queued: "waiting to start" };

/** Every job done in a room, resident or visitor, requests included. */
export function jobsInRoom(jobs: Readonly<Record<string, Job>>, roomId: string): Job[] {
  return Object.values(jobs).filter((j) => j.room === roomId);
}

export interface ActiveJob {
  job: Job;
  phase: JobPhase;
}

function phaseOf(job: Job, board: Board): JobPhase {
  if (job.status === "queued") return "queued";
  const status = board.agents[job.agent];
  return status?.state === "waiting" && status.job === job.id ? "waiting" : "working";
}

const PHASE_ORDER: Record<JobPhase, number> = { waiting: 0, working: 1, queued: 2 };

/** The jobs working or waiting in a room: those blocked on the owner's yes first, then the working, then the queued; oldest first within each. */
export function activeIn(board: Board, roomId: string): ActiveJob[] {
  return jobsInRoom(board.jobs, roomId)
    .filter((j) => isOpen(j.status))
    .map((job) => ({ job, phase: phaseOf(job, board) }))
    .sort((a, b) => PHASE_ORDER[a.phase] - PHASE_ORDER[b.phase] || a.job.created_at - b.job.created_at);
}

/** How many finished jobs the card lists. */
export const RECENT_LIMIT = 3;

/** The last jobs that ended in a room, newest first. */
export function recentIn(jobs: Readonly<Record<string, Job>>, roomId: string, limit = RECENT_LIMIT): Job[] {
  const ended = (j: Job): number => j.ended_at ?? j.created_at;
  return jobsInRoom(jobs, roomId)
    .filter((j) => !isOpen(j.status))
    .sort((a, b) => ended(b) - ended(a))
    .slice(0, limit);
}

/** What the tools may do here; the Hall's own tools need no project. */
function toolsNote(hasFolder: boolean): string {
  return hasFolder
    ? "An agent working here reads and searches the project folders freely. Writing files and running these programs ask you first."
    : "Attach a project folder to this room and agents can work in it with these tools.";
}

export interface RoomCardModel {
  id: string;
  name: string;
  /** The Hall is the host's: it is spoken to in the chat, and takes no jobs. */
  hall: boolean;
  agent: { id: string; name: string; /** The model it thinks with in this room, briefly. */ model: string; modelId: string };
  /** What the card says of the project's name; null when the room has neither a name nor folders to suggest one from. */
  project: ProjectLine;
  folders: string[];
  tools: { title: string; state: ToolState }[];
  /** Empty for the Hall. */
  note: string;
  now: { id: string; title: string; who: string; visiting: boolean; phase: JobPhase; step: string | null }[];
  recent: { id: string; title: string; who: string; when: string; outcome: Job["status"] }[];
  /** What to offer under the job field: null in the Hall. */
  brief: { careful: string } | null;
}

/** What "careful" does for this agent, in a few words. */
export function carefulWords(agent: Pick<Agent, "heavy_model">): string {
  return agent.heavy_model ? `switches to ${modelShort(agent.heavy_model)}` : "thinks longer";
}

export function roomCardModel(plan: Plan, board: Board, roomId: string, now: number): RoomCardModel | null {
  const room = plan.rooms.find((r) => r.id === roomId);
  if (!room) return null;
  const agent = plan.agents.find((a) => a.id === room.agent);
  const name = (id: string): string => plan.agents.find((a) => a.id === id)?.name ?? id;
  const modelId = room.model || agent?.model || "";
  const hall = room.agent === hostAgentId(plan);
  return {
    id: room.id,
    name: room.name,
    hall,
    agent: { id: room.agent, name: agent?.name ?? room.agent, model: modelShort(modelId), modelId },
    project: projectLine(room),
    folders: [...room.folders],
    tools: room.tools.map((t) => ({ title: t.title, state: toolState(t, room.folders.length > 0) })),
    note: hall ? "" : toolsNote(room.folders.length > 0),
    now: activeIn(board, room.id).map(({ job, phase }) => ({
      id: job.id,
      title: job.title,
      who: name(job.agent),
      visiting: job.agent !== room.agent,
      phase,
      step: job.last_step?.text ?? null,
    })),
    recent: recentIn(board.jobs, room.id).map((j) => ({
      id: j.id,
      title: j.title,
      who: name(j.agent),
      when: clock(j.ended_at ?? j.created_at, now),
      outcome: j.status,
    })),
    brief: hall || !agent ? null : { careful: carefulWords(agent) },
  };
}

/** What a room is doing, for a list: a job's phase, else the room's light. */
export type RoomState = JobPhase | RoomLight;

export const ROOM_STATE_WORD: Record<RoomState, string> = { ...PHASE_WORD, active: "active", idle: "idle", dark: "dark" };

export interface AgentRoom {
  id: string;
  name: string;
  /** The room's project name, shown beside its name. */
  project: string | null;
  folders: number;
  state: RoomState;
  selected: boolean;
}

function roomState(room: Room, board: Board, lights: Readonly<Record<string, RoomLight>>): RoomState {
  return activeIn(board, room.id)[0]?.phase ?? lights[room.id] ?? room.state;
}

/** The rooms an agent runs, in plan order: the host's list is the Hall. */
export function agentRooms(plan: Plan, agent: string, board: Board, lights: Readonly<Record<string, RoomLight>>, selected: string | null): AgentRoom[] {
  return plan.rooms
    .filter((r) => r.agent === agent)
    .map((r) => ({ id: r.id, name: r.name, project: r.project, folders: r.folders.length, state: roomState(r, board, lights), selected: r.id === selected }));
}

/** "No project folders", "1 project folder", "3 project folders". */
export function folderWords(count: number): string {
  return count === 0 ? "no project folders" : `${count} project ${count === 1 ? "folder" : "folders"}`;
}

/** The selected room, or null once it is gone from the plan. */
export function selectionIn(plan: Plan | null, id: string | null): string | null {
  return id !== null && plan?.rooms.some((r) => r.id === id) ? id : null;
}

/** Which agent's list is open after the selection changed: the selected room's agent's, else the one already open. */
export function agentToOpen(plan: Plan | null, selected: string | null, open: string | null): string | null {
  const owner = selected === null ? undefined : plan?.rooms.find((r) => r.id === selected)?.agent;
  return owner ?? open;
}
