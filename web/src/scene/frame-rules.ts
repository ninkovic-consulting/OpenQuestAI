// What a drawn frame tells the pacing: how much of the scene is moving, and
// whether the shadow map and the room labels need redoing. The stage gathers
// the signals each frame; these rules decide. (The owner's own input is the
// pacer's to know: it wakes the loop directly.)

import { strongest, type Activity } from "./pacing";

/** What moved during a frame, as each part of the scene reports it. */
export interface FrameSignals {
  /** The camera moved: a drag, a zoom, its damping, a flight, the slide beside a card. */
  camera: boolean;
  /** A visible figure walks or fades. */
  figuresMoving: boolean;
  /** A visible figure plays its idle or working clip in place. */
  figuresAnimating: boolean;
  /** A room is rising into place. */
  rising: boolean;
  /** A room's lamp is easing toward its state, or flickers with the voice. */
  lights: boolean;
  /** The miniature blur is easing between the house and a room. */
  blur: boolean;
  /** The streaks pulse with the voice. */
  voice: boolean;
  /** Always-there motion that needs no figure: the streaks' faint pulse, build mode's glowing slots. */
  ambient: boolean;
}

export const STILL: FrameSignals = {
  camera: false,
  figuresMoving: false,
  figuresAnimating: false,
  rising: false,
  lights: false,
  blur: false,
  voice: false,
  ambient: false,
};

/** The strongest activity a frame's signals show. */
export function activityOf(s: FrameSignals): Activity {
  let a: Activity = "still";
  if (s.ambient || s.figuresAnimating) a = strongest(a, "ambient");
  if (s.figuresMoving || s.rising || s.lights || s.blur || s.voice) a = strongest(a, "motion");
  if (s.camera) a = strongest(a, "interaction");
  return a;
}

/** A figure's idle sway redraws its shadow at most this often a second; nobody sees a few centimetres of sway lag. */
export const SWAY_SHADOWS_PER_S = 6;

/**
 * Whether the shadow map must be drawn again this frame: always after the
 * scene was rebuilt or reloaded (`forced`), whenever something that casts a
 * shadow moved through the room, and now and then while a figure sways in
 * place. The static house alone never redraws it.
 */
export function shadowsDue(s: FrameSignals, forced: boolean, sinceMs: number): boolean {
  if (forced || s.figuresMoving || s.rising) return true;
  return s.figuresAnimating && sinceMs >= 1000 / SWAY_SHADOWS_PER_S;
}

/** Room labels follow the house at most this often a second when nothing about the view changed. */
export const LABEL_REFRESH_PER_S = 4;

/**
 * Whether the room labels need placing again: whenever the picture moved
 * under them (`stale` covers a resize and new room states), and a few times a
 * second otherwise so a chip whose text changed is checked for overlaps.
 */
export function labelsDue(s: FrameSignals, stale: boolean, sinceMs: number): boolean {
  if (stale || s.camera || s.rising) return true;
  return sinceMs >= 1000 / LABEL_REFRESH_PER_S;
}
