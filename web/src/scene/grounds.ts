// The garden the house sits in: a dark lawn, a stone terrace, clipped hedges
// with a gap for the front path, bushes, and lanterns along the path.

import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { glowTexture } from "./canvas";
import { DIM } from "./layout";
import { applyWorldUVs, Materials } from "./materials";
import { palette } from "./palette";
import { box, flat } from "./shapes";

export interface Bounds {
  x0: number;
  z0: number;
  x1: number;
  z1: number;
}

const TERRACE = 1.0;
const GARDEN = 7;
const HEDGE_H = 1.15;
const HEDGE_W = 1.0;
const PATH_W = 2.2;

export class Grounds {
  readonly root = new THREE.Group();
  private readonly lawn: THREE.MeshStandardMaterial;
  private readonly hedge: THREE.MeshStandardMaterial;
  private readonly lanternGlow: THREE.MeshStandardMaterial;
  private readonly spill: THREE.MeshBasicMaterial;

  constructor(private readonly mats: Materials) {
    this.root.name = "grounds";
    const lawnTex = Materials.foliage(palette.lawn, palette.lawnSpeck, 512, 9000);
    lawnTex.repeat.set(1 / 6, 1 / 6);
    this.lawn = new THREE.MeshStandardMaterial({ map: lawnTex, roughness: 1 });
    const hedgeTex = Materials.foliage(palette.hedge, palette.hedgeSpeck, 256, 5000);
    hedgeTex.repeat.set(1 / 1.6, 1 / 1.6);
    this.hedge = new THREE.MeshStandardMaterial({ map: hedgeTex, bumpMap: hedgeTex, bumpScale: 4, roughness: 0.95 });
    this.lanternGlow = new THREE.MeshStandardMaterial({ color: 0x2a1a0a, emissive: palette.lamp, emissiveIntensity: 4 });
    this.spill = new THREE.MeshBasicMaterial({
      color: palette.lamp,
      alphaMap: glowTexture(),
      transparent: true,
      opacity: 0.09,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
  }

  /** Lay the garden around the house's footprint, in metres. `door` is the x of the front path. */
  build(b: Bounds, door: number): void {
    this.clear();
    const g = DIM.ground;
    const lawn = new THREE.Mesh(flat((b.x0 + b.x1) / 2, g - 0.02, (b.z0 + b.z1) / 2, 260, 260), this.lawn);
    applyWorldUVs(lawn.geometry);
    lawn.receiveShadow = true;
    this.root.add(lawn);

    const stone: THREE.BufferGeometry[] = [];
    const t = TERRACE + DIM.plinthOverhang;
    stone.push(box(b.x0 - t, g - 0.02, b.z0 - t, b.x1 + t, g + 0.02, b.z1 + t));
    const gardenZ1 = b.z1 + GARDEN;
    for (let z = b.z1 + t + 0.5; z < gardenZ1 + 9; z += 1.15) {
      const wobble = Math.sin(z * 1.7) * 0.12;
      stone.push(box(door - PATH_W / 2 + wobble, g - 0.02, z, door + PATH_W / 2 + wobble, g + 0.03, z + 0.95));
    }
    this.addMerged(stone, this.mats.surface("stone-tile"));

    const hedges: THREE.BufferGeometry[] = [];
    const hx0 = b.x0 - GARDEN;
    const hx1 = b.x1 + GARDEN;
    const hz0 = b.z0 - GARDEN;
    const run = (x0: number, z0: number, x1: number, z1: number): void => {
      hedges.push(box(x0, g, z0, x1, g + HEDGE_H, z1));
    };
    run(hx0, hz0, hx1, hz0 + HEDGE_W);
    run(hx0, hz0, hx0 + HEDGE_W, gardenZ1);
    run(hx1 - HEDGE_W, hz0, hx1, gardenZ1);
    run(hx0, gardenZ1 - HEDGE_W, door - PATH_W, gardenZ1);
    run(door + PATH_W, gardenZ1 - HEDGE_W, hx1, gardenZ1);
    // Low parterre hedges either side of the path.
    run(door - PATH_W - 4.2, b.z1 + t + 1.4, door - PATH_W - 0.6, b.z1 + t + 2.0);
    run(door + PATH_W + 0.6, b.z1 + t + 1.4, door + PATH_W + 4.2, b.z1 + t + 2.0);
    this.addMerged(hedges, this.hedge);

    const bushes: THREE.BufferGeometry[] = [];
    const rand = seeded(7);
    const bush = (x: number, z: number, r: number): void => {
      const geo = new THREE.IcosahedronGeometry(r, 2);
      const p = geo.getAttribute("position");
      for (let i = 0; i < p.count; i++) {
        const k = 1 + (rand() - 0.5) * 0.25;
        p.setXYZ(i, p.getX(i) * k, p.getY(i) * k * 0.85, p.getZ(i) * k);
      }
      geo.computeVertexNormals();
      geo.translate(x, g + r * 0.6, z);
      bushes.push(geo);
    };
    for (const [x, z] of [
      [hx0 + 2.2, hz0 + 2.2],
      [hx1 - 2.2, hz0 + 2.2],
      [hx0 + 2.2, gardenZ1 - 2.4],
      [hx1 - 2.2, gardenZ1 - 2.4],
      [door - PATH_W - 1.2, gardenZ1 - 1.6],
      [door + PATH_W + 1.2, gardenZ1 - 1.6],
    ] as const)
      bush(x, z, 0.95 + rand() * 0.4);
    for (let i = 0; i < 14; i++) {
      const side = i % 2 === 0 ? hx0 + 1.6 : hx1 - 1.6;
      bush(side + (rand() - 0.5) * 0.8, hz0 + 4 + i * ((gardenZ1 - hz0 - 8) / 14), 0.55 + rand() * 0.35);
    }
    this.addMerged(bushes, this.hedge);

    const posts: THREE.BufferGeometry[] = [];
    const glows: THREE.BufferGeometry[] = [];
    const spills: THREE.BufferGeometry[] = [];
    for (const z of [b.z1 + t + 2.6, b.z1 + t + 6.2]) {
      for (const x of [door - PATH_W / 2 - 0.5, door + PATH_W / 2 + 0.5]) {
        posts.push(box(x - 0.06, g, z - 0.06, x + 0.06, g + 1.1, z + 0.06));
        glows.push(box(x - 0.12, g + 1.1, z - 0.12, x + 0.12, g + 1.36, z + 0.12));
        spills.push(flat(x, g + 0.035, z, 3.4, 3.4));
      }
    }
    this.addMerged(posts, this.mats.bronze);
    this.addMerged(glows, this.lanternGlow, false);
    const spill = mergeGeometries(spills);
    for (const g of spills) g.dispose();
    if (spill) this.root.add(new THREE.Mesh(spill, this.spill));
  }

  private addMerged(geometries: THREE.BufferGeometry[], material: THREE.Material, shadows = true): void {
    const merged = mergeGeometries(geometries);
    for (const g of geometries) g.dispose();
    if (!merged) return;
    applyWorldUVs(merged);
    const mesh = new THREE.Mesh(merged, material);
    mesh.castShadow = shadows;
    mesh.receiveShadow = shadows;
    this.root.add(mesh);
  }

  private clear(): void {
    for (const child of [...this.root.children]) {
      this.root.remove(child);
      if (child instanceof THREE.Mesh) child.geometry.dispose();
    }
  }
}

/** A small deterministic random source, so the garden looks the same every time. */
function seeded(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}
