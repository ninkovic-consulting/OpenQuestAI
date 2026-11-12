import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { leanAxes, leanClip, pinRoot, rootCentre, trimClip } from "./motion";

/** A clip whose root walks 30 cm east and 10 cm north over 2 s while swaying 2 cm, bobbing in height. */
function walking(): THREE.AnimationClip {
  const times: number[] = [];
  const values: number[] = [];
  for (let i = 0; i <= 20; i++) {
    const t = i / 10;
    times.push(t);
    values.push(10 + 15 * t + 2 * Math.sin(t * Math.PI), 95 + Math.sin(t * 3), -5 * t);
  }
  const spin = new THREE.QuaternionKeyframeTrack("Spine01.quaternion", [0, 2], [0, 0, 0, 1, 0, 0, 0, 1]);
  return new THREE.AnimationClip("Walk", 2, [new THREE.VectorKeyframeTrack("Hips.position", times, values), spin]);
}

const root = (clip: THREE.AnimationClip): THREE.KeyframeTrack => clip.tracks.find((t) => t.name === "Hips.position") as THREE.KeyframeTrack;

describe("pinRoot", () => {
  it("ends where it starts, centred on the anchor, keeping the sway and the height", () => {
    const source = walking();
    const pinned = pinRoot(source, new THREE.Vector2(1, 2));
    const v = root(pinned).values;
    const last = v.length - 3;
    expect(v[last]).toBeCloseTo(v[0] ?? NaN, 5);
    expect(v[last + 2]).toBeCloseTo(v[2] ?? NaN, 5);
    const centre = rootCentre(pinned);
    expect(centre?.x).toBeCloseTo(1, 5);
    expect(centre?.y).toBeCloseTo(2, 5);
    // The sway is still there, and heights are untouched.
    expect((v[15] ?? 0) - (v[0] ?? 0)).toBeCloseTo(2, 4);
    expect(v[1]).toBeCloseTo(root(source).values[1] ?? NaN, 5);
  });

  it("leaves the source clip as it was", () => {
    const source = walking();
    const before = Array.from(root(source).values);
    pinRoot(source, new THREE.Vector2(0, 0));
    expect(Array.from(root(source).values)).toEqual(before);
  });
});

describe("trimClip", () => {
  it("keeps the part asked for, from zero, with keys exactly at both ends", () => {
    const source = walking();
    const part = trimClip(source, 0.55, 1.25);
    expect(part.duration).toBeCloseTo(0.7, 5);
    const track = root(part);
    expect(track.times[0]).toBeCloseTo(0, 5);
    expect(track.times[track.times.length - 1]).toBeCloseTo(0.7, 5);
    const at = (clip: THREE.AnimationClip, t: number): number =>
      (root(clip).InterpolantFactoryMethodLinear(new Float32Array(3)).evaluate(t) as Float32Array)[1] ?? NaN;
    expect(at(part, 0)).toBeCloseTo(at(source, 0.55), 4);
    expect(at(part, 0.7)).toBeCloseTo(at(source, 1.25), 4);
  });
});

describe("leanClip", () => {
  it("pitches the spine forward, toward +z, by the angle over all its bones", () => {
    const body = new THREE.Bone();
    body.name = "Hips";
    const spine = new THREE.Bone();
    spine.name = "Spine01";
    // A parent turned a quarter about y: the lean axis must be found in its space.
    body.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2);
    body.add(spine);
    const scene = new THREE.Group();
    scene.add(body);
    const leaned = leanClip(walking(), leanAxes(scene), 0.3);
    const q = new THREE.Quaternion().fromArray(leaned.tracks[1]?.values ?? [], 0);
    spine.quaternion.copy(q);
    scene.updateMatrixWorld(true);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(spine.getWorldQuaternion(new THREE.Quaternion()));
    expect(up.z).toBeCloseTo(Math.sin(0.3), 5);
    expect(up.x).toBeCloseTo(0, 5);
  });
});
