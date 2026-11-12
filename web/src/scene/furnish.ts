// One or two built pieces for each default room, so idle rooms read from
// above: shelves of books, a long table, a counter, a desk with dark screens.
// Made from boxes and cylinders with the house's own textures. Pieces stand
// against a wall with no door; extra rooms are left as they are. Each room
// names its main piece, the one its resident works at.

import * as THREE from "three";
import type { DecorContext } from "./decor";
import { box } from "./shapes";

type Side = "n" | "w" | "e" | "s";
/** A wall to stand against, or the middle of the floor. */
type Anchor = Side | "floor";

/** Book spines, linen, felt and screen glass. */
const M = {
  books: [0x5a1a14, 0x1f3b33, 0x6b4a1e, 0x2a2440, 0x7a5a2a, 0x3b1d12].map(
    (color) => new THREE.MeshStandardMaterial({ color, roughness: 0.75 }),
  ),
  linen: new THREE.MeshStandardMaterial({ color: 0xd9ccb4, roughness: 0.9 }),
  felt: new THREE.MeshStandardMaterial({ color: 0x1d5a3e, roughness: 0.95 }),
  iron: new THREE.MeshStandardMaterial({ color: 0x23201d, roughness: 0.45, metalness: 0.6 }),
  screen: new THREE.MeshStandardMaterial({ color: 0x050a0b, roughness: 0.2, emissive: 0x2b6c78, emissiveIntensity: 0.35 }),
  drum: new THREE.MeshStandardMaterial({ color: 0x7a1d14, roughness: 0.55, metalness: 0.3 }),
};

/**
 * A frame against one wall: `u` runs along the wall from its middle, `v`
 * into the room from the wall face, `y` up from the floor. On the floor
 * anchor `u` runs east and `v` south from the room's centre.
 */
class Wall {
  constructor(
    private readonly ctx: DecorContext,
    readonly side: Anchor,
  ) {}

  get length(): number {
    const { x0, x1, z0, z1 } = this.ctx;
    return this.side === "w" || this.side === "e" ? z1 - z0 : x1 - x0;
  }

  box(material: THREE.Material, u0: number, u1: number, v0: number, v1: number, y0: number, y1: number): void {
    const [ax, az] = this.point(u0, v0);
    const [bx, bz] = this.point(u1, v1);
    this.ctx.add(material, box(Math.min(ax, bx), y0, Math.min(az, bz), Math.max(ax, bx), y1, Math.max(az, bz)));
  }

  /** A point on the floor, in metres. */
  at(u: number, v: number): THREE.Vector2 {
    return new THREE.Vector2(...this.point(u, v));
  }

  cylinder(material: THREE.Material, u: number, v: number, radius: number, y0: number, y1: number): void {
    const [x, z] = this.point(u, v);
    this.ctx.add(material, new THREE.CylinderGeometry(radius, radius, y1 - y0, 18).translate(x, (y0 + y1) / 2, z));
  }

  private point(u: number, v: number): [number, number] {
    const { x0, x1, z0, z1 } = this.ctx;
    const cx = (x0 + x1) / 2;
    const cz = (z0 + z1) / 2;
    switch (this.side) {
      case "n":
        return [cx + u, z0 + v];
      case "s":
        return [cx - u, z1 - v];
      case "w":
        return [x0 + v, cz - u];
      case "e":
        return [x1 - v, cz + u];
      case "floor":
        return [cx + u, cz + v];
    }
  }
}

/** The first wall, in order of preference, that has no door in it. */
function freeWall(ctx: DecorContext, prefer: Side[] = ["n", "w", "e", "s"]): Wall {
  const onWall = (side: Side): boolean =>
    ctx.doors.some((d) =>
      side === "n" ? Math.abs(d.y - ctx.z0) < 0.4 : side === "s" ? Math.abs(d.y - ctx.z1) < 0.4 : side === "w" ? Math.abs(d.x - ctx.x0) < 0.4 : Math.abs(d.x - ctx.x1) < 0.4,
    );
  return new Wall(ctx, prefer.find((s) => !onWall(s)) ?? prefer[0] ?? "n");
}

function centre(ctx: DecorContext): Wall {
  return new Wall(ctx, "floor");
}

function seeded(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function bookcase(w: Wall, ctx: DecorContext, u0: number, u1: number, seed: number): void {
  const wood = ctx.mats.wood;
  const depth = 0.36;
  const top = 1.12;
  w.box(wood, u0, u1, 0, 0.03, 0, top);
  w.box(wood, u0, u0 + 0.04, 0, depth, 0, top);
  w.box(wood, u1 - 0.04, u1, 0, depth, 0, top);
  w.box(ctx.mats.capWood, u0 - 0.02, u1 + 0.02, 0, depth + 0.02, top, top + 0.04);
  const rand = seeded(seed);
  for (const shelf of [0.06, 0.42, 0.78]) {
    w.box(wood, u0 + 0.04, u1 - 0.04, 0.03, depth, shelf, shelf + 0.03);
    let u = u0 + 0.06;
    while (u < u1 - 0.1) {
      const width = 0.035 + rand() * 0.045;
      const height = 0.22 + rand() * 0.1;
      const material = M.books[Math.floor(rand() * M.books.length)] ?? wood;
      if (rand() > 0.08) w.box(material, u, u + width, 0.06, depth - 0.03 - rand() * 0.04, shelf + 0.03, shelf + 0.03 + height);
      u += width + 0.004;
    }
  }
}

function table(w: Wall, ctx: DecorContext, u0: number, u1: number, v0: number, v1: number, height: number): void {
  w.box(ctx.mats.capWood, u0, u1, v0, v1, height - 0.05, height);
  const inset = 0.08;
  for (const [u, v] of [
    [u0 + inset, v0 + inset],
    [u1 - inset, v0 + inset],
    [u0 + inset, v1 - inset],
    [u1 - inset, v1 - inset],
  ] as const)
    w.box(ctx.mats.wood, u - 0.035, u + 0.035, v - 0.035, v + 0.035, 0, height - 0.05);
}

function chair(w: Wall, ctx: DecorContext, u: number, v: number, backAway: boolean): void {
  w.box(ctx.mats.wood, u - 0.22, u + 0.22, v - 0.22, v + 0.22, 0.42, 0.47);
  for (const du of [-0.18, 0.18]) for (const dv of [-0.18, 0.18]) w.box(ctx.mats.wood, u + du - 0.02, u + du + 0.02, v + dv - 0.02, v + dv + 0.02, 0, 0.42);
  const back = backAway ? v + 0.2 : v - 0.24;
  w.box(ctx.mats.wood, u - 0.22, u + 0.22, back, back + 0.04, 0.47, 0.92);
}

/** Builds a room's pieces and returns the middle of its main piece on the floor. */
const FURNISH: Record<string, (ctx: DecorContext) => THREE.Vector2> = {
  library(ctx) {
    const w = freeWall(ctx, ["n", "w", "s", "e"]);
    const half = w.length / 2 - 0.85;
    bookcase(w, ctx, -half, half, 3);
    const side = freeWall(ctx, ["w", "s", "e"]);
    if (side.side !== w.side) bookcase(side, ctx, -0.9, 0.9, 11);
    const c = centre(ctx);
    c.cylinder(ctx.mats.capWood, 0.3, 0.4, 0.42, 0.62, 0.66);
    c.cylinder(ctx.mats.wood, 0.3, 0.4, 0.05, 0, 0.62);
    return w.at(0, 0.18);
  },

  "control-room"(ctx) {
    const w = freeWall(ctx, ["n", "e", "w"]);
    const half = Math.min(1.9, w.length / 2 - 0.9);
    w.box(ctx.mats.capWood, -half, half, 0, 0.78, 0.72, 0.77);
    w.box(ctx.mats.wood, -half, -half + 0.5, 0.04, 0.74, 0, 0.72);
    w.box(ctx.mats.wood, half - 0.5, half, 0.04, 0.74, 0, 0.72);
    for (const u of [-1.05, 0, 1.05].filter((x) => Math.abs(x) < half - 0.3)) {
      w.box(M.iron, u - 0.05, u + 0.05, 0.16, 0.24, 0.77, 0.86);
      w.box(M.iron, u - 0.4, u + 0.4, 0.08, 0.14, 0.86, 1.32);
      w.box(M.screen, u - 0.36, u + 0.36, 0.14, 0.15, 0.9, 1.28);
    }
    chair(w, ctx, -0.55, 1.25, true);
    chair(w, ctx, 0.55, 1.25, true);
    return w.at(0, 0.39);
  },

  "comms-room"(ctx) {
    const w = freeWall(ctx, ["n", "e", "s"]);
    table(w, ctx, -0.9, 0.9, 0.04, 0.7, 0.76);
    w.box(M.iron, -0.55, 0.15, 0.1, 0.42, 0.76, 1.08);
    w.box(M.screen, -0.5, -0.1, 0.42, 0.43, 0.82, 1.02);
    w.cylinder(ctx.mats.gilt, 0.06, 0.3, 0.05, 0.76, 1.0);
    w.box(ctx.mats.capWood, 0.3, 0.75, 0.15, 0.5, 0.76, 0.82);
    chair(w, ctx, -0.2, 1.1, true);
    return w.at(0, 0.37);
  },

  kitchen(ctx) {
    const w = freeWall(ctx, ["w", "n", "s"]);
    const half = w.length / 2 - 0.9;
    w.box(ctx.mats.wood, -half, half, 0, 0.6, 0, 0.86);
    w.box(ctx.mats.capStone, -half - 0.02, half + 0.02, 0, 0.64, 0.86, 0.9);
    w.box(M.iron, -0.45, 0.45, 0.02, 0.62, 0.9, 0.95);
    for (const u of [-0.22, 0.22]) w.cylinder(M.iron, u, 0.3, 0.12, 0.95, 1.08);
    const c = centre(ctx);
    table(c, ctx, -0.45, 0.45, -0.9, 0.9, 0.86);
    return w.at(0, 0.32);
  },

  "game-room"(ctx) {
    const c = centre(ctx);
    const [hu, hv] = ctx.z1 - ctx.z0 > ctx.x1 - ctx.x0 ? [0.72, 1.3] : [1.3, 0.72];
    c.box(ctx.mats.capWood, -hu, hu, -hv, hv, 0.68, 0.8);
    c.box(M.felt, -hu + 0.1, hu - 0.1, -hv + 0.1, hv - 0.1, 0.8, 0.815);
    for (const u of [-hu + 0.15, hu - 0.15]) for (const v of [-hv + 0.15, hv - 0.15]) c.box(ctx.mats.wood, u - 0.07, u + 0.07, v - 0.07, v + 0.07, 0, 0.68);
    c.cylinder(M.linen, 0.1, -0.4, 0.03, 0.815, 0.875);
    c.cylinder(M.drum, -0.2, 0.3, 0.03, 0.815, 0.875);
    return c.at(0, 0);
  },

  garage(ctx) {
    const w = freeWall(ctx, ["w", "n", "e"]);
    table(w, ctx, -1.1, 1.1, 0.02, 0.72, 0.9);
    w.box(ctx.mats.wood, -1.1, 1.1, 0, 0.03, 0.9, 1.25);
    for (const u of [-0.7, -0.4, 0.2, 0.6]) w.box(M.iron, u - 0.03, u + 0.03, 0.03, 0.07, 1.0, 1.2);
    w.cylinder(M.drum, 1.45, 0.35, 0.28, 0, 0.88);
    return w.at(0, 0.37);
  },

  workshop(ctx) {
    const c = centre(ctx);
    const half = Math.min(1.9, (ctx.x1 - ctx.x0) / 2 - 1.1);
    table(c, ctx, -half, half, -0.5, 0.5, 0.88);
    c.box(M.iron, -half + 0.3, -half + 0.8, -0.3, 0.1, 0.88, 1.02);
    c.box(ctx.mats.capStone, 0.1, 0.5, -0.2, 0.25, 0.88, 0.94);
    c.cylinder(ctx.mats.gilt, half - 0.5, 0.1, 0.07, 0.88, 1.08);
    for (const u of [-1, 0, 1].map((k) => k * half * 0.6)) c.cylinder(ctx.mats.wood, u, 0.85, 0.17, 0, 0.62);
    // The vice at the bench's west end.
    return c.at(-half + 0.55, -0.1);
  },

  "spare-room"(ctx) {
    const w = freeWall(ctx, ["n", "e", "w"]);
    w.box(ctx.mats.wood, -0.8, 0.8, 0, 0.08, 0, 1.0);
    w.box(ctx.mats.wood, -0.8, 0.8, 0.08, 2.1, 0.12, 0.36);
    w.box(M.linen, -0.75, 0.75, 0.1, 2.05, 0.36, 0.52);
    w.box(ctx.mats.surface("red-carpet"), -0.78, 0.78, 0.8, 2.08, 0.5, 0.56);
    for (const u of [-0.38, 0.38]) w.box(M.linen, u - 0.3, u + 0.3, 0.16, 0.5, 0.52, 0.64);
    w.box(ctx.mats.wood, 0.95, 1.4, 0.04, 0.48, 0, 0.56);
    return w.at(0, 1.1);
  },
};

/** Furnish a default room. Returns the middle of its main piece, or null when there is nothing to build for it. */
export function furnish(ctx: DecorContext): THREE.Vector2 | null {
  if (ctx.room.kind !== "default") return null;
  const build = FURNISH[ctx.room.id];
  return build ? build(ctx) : null;
}
