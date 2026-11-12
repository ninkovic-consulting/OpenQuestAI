// Clip surgery for the standing figures: keep every clip on the spot, cut out
// the usable part of a clip, and bend the upper body forward.

import * as THREE from "three";

/** The root bone; its position track carries the walk across the floor. */
export const ROOT_BONE = "Hips";
/** The bones a forward lean is spread over, lowest first. */
export const SPINE_BONES = ["Spine02", "Spine01", "Spine"] as const;

const rootTrack = (clip: THREE.AnimationClip): THREE.KeyframeTrack | undefined =>
  clip.tracks.find((t) => t.name === `${ROOT_BONE}.position`);

/** The root's average spot on the floor (x, z) over a clip, after any drift is taken out; null without a root track. */
export function rootCentre(clip: THREE.AnimationClip): THREE.Vector2 | null {
  const track = rootTrack(clip);
  if (!track) return null;
  const values = track.values;
  const n = track.times.length;
  let x = 0;
  let z = 0;
  for (let i = 0; i < n; i++) {
    x += values[i * 3] ?? 0;
    z += values[i * 3 + 2] ?? 0;
  }
  return new THREE.Vector2(x / n, z / n);
}

/**
 * Keep a clip on the spot: take out the root's drift from first key to last,
 * so it ends where it starts, and move its average spot to `anchor`. The sway
 * within the clip stays, so planted feet stay planted.
 */
export function pinRoot(clip: THREE.AnimationClip, anchor: THREE.Vector2): THREE.AnimationClip {
  const out = clip.clone();
  const track = rootTrack(out);
  if (!track) return out;
  const values = own(track);
  const { times } = track;
  const n = times.length;
  const t0 = times[0] ?? 0;
  const span = (times[n - 1] ?? 0) - t0;
  const drift = [(values[(n - 1) * 3] ?? 0) - (values[0] ?? 0), (values[(n - 1) * 3 + 2] ?? 0) - (values[2] ?? 0)] as const;
  for (let i = 0; i < n; i++) {
    const k = span > 0 ? ((times[i] ?? 0) - t0) / span : 0;
    values[i * 3] = (values[i * 3] ?? 0) - drift[0] * k;
    values[i * 3 + 2] = (values[i * 3 + 2] ?? 0) - drift[1] * k;
  }
  const centre = rootCentre(out) ?? anchor;
  for (let i = 0; i < n; i++) {
    values[i * 3] = (values[i * 3] ?? 0) + anchor.x - centre.x;
    values[i * 3 + 2] = (values[i * 3 + 2] ?? 0) + anchor.y - centre.y;
  }
  return out;
}

/** The part of a clip between `from` and `to` seconds, starting at zero. */
export function trimClip(clip: THREE.AnimationClip, from: number, to: number): THREE.AnimationClip {
  const tracks = clip.tracks.map((t) => {
    const cut = t.clone();
    // Sample the edges first, so the cut starts and ends exactly there.
    const edges = [from, to].map((time) => sample(t, time));
    cut.trim(from, to);
    return withEdges(cut, from, to, edges).shift(-from);
  });
  return new THREE.AnimationClip(clip.name, to - from, tracks);
}

/**
 * Bend the upper body forward by `angle` radians, spread over the spine
 * bones. `axes` maps each bone to the figure's left-to-right axis expressed
 * in that bone's parent space (see `leanAxes`).
 */
export function leanClip(clip: THREE.AnimationClip, axes: ReadonlyMap<string, THREE.Vector3>, angle: number): THREE.AnimationClip {
  const out = clip.clone();
  if (angle === 0 || axes.size === 0) return out;
  const q = new THREE.Quaternion();
  const turn = new THREE.Quaternion();
  for (const track of out.tracks) {
    const [bone, property] = track.name.split(".");
    const axis = bone ? axes.get(bone) : undefined;
    if (!axis || property !== "quaternion") continue;
    turn.setFromAxisAngle(axis, angle / axes.size);
    const values = own(track);
    for (let i = 0; i < track.times.length; i++) {
      q.fromArray(values, i * 4).premultiply(turn);
      q.toArray(values, i * 4);
    }
  }
  return out;
}

/**
 * The figure's left-to-right axis (+x of `root`) in the parent space of each
 * spine bone, taken from the rest pose: turning a bone about it pitches the
 * body forward for a positive angle, as the figures face +z.
 */
export function leanAxes(root: THREE.Object3D): Map<string, THREE.Vector3> {
  root.updateMatrixWorld(true);
  const rootTurn = root.getWorldQuaternion(new THREE.Quaternion());
  const axes = new Map<string, THREE.Vector3>();
  for (const name of SPINE_BONES) {
    const parent = root.getObjectByName(name)?.parent;
    if (!parent) continue;
    const parentTurn = parent.getWorldQuaternion(new THREE.Quaternion());
    const inModel = new THREE.Vector3(1, 0, 0).applyQuaternion(rootTurn);
    axes.set(name, inModel.applyQuaternion(parentTurn.invert()).normalize());
  }
  return axes;
}

/** A copy of a track's values that the track then owns: a cloned track shares its source's buffer. */
function own(track: THREE.KeyframeTrack): Float32Array {
  const values = Float32Array.from(track.values);
  track.values = values;
  return values;
}

function sample(track: THREE.KeyframeTrack, time: number): number[] {
  const interpolant = track.InterpolantFactoryMethodLinear(new Float32Array(track.getValueSize()));
  return Array.from(interpolant.evaluate(time) as ArrayLike<number>);
}

/** Add keys at `from` and `to` holding `edges`, unless the track already has keys there. */
function withEdges(track: THREE.KeyframeTrack, from: number, to: number, edges: number[][]): THREE.KeyframeTrack {
  const times: number[] = Array.from(track.times);
  const values: number[] = Array.from(track.values);
  const near = (a: number | undefined, b: number): boolean => a !== undefined && Math.abs(a - b) < 1e-4;
  if (!near(times[0], from)) {
    times.unshift(from);
    values.unshift(...(edges[0] ?? []));
  }
  if (!near(times[times.length - 1], to)) {
    times.push(to);
    values.push(...(edges[1] ?? []));
  }
  track.times = Float32Array.from(times);
  track.values = Float32Array.from(values);
  return track;
}
