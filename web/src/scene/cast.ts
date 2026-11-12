// Which figure each agent wears, how tall it stands and how it works. The host
// is not here: it sits in the Hall's armchair (props.ts). An agent missing
// from this table has no figure.

/** What a figure plays while its room is active. Every figure idles on its clip named `Idle`. */
export interface WorkMotion {
  clip: string;
  /** The part of the clip to loop, in seconds; the whole clip when left out. */
  span?: readonly [number, number];
  /** Playback rate; below 1 is slower. */
  speed: number;
  /** Play the span forward then back, for a part that does not loop by itself. */
  pingPong: boolean;
  /** Bend the upper body forward by this angle, in radians, as over a bench. */
  lean: number;
}

export interface Character {
  /** The model under assets/models/agents/, without `.glb`. */
  model: string;
  /** Standing height, in metres. */
  height: number;
  work: WorkMotion;
}

export const IDLE_CLIP = "Idle";

const whole = (clip: string): WorkMotion => ({ clip, speed: 1, pingPong: false, lean: 0 });

export const CAST: Readonly<Record<string, Character>> = {
  // A host's open-handed "this way, please".
  steward: { model: "brass", height: 1.8, work: whole("Checkout_Gesture") },
  // Talking into a headset with her hands.
  envoy: { model: "wren", height: 1.68, work: whole("Phone_Conversation") },
  // The hammer swing is a fighting move made empty-handed: an overhead blow and
  // a lunge to the floor. He idles bent over his work instead.
  maker: { model: "tink", height: 1.78, work: { clip: IDLE_CLIP, speed: 1, pingPong: false, lean: 0.32 } },
  // Only the end of the pick-up: holding the find up, looking at it and
  // settling her glasses, slowed. The deep bend to the floor is left out.
  checker: {
    model: "tock",
    height: 1.66,
    work: { clip: "Female_Bend_Over_Pick_Up_Inspect", span: [2.8, 3.7], speed: 0.45, pingPong: true, lean: 0 },
  },
  // Breathing slowly and looking around the tower.
  scout: { model: "rook", height: 1.88, work: whole("Long_Breathe_and_Look_Around") },
};

export function characterOf(agentId: string): Character | null {
  return Object.hasOwn(CAST, agentId) ? (CAST[agentId] ?? null) : null;
}
