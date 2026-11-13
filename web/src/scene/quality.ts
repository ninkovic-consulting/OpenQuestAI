// The scene's quality levels: how sharp it draws, how smooth its edges are,
// and how often it draws for each kind of motion. Balanced is the default and
// looks the same as High; Low trades sharpness and smoothness for GPU time.

export type Quality = "low" | "balanced" | "high";

export const QUALITIES: readonly Quality[] = ["low", "balanced", "high"];

/** Frames drawn per second for each kind of activity; Infinity is the display's own rate. */
export interface Rates {
  /** Only the always-there motion: idle figures, the faint streaks, build mode's pulse. */
  ambient: number;
  /** A figure pacing or fading, lights easing, a room rising, the blur easing. */
  motion: number;
  /** The camera moving, the owner's pointer on the scene, a resize. */
  interaction: number;
}

export interface QualityLevel {
  label: string;
  /** What the level does, in one line for Settings. */
  summary: string;
  /** The sharpest pixel ratio drawn; the display's own ratio caps it too. */
  maxPixelRatio: number;
  /** How far below that the automatic scaler may go, as a share of it. */
  minScale: number;
  /** Multisampling of the scene's render, for smooth edges; 0 is none. */
  multisampling: number;
  /** Multisampling once the pixel ratio is at least RETINA_RATIO, where half the samples look the same. */
  retinaMultisampling: number;
  /** Resolution of the tilt-shift blur and the bloom, as a share of the frame's. */
  effectScale: number;
  /** Size of the moon's shadow map, in texels a side. */
  shadowMapSize: number;
  rates: Rates;
}

export const LEVELS: Readonly<Record<Quality, QualityLevel>> = {
  low: {
    label: "Low",
    summary: "Standard resolution, no edge smoothing, softer shadows and glow, 20 frames a second at rest.",
    maxPixelRatio: 1,
    minScale: 0.75,
    multisampling: 0,
    retinaMultisampling: 0,
    effectScale: 0.25,
    shadowMapSize: 1024,
    rates: { ambient: 20, motion: 30, interaction: 60 },
  },
  balanced: {
    label: "Balanced",
    summary: "Full sharpness on Retina, 24 frames a second at rest, 60 while figures walk, the display's rate while you move the view.",
    maxPixelRatio: 2,
    minScale: 0.7,
    multisampling: 4,
    retinaMultisampling: 2,
    effectScale: 0.5,
    shadowMapSize: 2048,
    rates: { ambient: 24, motion: 60, interaction: Infinity },
  },
  high: {
    label: "High",
    summary: "Full sharpness, 30 frames a second at rest and the display's rate for anything that moves.",
    maxPixelRatio: 2,
    minScale: 0.85,
    multisampling: 4,
    retinaMultisampling: 4,
    effectScale: 0.5,
    shadowMapSize: 2048,
    rates: { ambient: 30, motion: Infinity, interaction: Infinity },
  },
};

/** While the assistant works on this Mac: the lightest pacing and resolution, whatever the level. */
export const STEP_BACK: { rates: Rates; maxPixelRatio: number } = {
  rates: { ambient: 12, motion: 20, interaction: 30 },
  maxPixelRatio: 1,
};

export const DEFAULT_QUALITY: Quality = "balanced";

/** From this pixel ratio on, edges are fine enough that fewer samples look the same. */
export const RETINA_RATIO = 1.5;

/** The multisampling to draw with at a pixel ratio. */
export function samplesFor(level: QualityLevel, pixelRatio: number): number {
  return pixelRatio >= RETINA_RATIO ? level.retinaMultisampling : level.multisampling;
}

export function isQuality(v: unknown): v is Quality {
  return typeof v === "string" && (QUALITIES as readonly string[]).includes(v);
}

/** The pixel ratios the scene may draw at: the level's cap (lowered while stepping back) and the scaler's floor. */
export function pixelRatioRange(quality: Quality, devicePixelRatio: number, stepBack: boolean): { max: number; min: number } {
  const level = LEVELS[quality];
  const device = devicePixelRatio > 0 ? devicePixelRatio : 1;
  const cap = stepBack ? Math.min(level.maxPixelRatio, STEP_BACK.maxPixelRatio) : level.maxPixelRatio;
  const max = Math.min(cap, device);
  return { max, min: max * level.minScale };
}
