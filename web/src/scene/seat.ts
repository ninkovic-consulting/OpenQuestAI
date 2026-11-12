// Seats the figure in the armchair. The two models were made apart, so both are
// measured — the chair by casting rays into it, the seated pose by sampling the
// skinned mesh — and the chair is sized and the figure placed from those numbers.
// Both models face +z; the chair's origin is its footprint centre on the floor.

import * as THREE from "three";

/** A point on a surface seen from the front: its depth `z` at height `y`. */
export interface Sample {
  y: number;
  z: number;
}

/** The chair at unit height (1 = its full height), facing +z. */
export interface ChairShape {
  /** Height of the cushion under the hips. */
  seatTop: number;
  /** Middle of the seat across its width. */
  centerX: number;
  /** Front face of the backrest above the cushion. */
  back: Sample[];
  /** Front face of the seat base below the cushion. */
  front: Sample[];
}

/** The seated pose in the figure's own space, in metres, facing +z. */
export interface PoseShape {
  /** Lowest point of the feet. */
  footY: number;
  /** Lowest point under the hips and thighs, where they meet the seat. */
  seatY: number;
  hipX: number;
  /** The rearmost point of the body in each height band (back above the seat, calves below it). */
  body: Sample[];
}

export interface SeatFit {
  /** Chair height in metres; the chair's width scales with it. */
  height: number;
  /** Chair depth scale in metres per unit, at most `height`. */
  depth: number;
  /** The figure's position in the chair's frame, in metres. */
  offset: THREE.Vector3;
  /** Space left between the figure's back and the backrest, in metres. */
  backGap: number;
}

export const BAND = 0.05;

export const SEAT_LIMITS = {
  /** Believable wingback heights, in metres. */
  minHeight: 0.95,
  maxHeight: 1.25,
  /** The chair's depth may shrink to this share of what its height implies; less reads as a squashed chair. */
  minDepthRatio: 0.7,
  /** How far the hips press into the cushion. */
  sink: 0.02,
  /** Air kept between the body and the chair. */
  clearance: 0.015,
};

/**
 * Size the chair so its cushion is at the height the pose needs with the feet
 * on the floor, then slide the figure back until its back meets the backrest or
 * its calves meet the seat front, whichever comes first. A pose made for a
 * shallower seat than the chair's leaves a gap at the back; the chair is made
 * shallower, within `minDepthRatio`, to close it.
 */
export function fitSeat(chair: ChairShape, pose: PoseShape, limits = SEAT_LIMITS): SeatFit {
  const need = pose.seatY - pose.footY + limits.sink;
  const height = THREE.MathUtils.clamp(need / chair.seatTop, limits.minHeight, limits.maxHeight);
  const y = chair.seatTop * height - limits.sink - pose.seatY;

  // Below the seat only the lower legs face the seat front; the hips are above it.
  const legs = pose.seatY - 2 * BAND;
  const reach = (surface: Sample[], depth: number, below = Infinity): number => {
    let bound = -Infinity;
    for (const s of surface) {
      const at = s.y * height - y;
      const body = at < below ? rearmost(pose.body, at) : null;
      if (body !== null) bound = Math.max(bound, s.z * depth - body + limits.clearance);
    }
    return bound;
  };

  let depth = height;
  for (let ratio = 1; ratio >= limits.minDepthRatio - 1e-9; ratio -= 0.01) {
    depth = height * ratio;
    if (reach(chair.front, depth, legs) <= reach(chair.back, depth)) break;
  }
  const back = reach(chair.back, depth);
  const z = Math.max(back, reach(chair.front, depth, legs));
  return {
    height,
    depth,
    offset: new THREE.Vector3(chair.centerX * height - pose.hipX, y, z),
    backGap: Number.isFinite(back) ? z - back : 0,
  };
}

/** The rearmost body point in the bands around height `y`, or null if the body is not there. */
function rearmost(body: Sample[], y: number): number | null {
  let z: number | null = null;
  for (const s of body) {
    if (y >= s.y - BAND / 2 && y < s.y + BAND * 1.5) z = z === null ? s.z : Math.min(z, s.z);
  }
  return z;
}

/** Cast rays into a chair at unit height, standing on y = 0 and facing +z. */
export function measureChair(chair: THREE.Object3D): ChairShape {
  chair.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(chair);
  const ray = new THREE.Raycaster();
  const hit = (from: THREE.Vector3, dir: THREE.Vector3): THREE.Vector3 | null => {
    ray.set(from, dir);
    return ray.intersectObject(chair, true)[0]?.point ?? null;
  };
  const centerX = (box.min.x + box.max.x) / 2;
  const across = [-0.1, 0, 0.1].map((dx) => centerX + dx);
  const down = new THREE.Vector3(0, -1, 0);
  const back = new THREE.Vector3(0, 0, -1);

  // Walk the centre line from the front edge back until the surface rises into the backrest.
  const cushion: number[] = [];
  let last: number | null = null;
  for (let z = box.max.z; z > box.min.z; z -= 0.02) {
    const ys = across.map((x) => hit(new THREE.Vector3(x, box.max.y + 1, z), down)?.y).filter((v) => v !== undefined);
    if (ys.length === 0) continue;
    const y = ys.reduce((a, b) => a + b, 0) / ys.length;
    if (last !== null && y > last + 0.05) break;
    cushion.push(y);
    last = y;
  }
  // The hips rest on the rear half of the cushion.
  const rear = cushion.slice(Math.floor(cushion.length / 2));
  const seatTop = rear.reduce((a, b) => a + b, 0) / Math.max(1, rear.length);

  const face = (y: number): number | null => {
    const zs = across.map((x) => hit(new THREE.Vector3(x, y, box.max.z + 1), back)?.z).filter((v) => v !== undefined);
    return zs.length === 0 ? null : Math.max(...zs);
  };
  const surface = (from: number, to: number): Sample[] => {
    const out: Sample[] = [];
    for (let y = from; y < to; y += 0.02) {
      const z = face(y);
      if (z !== null) out.push({ y, z });
    }
    return out;
  };
  return { seatTop, centerX, back: surface(seatTop + 0.03, box.max.y), front: surface(0, seatTop - 0.01) };
}

/** Sample a seated clip on the figure and read where its body is. Leaves the figure at the clip's start. */
export function measurePose(figure: THREE.Object3D, clip: THREE.AnimationClip, frames = 12): PoseShape {
  const mixer = new THREE.AnimationMixer(figure);
  const action = mixer.clipAction(clip).play();
  const meshes: THREE.SkinnedMesh[] = [];
  figure.traverse((o) => {
    if (o instanceof THREE.SkinnedMesh) meshes.push(o);
  });
  const joint = (name: string): THREE.Vector3 => {
    const bone = figure.getObjectByName(name);
    if (!bone) throw new Error(`figure has no ${name} joint`);
    return bone.getWorldPosition(new THREE.Vector3());
  };

  const bands = new Map<number, number>();
  let footY = Infinity;
  let seatY = Infinity;
  let hipX = 0;
  const v = new THREE.Vector3();
  for (let f = 0; f < frames; f++) {
    mixer.setTime((clip.duration * f) / frames);
    figure.updateMatrixWorld(true);
    const hip = joint("Hips");
    const knee = Math.min(joint("LeftLeg").z, joint("RightLeg").z);
    hipX += hip.x / frames;
    for (const mesh of meshes) {
      const count = mesh.geometry.getAttribute("position").count;
      for (let i = 0; i < count; i++) {
        mesh.getVertexPosition(i, v).applyMatrix4(mesh.matrixWorld);
        footY = Math.min(footY, v.y);
        if (Math.abs(v.x - hip.x) > 0.2) continue;
        if (v.y < hip.y && v.z > hip.z - 0.3 && v.z < knee - 0.12) seatY = Math.min(seatY, v.y);
        const band = Math.floor(v.y / BAND);
        bands.set(band, Math.min(bands.get(band) ?? Infinity, v.z));
      }
    }
  }
  action.stop();
  mixer.uncacheRoot(figure);
  const body = [...bands].map(([band, z]) => ({ y: band * BAND, z })).sort((a, b) => a.y - b.y);
  return { footY, seatY, hipX, body };
}
