// Geometry helpers in metres. Every helper returns geometry already placed in
// world space, ready to merge.

import * as THREE from "three";
import type { Axis } from "./grid";

/** An axis-aligned box from min and max corners. */
export function box(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number): THREE.BufferGeometry {
  const g = new THREE.BoxGeometry(Math.abs(x1 - x0), Math.abs(y1 - y0), Math.abs(z1 - z0));
  g.translate((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
  return g;
}

/**
 * A box against a wall line. `along` is the span along the wall, `across` the
 * signed offsets from the line (negative is north or west), `y` the heights.
 */
export function slab(
  axis: Axis,
  line: number,
  along: readonly [number, number],
  across: readonly [number, number],
  y: readonly [number, number],
): THREE.BufferGeometry {
  return axis === "h"
    ? box(along[0], y[0], line + across[0], along[1], y[1], line + across[1])
    : box(line + across[0], y[0], along[0], line + across[1], y[1], along[1]);
}

/** A flat rectangle lying on the ground, facing up. */
export function flat(cx: number, y: number, cz: number, w: number, d: number): THREE.BufferGeometry {
  const g = new THREE.PlaneGeometry(w, d);
  g.rotateX(-Math.PI / 2);
  g.translate(cx, y, cz);
  return g;
}
