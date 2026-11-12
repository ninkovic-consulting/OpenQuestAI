// The wire protocol (spec section 5) and the house plan (spec section 4.8).
// Mirrors vision/core/events.py; the daemon is the source of truth.

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
  project: string | null;
  floor: string;
  wall: string;
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
  assistant: { name: string };
  agents: Agent[];
  rooms: Room[];
  doors: Door[];
  free_slots: Cell[];
}

// ------------------------------------------------------------ daemon -> window

export interface OutboundData {
  "state.changed": { state: AssistantState; brain: BrainName | null };
  budget: { month: string; spent_usd: number; cap_usd: number };
  "house.changed": { revision: number };
  "user.utterance": { text: string; source: "voice" | "text" };
  "vision.delta": { text: string };
  "vision.reply": { text: string; turn_id: string };
  "voice.level": { level: number };
  "room.state": { room: string; state: RoomLight };
  "gate.request": { id: string; tool: string; summary: string; detail: string; expires_at: number };
  "gate.resolved": { id: string; decision: "allow" | "deny" | "timeout" };
  "brain.fallback": { from: BrainName; to: BrainName; reason: string };
  notice: { level: NoticeLevel; text: string };
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
  gate_pending: OutboundEvent[];
  notices: OutboundEvent[];
  budget: OutboundData["budget"];
}

/** Body of `POST /api/house/rooms`. `at` is the free slot that was clicked. */
export interface NewRoom {
  name: string;
  agent: string;
  at: Cell;
  project?: string;
  model?: string;
}

export type PostResult = { ok: true } | { ok: false; message: string };

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
  "notice",
]);

/** Narrow raw JSON to an outbound event, or null when it is not one. */
export function asOutbound(raw: unknown): OutboundEvent | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { type, ts, data } = raw as Record<string, unknown>;
  if (typeof type !== "string" || !OUTBOUND_TYPES.has(type)) return null;
  if (typeof data !== "object" || data === null) return null;
  return { type, ts: typeof ts === "number" ? ts : Date.now() / 1000, data } as OutboundEvent;
}
