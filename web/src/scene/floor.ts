// A room's floor as a grid of small cells, each either clear or blocked by a
// wall, a piece of furniture, a lamp or a figure. Rooms are rectangles or
// round towers; anything outside the shape is blocked.

import * as THREE from "three";

export type FloorShape =
  | { kind: "rect"; x0: number; z0: number; x1: number; z1: number }
  | { kind: "round"; cx: number; cz: number; r: number };

/** Cell size, in metres. */
export const CELL = 0.1;
/** Heights a standing figure fills; a rug or a threshold below it does not block. */
const BODY_Y: readonly [number, number] = [0.05, 2.0];
/** Clearance is measured out to this distance, in metres, and capped there. */
export const MAX_CLEAR = 1.6;

export class FloorGrid {
  readonly x0: number;
  readonly z0: number;
  readonly cols: number;
  readonly rows: number;
  readonly blocked: Uint8Array;

  constructor(shape: FloorShape) {
    const [x0, z0, x1, z1] =
      shape.kind === "rect" ? [shape.x0, shape.z0, shape.x1, shape.z1] : [shape.cx - shape.r, shape.cz - shape.r, shape.cx + shape.r, shape.cz + shape.r];
    this.x0 = x0;
    this.z0 = z0;
    this.cols = Math.max(1, Math.ceil((x1 - x0) / CELL - 1e-9));
    this.rows = Math.max(1, Math.ceil((z1 - z0) / CELL - 1e-9));
    this.blocked = new Uint8Array(this.cols * this.rows);
    for (let row = 0; row < this.rows; row++)
      for (let col = 0; col < this.cols; col++) {
        const [x, z] = this.centre(col, row);
        const inside = shape.kind === "rect" ? x < x1 && z < z1 : Math.hypot(x - shape.cx, z - shape.cz) <= shape.r - CELL / 2;
        if (!inside) this.blocked[row * this.cols + col] = 1;
      }
  }

  centre(col: number, row: number): [number, number] {
    return [this.x0 + (col + 0.5) * CELL, this.z0 + (row + 0.5) * CELL];
  }

  /** Block every cell whose square overlaps the box [x0, x1] by [z0, z1]. */
  blockBox(x0: number, z0: number, x1: number, z1: number): void {
    const c0 = Math.max(0, Math.floor((x0 - this.x0) / CELL));
    const c1 = Math.min(this.cols - 1, Math.floor((x1 - this.x0) / CELL));
    const r0 = Math.max(0, Math.floor((z0 - this.z0) / CELL));
    const r1 = Math.min(this.rows - 1, Math.floor((z1 - this.z0) / CELL));
    for (let row = r0; row <= r1; row++) for (let col = c0; col <= c1; col++) this.blocked[row * this.cols + col] = 1;
  }

  /** Block the cells whose centres lie within `r` of (x, z). */
  blockDisc(x: number, z: number, r: number): void {
    for (let row = 0; row < this.rows; row++)
      for (let col = 0; col < this.cols; col++) {
        const [cx, cz] = this.centre(col, row);
        if (Math.hypot(cx - x, cz - z) <= r) this.blocked[row * this.cols + col] = 1;
      }
  }

  /**
   * Block under each triangle that reaches into the body's height. Positions
   * are x, y, z triples; `index` lists corners three at a time, or the
   * positions are read in order when it is null. The triangle's bounding box
   * is blocked, which is exact for the boxes and walls the house is made of.
   */
  blockTriangles(position: ArrayLike<number>, index: ArrayLike<number> | null): void {
    const count = index ? index.length : position.length / 3;
    for (let k = 0; k + 2 < count; k += 3) {
      let minX = Infinity;
      let minY = Infinity;
      let minZ = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      let maxZ = -Infinity;
      for (let j = 0; j < 3; j++) {
        const v = (index ? (index[k + j] ?? 0) : k + j) * 3;
        const x = position[v] ?? 0;
        const y = position[v + 1] ?? 0;
        const z = position[v + 2] ?? 0;
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
        minZ = Math.min(minZ, z);
        maxZ = Math.max(maxZ, z);
      }
      if (maxY < BODY_Y[0] || minY > BODY_Y[1]) continue;
      this.blockBox(minX, minZ, maxX, maxZ);
    }
  }

  /**
   * For every cell, the distance from its centre to the nearest blocked
   * cell's edge, capped at MAX_CLEAR; zero on blocked cells.
   */
  clearance(): Float32Array {
    const out = new Float32Array(this.blocked.length);
    const ring = offsets();
    for (let row = 0; row < this.rows; row++)
      for (let col = 0; col < this.cols; col++) {
        const i = row * this.cols + col;
        if (this.blocked[i]) continue;
        let d = MAX_CLEAR;
        for (const o of ring) {
          const c = col + o.dc;
          const r = row + o.dr;
          // Beyond the grid counts as blocked: rooms are walled.
          if (c < 0 || r < 0 || c >= this.cols || r >= this.rows || this.blocked[r * this.cols + c]) {
            d = Math.min(MAX_CLEAR, o.d);
            break;
          }
        }
        out[i] = d;
      }
    return out;
  }
}

/** Block under every mesh of `object` that a figure could walk into, in the object's own space. */
export function blockObject(grid: FloorGrid, object: THREE.Object3D, skip: (mesh: THREE.Mesh) => boolean): void {
  object.updateMatrixWorld(true);
  const toObject = object.matrixWorld.clone().invert();
  const v = new THREE.Vector3();
  object.traverse((o) => {
    if (!(o instanceof THREE.Mesh) || skip(o)) return;
    const geometry = o.geometry as THREE.BufferGeometry;
    const source = geometry.getAttribute("position");
    const matrix = toObject.clone().multiply(o.matrixWorld);
    const placed = new Float32Array(source.count * 3);
    for (let i = 0; i < source.count; i++) {
      v.fromBufferAttribute(source, i).applyMatrix4(matrix);
      placed[i * 3] = v.x;
      placed[i * 3 + 1] = v.y;
      placed[i * 3 + 2] = v.z;
    }
    const index = geometry.getIndex();
    grid.blockTriangles(placed, index ? index.array : null);
  });
}

interface Offset {
  dc: number;
  dr: number;
  /** Distance from a cell's centre to the near edge of the cell at this offset. */
  d: number;
}

let OFFSETS: Offset[] | null = null;

/** Cell offsets within MAX_CLEAR, nearest first. */
function offsets(): Offset[] {
  if (OFFSETS) return OFFSETS;
  const reach = Math.ceil(MAX_CLEAR / CELL) + 1;
  const list: Offset[] = [];
  for (let dr = -reach; dr <= reach; dr++)
    for (let dc = -reach; dc <= reach; dc++) {
      if (dc === 0 && dr === 0) continue;
      const d = Math.hypot(Math.max(0, Math.abs(dc) - 0.5), Math.max(0, Math.abs(dr) - 0.5)) * CELL;
      if (d <= MAX_CLEAR) list.push({ dc, dr, d });
    }
  list.sort((p, q) => p.d - q.d);
  OFFSETS = list;
  return list;
}
