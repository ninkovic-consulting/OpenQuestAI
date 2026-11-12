// The 3D stage: renderer, scene and the frame loop, wired to the store.

import * as THREE from "three";
import { hostRoom } from "../net/plan";
import type { Store, ViewState } from "../net/store";
import type { Cell, Plan } from "../net/types";
import { BuildMode } from "./build";
import { CameraRig } from "./camera";
import { boxCorners, screenBand, type NdcWindow } from "./fit";
import { planBounds, towers } from "./grid";
import { Grounds, type Bounds } from "./grounds";
import { HouseView } from "./house";
import { DIM } from "./layout";
import { Lighting } from "./lighting";
import { Materials } from "./materials";
import { palette } from "./palette";
import { Post, Streaks } from "./post";
import { Props, PROPS_TOP } from "./props";

/** Screen kept clear around the fitted house, in CSS pixels (the bottom at least a share of the height): the key hints above, the caption below. */
const CLEAR = { top: 56, side: 24, bottom: 112, bottomShare: 0.12 };

export interface RoomAnchor {
  id: string;
  x: number;
  y: number;
  visible: boolean;
}

export class Stage {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly rig: CameraRig;
  private readonly house: HouseView;
  private readonly props: Props;
  private readonly lighting: Lighting;
  private readonly grounds: Grounds;
  private readonly post: Post;
  private readonly streaks = new Streaks();
  private readonly build = new BuildMode();
  private readonly raycaster = new THREE.Raycaster();
  private readonly clock = new THREE.Timer();
  private plan: Plan | null = null;
  /** The house's bounding box, for framing and the miniature blur. */
  private houseBox = new THREE.Box3();
  private houseCorners: THREE.Vector3[] = [];
  private width = 1;
  private height = 1;
  private down = new THREE.Vector2();
  /** Called every frame with each room's label anchor on screen. */
  onFrame: (anchors: RoomAnchor[]) => void = () => {};
  /** Called when a glowing free slot is clicked in build mode. */
  onSlot: (cell: Cell) => void = () => {};
  /** Called with the room the camera flies into, and with null when it returns home. */
  onRoom: (roomId: string | null) => void = () => {};

  constructor(
    private readonly container: HTMLElement,
    private readonly store: Store,
    notify: (text: string) => void,
  ) {
    this.renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance", stencil: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.toneMapping = THREE.NoToneMapping;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.scene.background = new THREE.Color(palette.background);
    this.scene.fog = new THREE.FogExp2(palette.background, 0.0065);

    const missing = (what: string): void => notify(`Could not load ${what}; showing a stand-in.`);
    const mats = new Materials(this.renderer, (name) => missing(`the ${name} texture`));
    this.rig = new CameraRig(this.renderer.domElement);
    this.house = new HouseView(mats, (plan) => hostRoom(plan)?.id);
    this.props = new Props(missing);
    this.lighting = new Lighting(this.scene, this.renderer);
    this.grounds = new Grounds(mats);
    this.post = new Post(this.renderer, this.scene, this.rig.camera);
    this.scene.add(this.house.root, this.props.root, this.grounds.root, this.streaks.mesh, this.build.root);

    void this.props.load();
    this.listen();
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    store.subscribe((s, prev) => this.onState(s, prev));
    this.onState(store.get(), store.get());
  }

  start(): void {
    this.clock.connect(document);
    this.renderer.setAnimationLoop((t) => this.frame(t));
  }

  /** Back to the whole-house view. Returns false when already there. */
  home(): boolean {
    if (this.rig.room === null) return false;
    this.rig.home();
    this.post.setMiniature(true);
    this.onRoom(null);
    return true;
  }

  setBuildMode(on: boolean): void {
    this.build.setActive(on);
    if (on) this.home();
  }

  private onState(s: ViewState, prev: ViewState): void {
    if (s.plan && (s.plan !== this.plan || prev.plan === null)) this.rebuild(s.plan);
    this.props.setTalking(s.assistant === "speaking");
  }

  private rebuild(plan: Plan): void {
    const first = this.plan === null;
    this.plan = plan;
    this.house.build(plan);
    const { bounds, center, radius } = footprint(plan);
    this.lighting.sync(this.house, center, radius + 6);
    const host = hostRoom(plan);
    const hostView = host ? this.house.rooms.get(host.id) : undefined;
    this.grounds.build(bounds, hostView?.center.x ?? center.x);
    this.build.setPlan(plan);
    if (hostView) {
      this.props.place(hostView.center, hostView.extent.x >= 7 && hostView.extent.y >= 7);
      this.streaks.place(hostView.center, hostView.extent, hostView.wallTop);
    }
    this.houseBox = houseBox(plan, bounds);
    this.houseCorners = boxCorners(this.houseBox);
    this.rig.frame(this.houseBox, this.clearWindow(), first);
  }

  /** The part of the scene the house is fitted into, in normalised device coordinates. */
  private clearWindow(): NdcWindow {
    const x = Math.min(0.5, (2 * CLEAR.side) / this.width);
    return {
      left: -1 + x,
      right: 1 - x,
      top: 1 - Math.min(0.5, (2 * CLEAR.top) / this.height),
      bottom: -1 + Math.min(0.5, (2 * Math.max(CLEAR.bottom, CLEAR.bottomShare * this.height)) / this.height),
    };
  }

  private resize(): void {
    this.width = Math.max(1, this.container.clientWidth);
    this.height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(this.width, this.height, false);
    this.post.setSize(this.width, this.height);
    this.rig.setAspect(this.width / this.height);
    if (this.plan) this.rig.frame(this.houseBox, this.clearWindow(), this.rig.room === null);
  }

  private ndc(ev: MouseEvent): THREE.Vector2 {
    const rect = this.renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
  }

  private listen(): void {
    const dom = this.renderer.domElement;
    dom.addEventListener("dblclick", (ev) => {
      if (this.build.active) return;
      this.raycaster.setFromCamera(this.ndc(ev), this.rig.camera);
      const hit = this.raycaster.intersectObjects(this.house.floors(), false)[0];
      const id = hit?.object.userData["roomId"] as string | undefined;
      const view = id ? this.house.rooms.get(id) : undefined;
      if (view) {
        this.rig.flyTo(view.room.id, view.center, view.extent);
        this.post.setMiniature(false);
        this.onRoom(view.room.id);
      }
    });
    dom.addEventListener("pointerdown", (ev) => this.down.set(ev.clientX, ev.clientY));
    dom.addEventListener("pointerup", (ev) => {
      if (this.down.distanceTo(new THREE.Vector2(ev.clientX, ev.clientY)) > 5) return;
      const cell = this.build.pick(this.ndc(ev), this.rig.camera);
      if (cell) this.onSlot(cell);
    });
    dom.addEventListener("pointermove", (ev) => {
      dom.style.cursor = this.build.hover(this.ndc(ev), this.rig.camera) ? "pointer" : "";
    });
  }

  private frame(timestamp: number): void {
    this.clock.update(timestamp);
    const dt = Math.min(0.05, this.clock.getDelta());
    const time = this.clock.getElapsed();
    const s = this.store.get();
    const hostId = this.plan ? hostRoom(this.plan)?.id : undefined;
    this.rig.update(dt);
    this.house.update(dt);
    this.props.update(dt);
    this.lighting.update(dt, s.roomLights, hostId, s.voiceLevel);
    this.streaks.update(time, dt, s.assistant === "speaking" ? s.voiceLevel : 0, this.rig.camera);
    this.build.update(time);
    this.post.render(dt, screenBand(this.houseCorners, this.rig.camera));
    this.onFrame(this.anchors());
  }

  private anchors(): RoomAnchor[] {
    const v = new THREE.Vector3();
    const out: RoomAnchor[] = [];
    for (const view of this.house.rooms.values()) {
      v.copy(view.center).setY(view.wallTop + 0.5).add(view.group.position);
      v.project(this.rig.camera);
      out.push({
        id: view.room.id,
        x: ((v.x + 1) / 2) * this.width,
        y: ((1 - v.y) / 2) * this.height,
        visible: v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05,
      });
    }
    return out;
  }
}

/** The house from its plinth to its highest point: the tower's battlements, a wall cap or the tallest furniture. */
function houseBox(plan: Plan, bounds: Bounds): THREE.Box3 {
  const walls = plan.wall_height_m * DIM.exteriorCut + DIM.cap;
  const tower = towers(plan).length > 0 ? plan.wall_height_m * DIM.towerCut + DIM.merlon : 0;
  const o = DIM.plinthOverhang + DIM.stone;
  return new THREE.Box3(
    new THREE.Vector3(bounds.x0 - o, DIM.ground, bounds.z0 - o),
    new THREE.Vector3(bounds.x1 + o, Math.max(walls, tower, PROPS_TOP), bounds.z1 + o),
  );
}

/** The house's footprint in metres, its centre and the radius that encloses it. */
function footprint(plan: Plan): { bounds: Bounds; center: THREE.Vector3; radius: number } {
  const b = planBounds(plan);
  const c = plan.cell_m;
  const bounds = { x0: b.minX * c, z0: b.minY * c, x1: b.maxX * c, z1: b.maxY * c };
  const center = new THREE.Vector3((bounds.x0 + bounds.x1) / 2, 0, (bounds.z0 + bounds.z1) / 2);
  return { bounds, center, radius: Math.hypot(bounds.x1 - bounds.x0, bounds.z1 - bounds.z0) / 2 };
}
