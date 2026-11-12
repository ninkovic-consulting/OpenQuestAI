// The first-start wizard's steps and how Back, Skip and Continue move
// through them, apart from the DOM.

export const STEPS = ["welcome", "key", "downloads", "microphone", "name", "room", "done"] as const;
export type StepId = (typeof STEPS)[number];

export const STEP_TITLES: Record<StepId, string> = {
  welcome: "Welcome",
  key: "API key",
  downloads: "Downloads",
  microphone: "Microphone",
  name: "Name",
  room: "A project room",
  done: "Done",
};

/** How a step ended, for the summary. */
export interface Outcome {
  status: "done" | "skipped";
  text: string;
}

export interface Flow {
  index: number;
  outcomes: Partial<Record<StepId, Outcome>>;
}

/** The steps that set something up; the summary lists these. */
const TASKS: readonly StepId[] = STEPS.filter((s) => s !== "welcome" && s !== "done");
const LAST = STEPS.length - 1;

export const startFlow = (): Flow => ({ index: 0, outcomes: {} });

export function stepOf(flow: Flow): StepId {
  return STEPS[Math.min(Math.max(flow.index, 0), LAST)] ?? "welcome";
}

export function stepCount(flow: Flow): string {
  return `Step ${flow.index + 1} of ${STEPS.length}`;
}

/** Continue: keep how this step ended and go to the next. */
export function forward(flow: Flow, outcome?: Outcome): Flow {
  const step = stepOf(flow);
  const outcomes = outcome && TASKS.includes(step) ? { ...flow.outcomes, [step]: outcome } : flow.outcomes;
  return { index: Math.min(flow.index + 1, LAST), outcomes };
}

/** Skip: on the welcome step, skip the whole setup to the summary; elsewhere this step only. */
export function skip(flow: Flow): Flow {
  const step = stepOf(flow);
  if (step === "welcome") {
    const outcomes = { ...flow.outcomes };
    for (const t of TASKS) outcomes[t] ??= { status: "skipped", text: "Skipped" };
    return { index: LAST, outcomes };
  }
  if (step === "done") return flow;
  return forward(flow, { status: "skipped", text: "Skipped" });
}

export function back(flow: Flow): Flow {
  return { ...flow, index: Math.max(0, flow.index - 1) };
}

/** Each task with how it ended; a step never reached counts as skipped. */
export function summary(flow: Flow): { id: StepId; title: string; outcome: Outcome }[] {
  return TASKS.map((id) => ({ id, title: STEP_TITLES[id], outcome: flow.outcomes[id] ?? { status: "skipped", text: "Not reached" } }));
}
