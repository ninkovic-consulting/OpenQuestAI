// What makes an unfurnished room look lived in: a rug or floor inset, a lamp
// and a painting. All geometry goes into the room's merge buckets.

import * as THREE from "three";
import type { Room } from "../net/types";
import { canvasTexture } from "./canvas";
import type { Materials } from "./materials";
import { box } from "./shapes";

export type Add = (material: THREE.Material, geometry: THREE.BufferGeometry) => void;

export interface DecorContext {
  room: Room;
  /** Inner faces of the walls, in metres. */
  x0: number;
  z0: number;
  x1: number;
  z1: number;
  doors: THREE.Vector2[];
  add: Add;
  mats: Materials;
  glow: THREE.Material;
}

const RUG_BORDER = new THREE.MeshStandardMaterial({ color: 0x6e4a17, roughness: 0.9 });
/** Tints over the carpet texture, so neighbouring rugs differ. */
const RUG_TINTS = [0x6f9a86, 0xc9a070, 0x8a8fb8, 0xb0605a];
const rugs = new Map<number, THREE.MeshStandardMaterial>();

function rugMaterial(mats: Materials, variant: number): THREE.MeshStandardMaterial {
  const tint = RUG_TINTS[variant % RUG_TINTS.length] ?? 0xffffff;
  let material = rugs.get(tint);
  if (!material) {
    material = mats.surface("red-carpet").clone();
    material.color.set(tint);
    rugs.set(tint, material);
  }
  return material;
}

export function floorDressing(ctx: DecorContext, variant: number): void {
  const { x0, z0, x1, z1, add, mats } = ctx;
  if (ctx.room.floor === "red-carpet") {
    const band = 0.42;
    const y: [number, number] = [0, 0.012];
    add(mats.surface("wood-floor"), box(x0, y[0], z0, x1, y[1], z0 + band));
    add(mats.surface("wood-floor"), box(x0, y[0], z1 - band, x1, y[1], z1));
    add(mats.surface("wood-floor"), box(x0, y[0], z0 + band, x0 + band, y[1], z1 - band));
    add(mats.surface("wood-floor"), box(x1 - band, y[0], z0 + band, x1, y[1], z1 - band));
    return;
  }
  // Stone floors carry their own pattern; a rug only softens wood.
  if (ctx.room.floor !== "wood-floor") return;
  const margin = Math.min(1.25, (x1 - x0) * 0.27, (z1 - z0) * 0.27);
  add(RUG_BORDER, box(x0 + margin, 0, z0 + margin, x1 - margin, 0.01, z1 - margin));
  add(rugMaterial(mats, variant), box(x0 + margin + 0.14, 0, z0 + margin + 0.14, x1 - margin - 0.14, 0.016, z1 - margin - 0.14));
}

/** A standing lamp in the corner farthest from any door. Returns where its light sits. */
export function lamp(ctx: DecorContext): THREE.Vector3 {
  const inset = 0.5;
  const corners = [
    new THREE.Vector2(ctx.x0 + inset, ctx.z0 + inset),
    new THREE.Vector2(ctx.x1 - inset, ctx.z0 + inset),
    new THREE.Vector2(ctx.x0 + inset, ctx.z1 - inset),
    new THREE.Vector2(ctx.x1 - inset, ctx.z1 - inset),
  ];
  const clearance = (c: THREE.Vector2): number => Math.min(...ctx.doors.map((d) => d.distanceTo(c)), 99);
  const spot = corners.find((c) => clearance(c) > 1.4) ?? corners.reduce((p, q) => (clearance(q) > clearance(p) ? q : p));
  const { x, y: z } = spot;
  const base = new THREE.CylinderGeometry(0.15, 0.18, 0.04, 20).translate(x, 0.02, z);
  const pole = new THREE.CylinderGeometry(0.022, 0.022, 1.3, 8).translate(x, 0.68, z);
  const shade = new THREE.CylinderGeometry(0.15, 0.27, 0.3, 20, 1, true).translate(x, 1.42, z);
  ctx.add(ctx.mats.bronze, base);
  ctx.add(ctx.mats.bronze, pole);
  ctx.add(ctx.glow, shade);
  return new THREE.Vector3(x, 1.38, z);
}

const PAINTINGS: THREE.Texture[] = [];

function paintingTexture(i: number): THREE.Texture {
  const cached = PAINTINGS[i];
  if (cached) return cached;
  const skies = [
    ["#1d2a3a", "#6b4a32"],
    ["#2a1a22", "#a0562e"],
    ["#14222a", "#3f5a52"],
  ] as const;
  const [top, bottom] = skies[i % skies.length] ?? skies[0];
  const tex = canvasTexture(128, (g) => {
    const sky = g.createLinearGradient(0, 0, 0, 128);
    sky.addColorStop(0, top);
    sky.addColorStop(1, bottom);
    g.fillStyle = sky;
    g.fillRect(0, 0, 128, 128);
    g.fillStyle = "rgba(240,220,170,0.8)";
    g.beginPath();
    g.arc(30 + i * 30, 34, 9, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "#151009";
    g.beginPath();
    g.moveTo(0, 128);
    for (let x = 0; x <= 128; x += 8) g.lineTo(x, 84 + Math.sin(x / 17 + i) * 12 + Math.sin(x / 7) * 4);
    g.lineTo(128, 128);
    g.fill();
  });
  PAINTINGS[i] = tex;
  return tex;
}

/** A framed painting on the north wall, away from any door. Returns the canvas mesh. */
export function painting(ctx: DecorContext, variant: number): THREE.Mesh | null {
  const w = 0.95;
  const h = 0.62;
  const z = ctx.z0;
  const options = [0, -1.2, 1.2].map((dx) => (ctx.x0 + ctx.x1) / 2 + dx);
  const cx = options.find((x) => ctx.doors.every((d) => Math.abs(d.y - z) > 0.4 || Math.abs(d.x - x) > 1.3));
  if (cx === undefined) return null;
  ctx.add(ctx.mats.gilt, box(cx - w / 2 - 0.06, 0.55, z, cx + w / 2 + 0.06, 0.55 + h + 0.12, z + 0.04));
  const canvas = new THREE.Mesh(
    new THREE.PlaneGeometry(w, h),
    new THREE.MeshStandardMaterial({ map: paintingTexture(variant), roughness: 0.7 }),
  );
  canvas.position.set(cx, 0.61 + h / 2, z + 0.042);
  return canvas;
}
