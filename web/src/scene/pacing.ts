// How often the scene draws. Each drawn frame reports the strongest activity
// in the scene (nothing, ambient motion, real motion, or the owner moving
// the view); the quality level gives each a rate. While the assistant works
// on this Mac the scene steps back: its rates are capped, its sharpness is
// not. While the page is hidden it draws nothing at all.

import type { ViewState } from "../net/store";
import { ratesFor, type Quality } from "./quality";

export type Activity = "still" | "ambient" | "motion" | "interaction";

const RANK: Record<Activity, number> = { still: 0, ambient: 1, motion: 2, interaction: 3 };

/** The stronger of two activities. */
export function strongest(a: Activity, b: Activity): Activity {
  return RANK[b] > RANK[a] ? b : a;
}

export interface PaceInput {
  visible: boolean;
  activity: Activity;
  stepBack: boolean;
  quality: Quality;
}

export interface Pace {
  /** Frames a second: 0 draws nothing until something changes, Infinity draws on every display tick. */
  fps: number;
  /** The state in words, for the readout. */
  label: string;
}

const WORDS: Record<Activity, string> = { still: "still", ambient: "idle", motion: "moving", interaction: "interacting" };

/** The rate to draw at now. */
export function decidePace(p: PaceInput): Pace {
  if (!p.visible) return { fps: 0, label: "paused (hidden or covered)" };
  const word = WORDS[p.activity];
  const prefix = p.stepBack ? "stepped back · " : "";
  if (p.activity === "still") return { fps: 0, label: `${prefix}still` };
  const fps = ratesFor(p.quality, p.stepBack)[p.activity];
  return { fps, label: `${prefix}${word} ${fps === Infinity ? "display rate" : `${fps}/s`}` };
}

/**
 * Whether the assistant is using this Mac's GPU now: its voice is speaking
 * (the voice is made on the Mac, and a local model's reply streams while it
 * speaks), a local model is thinking, or offline mode has a local model
 * working on a resident's job.
 */
export function workingHere(s: Pick<ViewState, "assistant" | "brain" | "mode" | "agents">): boolean {
  if (s.assistant === "speaking") return true;
  const local = s.mode?.answering === "local";
  if (s.assistant === "thinking" && (local || s.brain === "local")) return true;
  return local && Object.values(s.agents).some((a) => a.state === "working");
}

/** Slack allowed when a display tick arrives a little early for the next frame, in milliseconds. */
export const SLACK_MS = 4;

/** Whether a frame due at `next` may be drawn at `now`. */
export function due(now: number, next: number): boolean {
  return now >= next - SLACK_MS;
}

/** When the frame after one drawn at `now` is due, keeping an even rhythm without falling behind. */
export function nextDue(next: number, now: number, fps: number): number {
  if (fps === Infinity || fps <= 0) return now;
  const interval = 1000 / fps;
  const following = next + interval;
  return following < now - SLACK_MS ? now + interval : following;
}
