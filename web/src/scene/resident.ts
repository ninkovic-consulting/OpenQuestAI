// One standing figure: its model scaled to its real height, an idle clip, a
// working clip and (once loaded) a walk, which cross-fade; a fade out and in
// when it changes rooms. At work on a job it paces between two spots in the
// room (pace.ts) with a thin mustard ring at its feet; waiting for the
// owner's yes it stands still and the ring turns alert red.

import * as THREE from "three";
import type { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import type { AgentWork } from "../net/job-types";
import { IDLE_CLIP, type Character, type WorkMotion } from "./cast";
import { leanAxes, leanClip, pinRoot, rootCentre, trimClip } from "./motion";
import { paceAt, TURN_S } from "./pace";
import { palette } from "./palette";
import { sanitizeModel } from "./sanitize";
import type { Spot } from "./spot";

/** Where a figure stands: a room, a spot on its floor, and the room's group, whose rise it follows. */
export interface Placement {
  room: string;
  x: number;
  z: number;
  facing: number;
  group: THREE.Object3D;
  /** The other end of its pacing at work; null when the room has no room for it. */
  pace: Spot | null;
}

const CROSS_S = 0.8;
/** Between walking and standing the clips change faster, so the feet do not slide. */
const STEP_CROSS_S = 0.3;
const FADE_S = 0.5;
/** The walk clip's pace for a figure 1.78 m tall, in metres a second, at WALK_RATE. */
const WALK_SPEED = 0.95;
/** The walk clip plays a little slower than recorded: an unhurried pace round a room. */
const WALK_RATE = 0.8;
const REF_HEIGHT = 1.78;
const RING = { inner: 0.34, outer: 0.37, lift: 0.015, opacity: 0.85 } as const;

export class Resident {
  readonly root = new THREE.Group();
  private readonly mixer: THREE.AnimationMixer;
  private readonly materials: THREE.Material[] = [];
  private readonly ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>;
  private walk: THREE.AnimationAction | null = null;
  private current: THREE.AnimationAction;
  private placement: Placement | null = null;
  /** Where to go once faded out; null to stay hidden. */
  private next: { placement: Placement | null; work: AgentWork } | null = null;
  private work: AgentWork = "idle";
  /** Seconds into pacing on this job (it starts facing its work); it stops while the figure waits. */
  private paced = TURN_S;
  private opacity = 0;

  private constructor(
    model: THREE.Object3D,
    private readonly idle: THREE.AnimationAction,
    private readonly working: THREE.AnimationAction,
    private readonly anchor: THREE.Vector2,
    readonly height: number,
  ) {
    this.root.add(model);
    this.root.visible = false;
    this.mixer = idle.getMixer();
    this.current = idle;
    model.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      o.castShadow = true;
      o.receiveShadow = true;
      // The clips bend and reach beyond the rest pose's bounds.
      o.frustumCulled = false;
      this.materials.push(...[o.material].flat());
    });
    const ringMaterial = new THREE.MeshBasicMaterial({ color: palette.mustard, transparent: true, opacity: 0, depthWrite: false, toneMapped: false });
    this.ring = new THREE.Mesh(new THREE.RingGeometry(RING.inner, RING.outer, 64), ringMaterial);
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.position.y = RING.lift;
    this.ring.visible = false;
    this.root.add(this.ring);
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
    return new Resident(model, idle, work, anchor, character.height);
  }

  /** The character's walk, kept on the spot: the figure itself moves across the floor at the clip's pace. */
  addWalk(clip: THREE.AnimationClip): void {
    if (this.walk) return;
    this.walk = this.mixer.clipAction(pinRoot(clip, this.anchor));
    this.walk.timeScale = WALK_RATE;
  }

  get hasWalk(): boolean {
    return this.walk !== null;
  }

  get room(): string | null {
    return (this.next ? this.next.placement : this.placement)?.room ?? null;
  }

  /**
   * Stand at `placement` (null hides the figure), doing `work`. A new spot,
   * or the end of a job away from the spot, fades out and in; otherwise the
   * clips cross-fade where it stands.
   */
  set(placement: Placement | null, work: AgentWork): void {
    const away = work === "idle" && this.placement !== null && Math.hypot(this.root.position.x - this.placement.x, this.root.position.z - this.placement.z) > 0.05;
    if (this.next || away || !samePlace(this.placement, placement)) {
      this.next = { placement, work };
      return;
    }
    // Same spot; the room's group may be a new one after a rebuild.
    this.placement = placement;
    if (work === "idle") this.paced = TURN_S;
    this.work = work;
    this.showRing();
  }

  /** The figure's middle and reach, for culling; null when hidden. */
  bounds(sphere: THREE.Sphere): THREE.Sphere | null {
    if (!this.root.visible) return null;
    sphere.center.copy(this.root.position).setY(this.root.position.y + this.height / 2);
    sphere.radius = this.height * 0.75;
    return sphere;
  }

  /** Advance the fades and the pacing; `animate` false skips the skeleton, for a figure no one can see. */
  update(dt: number, animate: boolean): void {
    if (this.next) {
      this.fade(-dt / FADE_S);
      if (this.opacity === 0) {
        const { placement, work } = this.next;
        this.next = null;
        this.placement = placement;
        this.work = work;
        this.paced = TURN_S;
        this.showRing();
        this.play(this.target(), true);
        if (placement) {
          this.root.position.set(placement.x, 0, placement.z);
          this.root.rotation.y = placement.facing;
        }
      }
    } else if (this.placement) {
      this.fade(dt / FADE_S);
      this.move(dt);
    }
    if (this.placement) this.root.position.y = this.placement.group.position.y;
    if (animate && this.root.visible) this.mixer.update(dt);
  }

  /** Pace while working; stand where it is while waiting; at its spot otherwise. */
  private move(dt: number): void {
    const p = this.placement;
    if (!p) return;
    const pacing = this.work !== "idle" && p.pace !== null && this.walk !== null;
    if (pacing && p.pace) {
      if (this.work === "working") this.paced += dt;
      const speed = (WALK_SPEED * WALK_RATE * this.height) / REF_HEIGHT;
      const pose = paceAt(p, p.pace, this.paced, speed);
      this.root.position.x = pose.x;
      this.root.position.z = pose.z;
      this.root.rotation.y = pose.facing;
      this.play(this.work === "working" && pose.walking ? (this.walk ?? this.working) : this.work === "working" ? this.working : this.idle, false);
      return;
    }
    this.play(this.target(), false);
  }

  /** The clip for standing still in the current work. */
  private target(): THREE.AnimationAction {
    return this.work === "working" ? this.working : this.idle;
  }

  private play(to: THREE.AnimationAction, now: boolean): void {
    const from = this.current;
    if (to === from) return;
    this.current = to;
    to.reset().play();
    if (now) from.stop();
    else from.crossFadeTo(to, to === this.walk || from === this.walk ? STEP_CROSS_S : CROSS_S, false);
  }

  private showRing(): void {
    this.ring.visible = this.work !== "idle";
    this.ring.material.color.setHex(this.work === "waiting" ? palette.alert : palette.mustard);
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
    this.ring.material.opacity = RING.opacity * opacity;
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
