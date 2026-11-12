// The host room's furniture and the seated figure. Models are normalised to
// real sizes; the figure plays a seated idle and cross-fades to answering
// while the assistant speaks.

import * as THREE from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { HOST_LAYOUT } from "./layout";
import { palette } from "./palette";

/** Real heights, in metres. */
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
/** Where the seated figure sits relative to the chair's origin (m). */
const SEAT = new THREE.Vector3(0, 0.02, 0.06);

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
    const pieces = (Object.keys(HEIGHT) as Piece[]).map((name) => this.piece(name));
    await Promise.all([...pieces, this.figure()]);
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
    const [from, to] = talking ? [this.idle, this.talk] : [this.talk, this.idle];
    to.reset().play();
    from.crossFadeTo(to, FADE_S, false);
  }

  update(dt: number): void {
    this.mixer?.update(dt);
  }

  private async piece(name: Piece): Promise<void> {
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
    this.root.add(object);
  }

  private async figure(): Promise<void> {
    let gltf: GLTF;
    try {
      gltf = await this.loader.loadAsync("assets/models/vision.glb");
    } catch {
      this.onMissing("figure model");
      return;
    }
    const figure = gltf.scene;
    figure.name = "figure";
    figure.position.set(HOST_LAYOUT.armchair.x + SEAT.x, SEAT.y, HOST_LAYOUT.armchair.z + SEAT.z);
    figure.rotation.y = HOST_LAYOUT.armchair.turn;
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
    this.root.add(figure);
    this.mixer = new THREE.AnimationMixer(figure);
    const clip = (name: string): THREE.AnimationClip | null => THREE.AnimationClip.findByName(gltf.animations, name);
    const idleClip = clip(CLIP_IDLE);
    const talkClip = clip(CLIP_TALK);
    if (!idleClip || !talkClip) {
      this.onMissing("figure animations");
      return;
    }
    this.idle = this.mixer.clipAction(idleClip).play();
    this.talk = this.mixer.clipAction(talkClip);
  }
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
  object.scale.setScalar(height / size.y);
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
