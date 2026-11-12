// Shared measurements, in metres. Floors are at y = 0.

export const DIM = {
  /** Interior walls are cut to this share of the plan's wall height. */
  interiorCut: 0.5,
  exteriorCut: 0.58,
  lining: 0.08,
  stone: 0.26,
  door: 1.1,
  window: 1.15,
  sill: 0.5,
  floorDepth: 0.12,
  plinthOverhang: 0.55,
  ground: -0.5,
  towerCut: 0.95,
} as const;

/** Where the host room's furniture stands, relative to the room centre (x east, z south). */
export const HOST_LAYOUT = {
  armchair: { x: 0, z: 0.3, turn: 0 },
  lamp: { x: -1.15, z: -0.35 },
  sideTable: { x: 1.05, z: 0.45 },
  staircase: { x: 0, z: -3.1, turn: Math.PI / 2 },
  cabinet: { x: -3.72, z: 0, turn: Math.PI / 2 },
} as const;
