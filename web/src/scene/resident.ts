// One standing figure: its model scaled to its real height, an idle clip and
// a working clip that cross-fade, and a fade out and in when it changes rooms.

import * as THREE from "three";
import type { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { IDLE_CLIP, type Character, type WorkMotion } from "./cast";
import { leanAxes, leanClip, pinRoot, rootCentre, trimClip } from "./motion";
import { sanitizeModel } from "./sanitize";

/** Where a figure stands: a room, a spot on its floor, and the room's group, whose rise it follows. */
export interface Placement {
  room: string;
  x: number;
  z: number;
  facing: number;
  group: THREE.Object3D;
}

const CROSS_S = 0.8;
const FADE_S = 0.5;

export class Resident {
  readonly root = new THREE.Group();
  private readonly mixer: THREE.AnimationMixer;
  private readonly materials: THREE.Material[] = [];
  private placement: Placement | null = null;
  /** Where to go once faded out; null to stay hidden. */
  private next: { placement: Placement | null; working: boolean } | null = null;
  private working = false;
  private opacity = 0;

  private constructor(
    model: THREE.Object3D,
    private readonly idle: THREE.AnimationAction,
    private readonly work: THREE.AnimationAction,
    readonly height: number,
  ) {
    this.root.add(model);
    this.root.visible = false;
    this.mixer = idle.getMixer();
    model.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      o.castShadow = true;
      o.receiveShadow = true;
      // The clips bend and reach beyond the rest pose's bounds.
      o.frustumCulled = false;
      this.materials.push(...[o.material].flat());
    });
  }

  /** Load a character's model; null when the model or its clips are missing. `phase` (0 to 1) offsets the idle. */
  static async load(loader: GLTFLoader, character: Character, phase: number): Promise<Resident | null> {
    const gltf = await loader.loadAsync(`assets/models/agents/${character.model}.glb`).catch(() => null);
    if (!gltf) return null;
    const model = gltf.scene;
    sanitizeModel(model);
    standAt(model, character.height);
    const idleSource = THREE.AnimationClip.findByName(gltf.animations, IDLE_CLIP);
    const workSource = THREE.AnimationClip.findByName(gltf.animations, character.work.clip);
    const anchor = idleSource ? rootCentre(idleSource) : null;
    if (!idleSource || !workSource || !anchor) return null;
    const mixer = new THREE.AnimationMixer(model);
    const idle = mixer.clipAction(pinRoot(idleSource, anchor));
    idle.time = phase * idle.getClip().duration;
    idle.play();
    const work = mixer.clipAction(pinRoot(workClip(workSource, character.work, model), anchor));
    work.timeScale = character.work.speed;
    if (character.work.pingPong) work.setLoop(THREE.LoopPingPong, Infinity);
    return new Resident(model, idle, work, character.height);
  }

  get room(): string | null {
    return (this.next ? this.next.placement : this.placement)?.room ?? null;
  }

  /**
   * Stand at `placement` (null hides the figure), working or not. A new spot
   * fades out and in; the same spot only cross-fades the clips.
   */
  set(placement: Placement | null, working: boolean): void {
    if (this.next || !samePlace(this.placement, placement)) {
      this.next = { placement, working };
      return;
    }
    // Same spot; the room's group may be a new one after a rebuild.
    this.placement = placement;
    this.setWorking(working, false);
  }

  /** The figure's middle and reach, for culling; null when hidden. */
  bounds(sphere: THREE.Sphere): THREE.Sphere | null {
    if (!this.root.visible) return null;
    sphere.center.copy(this.root.position).setY(this.root.position.y + this.height / 2);
    sphere.radius = this.height * 0.75;
    return sphere;
  }

  /** Advance the fades; `animate` false skips the skeleton, for a figure no one can see. */
  update(dt: number, animate: boolean): void {
    if (this.next) {
      this.fade(-dt / FADE_S);
      if (this.opacity === 0) {
        const { placement, working } = this.next;
        this.next = null;
        this.placement = placement;
        this.setWorking(working, true);
        if (placement) {
          this.root.position.set(placement.x, 0, placement.z);
          this.root.rotation.y = placement.facing;
        }
      }
    } else if (this.placement) this.fade(dt / FADE_S);
    if (this.placement) this.root.position.y = this.placement.group.position.y;
    if (animate && this.root.visible) this.mixer.update(dt);
  }

  private setWorking(working: boolean, now: boolean): void {
    if (working === this.working) return;
    this.working = working;
    const [from, to] = working ? [this.idle, this.work] : [this.work, this.idle];
    to.reset().play();
    if (now) from.stop();
    else from.crossFadeTo(to, CROSS_S, false);
  }

  private fade(step: number): void {
    const opacity = THREE.MathUtils.clamp(this.opacity + step, 0, 1);
    if (opacity === this.opacity) return;
    const solid = opacity === 1;
    for (const m of this.materials) {
      if (m.transparent === solid) {
        m.transparent = !solid;
        m.needsUpdate = true;
      }
      m.opacity = opacity;
    }
    this.opacity = opacity;
    this.root.visible = opacity > 0;
  }
}

/** The working clip as the character's table describes it. */
function workClip(source: THREE.AnimationClip, motion: WorkMotion, model: THREE.Object3D): THREE.AnimationClip {
  const part = motion.span ? trimClip(source, motion.span[0], motion.span[1]) : source;
  return motion.lean === 0 ? part : leanClip(part, leanAxes(model), motion.lean);
}

/** Scale the model to `height` in its rest pose and stand its feet on y = 0. */
function standAt(model: THREE.Object3D, height: number): void {
  model.updateMatrixWorld(true);
  const size = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
  model.scale.multiplyScalar(height / size.y);
  model.updateMatrixWorld(true);
  model.position.y -= new THREE.Box3().setFromObject(model).min.y;
}

function samePlace(a: Placement | null, b: Placement | null): boolean {
  if (!a || !b) return a === b;
  return a.room === b.room && Math.hypot(a.x - b.x, a.z - b.z) < 0.01 && Math.abs(a.facing - b.facing) < 0.01;
}
