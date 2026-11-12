// One small store that the HUD and the scene both read. `reduce` is pure.

import type {
  AssistantState,
  BrainName,
  GateRequest,
  NoticeLevel,
  OutboundData,
  OutboundEvent,
  Plan,
  RoomLight,
  RunningAutomation,
  StateSnapshot,
} from "./types";

export type Connection = "connecting" | "open" | "offline";

export interface Caption {
  /** What the user said or typed; for an automation's run, the automation's name. */
  user: string;
  source: "voice" | "text" | "automation" | "phone" | null;
  reply: string;
  /** True while deltas are still streaming in. */
  streaming: boolean;
}

export interface Toast {
  id: number;
  level: NoticeLevel;
  text: string;
}

export interface ViewState {
  connection: Connection;
  assistant: AssistantState;
  brain: BrainName | null;
  budget: OutboundData["budget"] | null;
  plan: Plan | null;
  /** Latest revision announced by `house.changed`; above `plan.revision` means a reload is due. */
  houseRevision: number;
  /** Live room lighting; `room.state` events win over the plan's snapshot. */
  roomLights: Record<string, RoomLight>;
  caption: Caption;
  voiceLevel: number;
  gates: GateRequest[];
  toasts: Toast[];
  nextToastId: number;
  /** The automation running now, shown beside the assistant's state. */
  automation: RunningAutomation | null;
  /** Counts automation changes, so the Automations group knows to refetch. */
  automationsRevision: number;
}

export type Action =
  | { kind: "event"; event: OutboundEvent }
  | { kind: "plan"; plan: Plan }
  /** `initial` is the first snapshot of this page: its recent notices become toasts. */
  | { kind: "snapshot"; snapshot: StateSnapshot; initial: boolean }
  | { kind: "connection"; connection: Connection }
  | { kind: "toast"; level: NoticeLevel; text: string }
  | { kind: "dismiss"; id: number };

const MAX_TOASTS = 4;

export function initialState(): ViewState {
  return {
    connection: "connecting",
    assistant: "idle",
    brain: null,
    budget: null,
    plan: null,
    houseRevision: -1,
    roomLights: {},
    caption: { user: "", source: null, reply: "", streaming: false },
    voiceLevel: 0,
    gates: [],
    toasts: [],
    nextToastId: 1,
    automation: null,
    automationsRevision: 0,
  };
}

function addToast(s: ViewState, level: NoticeLevel, text: string): ViewState {
  const toast = { id: s.nextToastId, level, text };
  return { ...s, toasts: [...s.toasts, toast].slice(-MAX_TOASTS), nextToastId: s.nextToastId + 1 };
}

function addGate(s: ViewState, gate: GateRequest): ViewState {
  return { ...s, gates: [...s.gates.filter((g) => g.id !== gate.id), gate] };
}

function reduceEvent(s: ViewState, e: OutboundEvent): ViewState {
  switch (e.type) {
    case "state.changed":
      return {
        ...s,
        assistant: e.data.state,
        brain: e.data.brain ?? s.brain,
        voiceLevel: e.data.state === "speaking" ? s.voiceLevel : 0,
      };
    case "budget":
      return { ...s, budget: e.data };
    case "house.changed":
      return { ...s, houseRevision: Math.max(s.houseRevision, e.data.revision) };
    case "user.utterance":
      return {
        ...s,
        caption: { user: e.data.text, source: e.data.source, reply: "", streaming: false },
      };
    case "vision.delta": {
      const fresh = !s.caption.streaming;
      return {
        ...s,
        caption: {
          ...s.caption,
          reply: (fresh ? "" : s.caption.reply) + e.data.text,
          streaming: true,
        },
      };
    }
    case "vision.reply":
      return { ...s, caption: { ...s.caption, reply: e.data.text, streaming: false } };
    case "voice.level":
      return { ...s, voiceLevel: Math.min(1, Math.max(0, e.data.level)) };
    case "room.state":
      return { ...s, roomLights: { ...s.roomLights, [e.data.room]: e.data.state } };
    case "gate.request":
      return addGate(s, e.data);
    case "gate.resolved":
      return { ...s, gates: s.gates.filter((g) => g.id !== e.data.id) };
    case "brain.fallback":
      return addToast(
        { ...s, brain: e.data.to },
        "warn",
        `Switched from ${e.data.from} to ${e.data.to}: ${e.data.reason}`,
      );
    case "automation.changed":
      return { ...s, automationsRevision: s.automationsRevision + 1 };
    case "automation.started":
      return {
        ...s,
        automation: e.data,
        caption: { user: e.data.name, source: "automation", reply: "", streaming: false },
      };
    case "automation.finished":
      return { ...s, automation: s.automation?.id === e.data.id ? null : s.automation };
    case "notice":
      return addToast(s, e.data.level, e.data.text);
  }
}

function reducePlan(s: ViewState, plan: Plan): ViewState {
  const roomLights: Record<string, RoomLight> = {};
  for (const room of plan.rooms) roomLights[room.id] = s.roomLights[room.id] ?? room.state;
  return { ...s, plan, roomLights, houseRevision: Math.max(s.houseRevision, plan.revision) };
}

function reduceSnapshot(s: ViewState, snap: StateSnapshot, initial: boolean): ViewState {
  let next: ViewState = {
    ...s,
    assistant: snap.state,
    brain: snap.brain,
    budget: snap.budget,
    gates: [],
    automation: snap.automation ?? null,
  };
  for (const gate of snap.gate_pending) next = addGate(next, gate);
  if (initial) for (const notice of snap.notices) next = addToast(next, notice.level, notice.text);
  return next;
}

export function reduce(s: ViewState, a: Action): ViewState {
  switch (a.kind) {
    case "event":
      return reduceEvent(s, a.event);
    case "plan":
      return reducePlan(s, a.plan);
    case "snapshot":
      return reduceSnapshot(s, a.snapshot, a.initial);
    case "connection":
      return { ...s, connection: a.connection };
    case "toast":
      return addToast(s, a.level, a.text);
    case "dismiss":
      return { ...s, toasts: s.toasts.filter((t) => t.id !== a.id) };
  }
}

export type Listener = (state: ViewState, previous: ViewState) => void;

export class Store {
  private state = initialState();
  private readonly listeners = new Set<Listener>();

  get(): ViewState {
    return this.state;
  }

  dispatch(action: Action): void {
    const previous = this.state;
    this.state = reduce(previous, action);
    if (this.state !== previous) for (const l of this.listeners) l(this.state, previous);
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
