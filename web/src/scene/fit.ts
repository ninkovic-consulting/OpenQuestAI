// Framing the house: where the camera looks and how far back it stands so a
// box lands inside a window of the screen at any size and aspect, and where
// that box sits on screen, for the miniature blur.

import * as THREE from "three";

/** A window of the screen in normalised device coordinates: -1 is the left or bottom edge, 1 the right or top. */
export interface NdcWindow {
  left: number;
  right: number;
  bottom: number;
  top: number;
}

export interface Fit {
  target: THREE.Vector3;
  distance: number;
}

/** A vertical span of the screen in normalised device coordinates. */
export interface ScreenBand {
  center: number;
  half: number;
}

const CENTRING_STEPS = 8;

export function boxCorners(box: THREE.Box3): THREE.Vector3[] {
  const out: THREE.Vector3[] = [];
  for (const x of [box.min.x, box.max.x])
    for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) out.push(new THREE.Vector3(x, y, z));
  return out;
}

/**
 * Look along `-dir` (a unit vector from the target to the camera) and stand
 * back just far enough that every point projects inside `window`, for both
 * the vertical field of view `fovY` (radians) and the horizontal one. The
 * target slides across the view so the points sit centred in the window.
 */
export function fitView(points: THREE.Vector3[], dir: THREE.Vector3, fovY: number, aspect: number, window: NdcWindow): Fit {
  const right = new THREE.Vector3().crossVectors(THREE.Object3D.DEFAULT_UP, dir).normalize();
  const up = new THREE.Vector3().crossVectors(dir, right);
  const tanV = Math.tan(fovY / 2);
  const tanH = tanV * aspect;
  const target = points.reduce((sum, p) => sum.add(p), new THREE.Vector3()).divideScalar(Math.max(1, points.length));
  const r = new THREE.Vector3();

  const distanceFor = (t: THREE.Vector3): number => {
    let d = 0;
    for (const p of points) {
      r.subVectors(p, t);
      const depth = r.dot(dir);
      const x = r.dot(right) / tanH;
      const y = r.dot(up) / tanV;
      d = Math.max(d, depth + x / window.right, depth + x / window.left, depth + y / window.top, depth + y / window.bottom);
    }
    return d;
  };

  let distance = distanceFor(target);
  for (let step = 0; step < CENTRING_STEPS; step++) {
    const ndc = project(points, target, distance, dir, right, up, tanH, tanV);
    const dx = (ndc.x0 + ndc.x1) / 2 - (window.left + window.right) / 2;
    const dy = (ndc.y0 + ndc.y1) / 2 - (window.bottom + window.top) / 2;
    target.addScaledVector(right, dx * tanH * distance).addScaledVector(up, dy * tanV * distance);
    distance = distanceFor(target);
  }
  return { target, distance };
}

/** Scratch for `screenBand`, which runs every frame. */
const bandPoint = new THREE.Vector3();

/** Where the points sit vertically on screen; null when one is behind the camera, so the span is unknown. */
export function screenBand(points: THREE.Vector3[], camera: THREE.Camera): ScreenBand | null {
  let lo = Infinity;
  let hi = -Infinity;
  const v = bandPoint;
  for (const p of points) {
    v.copy(p).applyMatrix4(camera.matrixWorldInverse);
    if (v.z >= 0) return null;
    v.applyMatrix4(camera.projectionMatrix);
    lo = Math.min(lo, v.y);
    hi = Math.max(hi, v.y);
  }
  return { center: (lo + hi) / 2, half: (hi - lo) / 2 };
}

function project(
  points: THREE.Vector3[],
  target: THREE.Vector3,
  distance: number,
  dir: THREE.Vector3,
  right: THREE.Vector3,
  up: THREE.Vector3,
  tanH: number,
  tanV: number,
): { x0: number; x1: number; y0: number; y1: number } {
  const out = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity };
  const r = new THREE.Vector3();
  for (const p of points) {
    r.subVectors(p, target);
    const depth = distance - r.dot(dir);
    const x = r.dot(right) / (depth * tanH);
    const y = r.dot(up) / (depth * tanV);
    out.x0 = Math.min(out.x0, x);
    out.x1 = Math.max(out.x1, x);
    out.y0 = Math.min(out.y0, y);
    out.y1 = Math.max(out.y1, y);
  }
  return out;
}
