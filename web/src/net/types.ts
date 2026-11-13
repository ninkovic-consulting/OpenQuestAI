// The wire protocol (spec section 5) and the house plan (spec section 4.8).
// Mirrors vision/core/events.py; the daemon is the source of truth.

import { asBrainMode } from "./brain-guards";
import type { BrainMode } from "./brain-types";
import { asAgentState, asJob, gateFieldsOk } from "./job-guards";
import type { AgentWork, Job } from "./job-types";

export type AssistantState = "idle" | "listening" | "transcribing" | "thinking" | "speaking";
export type BrainName = "claude" | "local" | "fake";
export type RoomLight = "dark" | "idle" | "active";
export type NoticeLevel = "info" | "warn" | "error";
export type Side = "n" | "e" | "s" | "w";
export type Cell = readonly [number, number];

export interface Agent {
  id: string;
  name: string;
  model: string;
  heavy_model?: string | null;
  /** The thinking level for the model and for careful work. */
  effort?: string;
  heavy_effort?: string;
}

/** A tool on a room, as the plan carries it. Project tools run only in a room with at least one project folder. */
export interface ToolRef {
  id: string;
  title: string;
  /** Whether the program the tool needs is on this Mac; built-in tools always are. */
  available: boolean;
  built_in: boolean;
}

export interface Room {
  id: string;
  name: string;
  kind: "default" | "extra";
  shape: "rect" | "round";
  at: Cell;
  size: Cell;
  agent: string;
  model: string;
  /** The room's project folders as the owner gave them, for example `~/Projects/shop`; the first is where programs run. */
  folders: string[];
  floor: string;
  wall: string;
  /** The room's own tools, or its agent's when it lists none. */
  tools: ToolRef[];
  state: RoomLight;
}

export interface Door {
  a: string;
  b: string;
  cell: Cell;
  side: Side;
}

export interface Plan {
  revision: number;
  cell_m: number;
  wall_height_m: number;
  max_extra_rooms: number;
  /** The most project folders one room may have. */
  max_room_folders: number;
  assistant: { name: string };
  agents: Agent[];
  /** The thinking levels each model in the house takes; a model that takes none has an empty list. */
  effort_levels: Record<string, string[]>;
  rooms: Room[];
  doors: Door[];
  free_slots: Cell[];
}

// ------------------------------------------------------------ daemon -> window

export interface OutboundData {
  "state.changed": { state: AssistantState; brain: BrainName | null };
  budget: { month: string; spent_usd: number; cap_usd: number };
  "house.changed": { revision: number };
  "user.utterance": { text: string; source: "voice" | "text" | "phone" };
  "vision.delta": { text: string };
  "vision.reply": { text: string; turn_id: string };
  "voice.level": { level: number };
  "room.state": { room: string; state: RoomLight };
  /** A request made during a resident's job names the agent (id and name) and the job; the host's own leave them null. */
  "gate.request": {
    id: string;
    tool: string;
    summary: string;
    detail: string;
    expires_at: number;
    agent?: string | null;
    agent_name?: string | null;
    job?: string | null;
  };
  "gate.resolved": { id: string; decision: "allow" | "deny" | "timeout" };
  "brain.fallback": { from: BrainName; to: BrainName; reason: string };
  /** Offline mode or the local model changed. */
  "brain.mode": BrainMode;
  /** `automation` is null when deleted; `reloaded` (empty id) means refetch the whole list. */
  "automation.changed": { id: string; change: "created" | "updated" | "deleted" | "reloaded"; automation: unknown };
  "automation.started": { id: string; name: string };
  "automation.finished": { id: string; name: string; status: string; reply: string };
  "job.changed": Job;
  "agent.state": { agent: string; state: AgentWork; job: string | null };
  presence: Presence;
  notice: { level: NoticeLevel; text: string };
}

/** Whether the owner is at the Mac (`vision.presence`); unknown counts as present. */
export interface Presence {
  away: boolean;
  /** False when the Mac would not say. */
  known: boolean;
  reason: "idle" | "locked" | "asleep" | null;
  /** Unix seconds: when this state began. */
  since: number;
  away_after_s: number;
}

export type OutboundType = keyof OutboundData;

export type OutboundEvent = {
  [K in OutboundType]: { type: K; ts: number; data: OutboundData[K] };
}[OutboundType];

export type GateRequest = OutboundData["gate.request"];

// ------------------------------------------------------------ window -> daemon

export interface InboundData {
  hello: { token: string };
  "input.text": { text: string };
  "input.ptt": { down: boolean };
  "input.interrupt": Record<string, never>;
  "gate.decision": { id: string; decision: "allow" | "deny" };
}

export type InboundType = keyof InboundData;

export type InboundEvent = {
  [K in InboundType]: { type: K; ts: number; data: InboundData[K] };
}[InboundType];

export function envelope<K extends InboundType>(type: K, data: InboundData[K]): InboundEvent {
  return { type, ts: Date.now() / 1000, data } as InboundEvent;
}

// ------------------------------------------------------------ HTTP

/** `GET /api/state`: what a reconnecting window needs to redraw itself. */
export interface StateSnapshot {
  state: AssistantState;
  brain: BrainName;
  /** Pending requests, each shaped like a `gate.request` event's data. */
  gate_pending: GateRequest[];
  /** Recent notices, each shaped like a `notice` event's data. */
  notices: OutboundData["notice"][];
  budget: OutboundData["budget"];
  /** The automation running now, if any. */
  automation?: RunningAutomation | null;
  /** Offline mode and the local model. */
  mode?: BrainMode;
  presence?: Presence;
}

export type RunningAutomation = OutboundData["automation.started"];

/** Body of `POST /api/house/rooms`. `at` is the free slot that was clicked. */
export interface NewRoom {
  name: string;
  agent: string;
  at: Cell;
  /** Project folders, in order; left out, the room has none. */
  folders?: string[];
  model?: string;
  /** Tool ids; left out, the room uses its agent's. */
  tools?: string[];
}

export type PostResult = { ok: true } | { ok: false; message: string };

/** `GET /api/house/tools/propose`: the tools a project folder looks like it needs. */
export type ProposeResult = { ok: true; tools: ToolRef[] } | { ok: false; message: string };

const OUTBOUND_TYPES: ReadonlySet<string> = new Set<OutboundType>([
  "state.changed",
  "budget",
  "house.changed",
  "user.utterance",
  "vision.delta",
  "vision.reply",
  "voice.level",
  "room.state",
  "gate.request",
  "gate.resolved",
  "brain.fallback",
  "brain.mode",
  "automation.changed",
  "automation.started",
  "automation.finished",
  "job.changed",
  "agent.state",
  "presence",
  "notice",
]);

/** Events whose data the window relies on field by field are checked before they reach the store. */
const DATA_CHECKS: Partial<Record<OutboundType, (data: Record<string, unknown>) => boolean>> = {
  "job.changed": (d) => asJob(d) !== null,
  "agent.state": (d) => asAgentState(d) !== null,
  "brain.mode": (d) => asBrainMode(d) !== null,
  "gate.request": gateFieldsOk,
  presence: (d) => typeof d["away"] === "boolean" && typeof d["known"] === "boolean" && typeof d["since"] === "number",
};

/** Narrow raw JSON to an outbound event, or null when it is not one. */
export function asOutbound(raw: unknown): OutboundEvent | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { type, ts, data } = raw as Record<string, unknown>;
  if (typeof type !== "string" || !OUTBOUND_TYPES.has(type)) return null;
  if (typeof data !== "object" || data === null) return null;
  const check = DATA_CHECKS[type as OutboundType];
  if (check && !check(data as Record<string, unknown>)) return null;
  return { type, ts: typeof ts === "number" ? ts : Date.now() / 1000, data } as OutboundEvent;
}
