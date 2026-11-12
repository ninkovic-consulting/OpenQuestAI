// The host room's furniture and the seated figure. Models are normalised to
// real sizes and the armchair is fitted to the figure's seated pose (seat.ts).
// The figure plays the upright start of the seated idle; while the assistant
// speaks, the answering clip's upper body is blended in, so the hips and legs
// stay in the seat.

import * as THREE from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { HOST_LAYOUT } from "./layout";
import { palette } from "./palette";
import { fitSeat, measureChair, measurePose } from "./seat";

/** Real heights, in metres; the armchair's is refitted to the figure once both load. */
const HEIGHT = {
  armchair: 1.12,
  "floor-lamp": 1.72,
  "side-table": 0.62,
  cabinet: 1.95,
  staircase: 2.3,
} as const;

type Piece = keyof typeof HEIGHT;

const CLIP_IDLE = "Chair_Sit_Idle_M";
const CLIP_TALK = "Sitting_Answering_Questions";
const FADE_S = 0.6;
/** The idle clip sits upright, hands on knees, until here; then it leans 50° forward, elbows on knees, until 8.5 s. */
const IDLE_UPRIGHT_S = 1.2;
const CLIP_FPS = 30;
/** How much the answering clip's upper body weighs against the idle's (1 would be half and half). */
const TALK_WEIGHT = 1.5;
/** Tracks the answering clip leaves to the idle: its hips sit higher and further aside. */
const SEATED_TRACK = /^(Hips|(Left|Right)(UpLeg|Leg|Foot|ToeBase))\./;

interface Figure {
  object: THREE.Object3D;
  idle: THREE.AnimationClip;
}

export class Props {
  readonly root = new THREE.Group();
  private mixer: THREE.AnimationMixer | null = null;
  private idle: THREE.AnimationAction | null = null;
  private talk: THREE.AnimationAction | null = null;
  private talking = false;
  private readonly loader = new GLTFLoader();

  constructor(private readonly onMissing: (what: string) => void) {
    this.root.name = "props";
  }

  async load(): Promise<void> {
    const names = Object.keys(HEIGHT) as Piece[];
    const [pieces, figure] = await Promise.all([Promise.all(names.map((name) => this.piece(name))), this.figure()]);
    const chair = pieces[names.indexOf("armchair")];
    if (chair && figure) seat(chair, figure);
    this.root.add(...pieces);
    if (figure) this.root.add(figure.object);
  }

  /** Stand the furniture in the host room. `fits` is false when the room is too small for the big pieces. */
  place(center: THREE.Vector3, fits: boolean): void {
    this.root.position.copy(center);
    for (const name of ["staircase", "cabinet"] as const) {
      const o = this.root.getObjectByName(name);
      if (o) o.visible = fits;
    }
  }

  setTalking(talking: boolean): void {
    if (talking === this.talking || !this.idle || !this.talk) return;
    this.talking = talking;
    if (talking) this.talk.reset().fadeIn(FADE_S).play();
    else this.talk.fadeOut(FADE_S);
  }

  update(dt: number): void {
    this.mixer?.update(dt);
  }

  private async piece(name: Piece): Promise<THREE.Object3D> {
    const layout = {
      armchair: HOST_LAYOUT.armchair,
      "floor-lamp": { ...HOST_LAYOUT.lamp, turn: 0 },
      "side-table": { ...HOST_LAYOUT.sideTable, turn: 0 },
      cabinet: HOST_LAYOUT.cabinet,
      staircase: HOST_LAYOUT.staircase,
    }[name];
    let object: THREE.Object3D;
    try {
      object = (await this.loader.loadAsync(`assets/models/${name}.glb`)).scene;
      normalise(object, HEIGHT[name]);
    } catch {
      this.onMissing(`${name} model`);
      object = standIn(HEIGHT[name]);
    }
    object.name = name === "floor-lamp" ? "lamp" : name;
    if (name === "floor-lamp") object.add(bulb(HEIGHT[name] / object.scale.y));
    object.position.set(layout.x, object.position.y, layout.z);
    object.rotation.y = layout.turn;
    shade(object);
    return object;
  }

  private async figure(): Promise<Figure | null> {
    let gltf: GLTF;
    try {
      gltf = await this.loader.loadAsync("assets/models/vision.glb");
    } catch {
      this.onMissing("figure model");
      return null;
    }
    const figure = gltf.scene;
    figure.name = "figure";
    shade(figure);
    figure.traverse((o) => {
      if (!(o instanceof THREE.SkinnedMesh)) return;
      o.frustumCulled = false;
      // Cloth, not satin: a matte suit keeps its pinstripes under the lamp.
      for (const m of [o.material].flat()) {
        if (m instanceof THREE.MeshStandardMaterial) {
          m.roughness = 0.82;
          m.envMapIntensity = 0.4;
          m.color.setScalar(0.82);
        }
      }
    });
    const clip = (name: string): THREE.AnimationClip | null => THREE.AnimationClip.findByName(gltf.animations, name);
    const idleClip = clip(CLIP_IDLE);
    const talkClip = clip(CLIP_TALK);
    if (!idleClip || !talkClip) {
      this.onMissing("figure animations");
      return null;
    }
    this.mixer = new THREE.AnimationMixer(figure);
    const upright = THREE.AnimationUtils.subclip(idleClip, CLIP_IDLE, 0, IDLE_UPRIGHT_S * CLIP_FPS, CLIP_FPS);
    this.idle = this.mixer.clipAction(upright).setLoop(THREE.LoopPingPong, Infinity).play();
    const upper = talkClip.tracks.filter((t) => !SEATED_TRACK.test(t.name));
    this.talk = this.mixer.clipAction(new THREE.AnimationClip(CLIP_TALK, talkClip.duration, upper));
    this.talk.weight = TALK_WEIGHT;
    return { object: figure, idle: upright };
  }
}

/** Size the armchair to the seated pose and sit the figure in it, both facing the chair's way. */
function seat(chair: THREE.Object3D, figure: Figure): void {
  const at = chair.position.clone();
  const turn = chair.rotation.y;
  chair.position.set(0, 0, 0);
  chair.rotation.y = 0;
  normalise(chair, 1);
  const fit = fitSeat(measureChair(chair), measurePose(figure.object, figure.idle));
  chair.scale.multiply(new THREE.Vector3(fit.height, fit.height, fit.depth));
  chair.position.set(at.x, chair.position.y * fit.height, at.z);
  chair.rotation.y = turn;
  figure.object.position.copy(fit.offset).applyAxisAngle(THREE.Object3D.DEFAULT_UP, turn).add(chair.position).setY(fit.offset.y);
  figure.object.rotation.y = turn;
}

/** A warm bulb inside the lamp's shade, so the lamp reads lit. `height` is in model units. */
function bulb(height: number): THREE.Mesh {
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(height * 0.035, 16, 12),
    new THREE.MeshStandardMaterial({ color: 0x000000, emissive: palette.lamp, emissiveIntensity: 6 }),
  );
  mesh.position.y = height * 0.38;
  return mesh;
}

/** Scale to a real height and stand the model on the floor. */
function normalise(object: THREE.Object3D, height: number): void {
  const size = new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3());
  object.scale.multiplyScalar(height / size.y);
  const box = new THREE.Box3().setFromObject(object);
  object.position.y = -box.min.y;
}

function shade(object: THREE.Object3D): void {
  object.traverse((o) => {
    if (o instanceof THREE.Mesh) {
      o.castShadow = true;
      o.receiveShadow = true;
    }
  });
}

/** A plain block in place of a model that failed to load. */
function standIn(height: number): THREE.Object3D {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(0.6, height, 0.6),
    new THREE.MeshStandardMaterial({ color: 0x5a4038, roughness: 0.8 }),
  );
  mesh.position.y = height / 2;
  const group = new THREE.Group();
  group.add(mesh);
  return group;
}
