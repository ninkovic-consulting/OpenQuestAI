// Mock mode's scene tour (`?mock=1&tour=1`): walks the scene through each
// pacing state in turn so the readout can be checked against it: the house at
// rest, a camera move into a room where a figure paces, the assistant
// thinking and then speaking on the local model, and back to rest. The last
// step asks for the page to be hidden, which only the owner can do.

import type { BrainMode } from "../net/brain-types";
import type { Store } from "../net/store";
import type { OutboundData, OutboundEvent, OutboundType } from "../net/types";

/** Seconds before the first step, while mock mode plays its opening exchange. */
const START_S = 16;
/** Seconds each step lasts. */
const STEP_S = 6;

export interface TourStage {
  focusRoom(id: string): boolean;
  home(): boolean;
}

export function runTour(store: Store, stage: TourStage): void {
  const emit = <K extends OutboundType>(type: K, data: OutboundData[K]): void =>
    store.dispatch({ kind: "event", event: { type, ts: Date.now() / 1000, data } as OutboundEvent });
  const say = (text: string): void => store.dispatch({ kind: "toast", level: "info", text: `Scene tour: ${text}` });
  const mode = (answering: BrainMode["answering"]): BrainMode => ({
    offline: answering === "local",
    answering,
    local_backend: store.get().mode?.local_backend ?? "mlx",
    local_model: store.get().mode?.local_model ?? "local model",
    local_tools: store.get().mode?.local_tools ?? null,
  });
  let pulse = 0;

  const steps: (() => void)[] = [
    () => say("the house at rest."),
    () => {
      say("a camera move into a room where a figure paces.");
      stage.focusRoom(pacingRoom(store) ?? store.get().plan?.rooms[0]?.id ?? "");
    },
    () => say("a figure pacing at work."),
    () => {
      stage.home();
      say("the assistant thinking on the local model; the scene steps back.");
      emit("brain.mode", mode("local"));
      emit("state.changed", { state: "thinking", brain: "local" });
    },
    () => {
      say("the local model speaking; the scene stays stepped back.");
      emit("state.changed", { state: "speaking", brain: "local" });
      pulse = window.setInterval(() => emit("voice.level", { level: 0.3 + Math.random() * 0.6 }), 90);
    },
    () => {
      window.clearInterval(pulse);
      emit("state.changed", { state: "idle", brain: "claude" });
      emit("brain.mode", mode("claude"));
      say("back at rest, at full resolution.");
    },
    () => say("now hide the page (another tab, or minimise): the scene stops drawing."),
  ];
  steps.forEach((step, i) => window.setTimeout(step, (START_S + i * STEP_S) * 1000));
}

/** The room of a resident at work on a job, where its figure paces. */
function pacingRoom(store: Store): string | null {
  const s = store.get();
  for (const status of Object.values(s.agents)) {
    if (status.state !== "working" || status.job === null) continue;
    const room = s.jobs[status.job]?.room;
    if (room) return room;
  }
  return null;
}
