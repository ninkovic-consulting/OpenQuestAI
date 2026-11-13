// The 3D stage: renderer, scene and the frame loop, wired to the store. It
// draws only when something changed or moves (pacer.ts), at a rate and
// resolution set by the quality level, the automatic scaler and whether the
// assistant is working on this Mac; the shadow map is redrawn only when
// something that casts a shadow moved.

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
import { Residents } from "./residents";
import { displayPrefs, type DisplayPrefs } from "./display-prefs";
import { activityOf, labelsDue, shadowsDue, type FrameSignals } from "./frame-rules";
import { GpuTimer } from "./gpu-timer";
import { FrameMeter } from "./meter";
import { Pacer } from "./pacer";
import { workingHere, type Activity } from "./pacing";
import { LEVELS, pixelRatioRange, samplesFor, type QualityLevel } from "./quality";
import { Readout } from "./readout";
import { easeRatio, FRESH, scaleStep, type ScalerState } from "./scaler";

/** Screen kept clear around the fitted house, in CSS pixels (the bottom at least a share of the height): the key hints above, the caption below. */
const CLEAR = { top: 56, side: 24, bottom: 112, bottomShare: 0.12 };
/** How long the owner's pointer or a resize keeps the scene at the interaction rate, in milliseconds. */
const INPUT_MS = 400;
/** The pixel ratio changes by one small step at most this often, in milliseconds. */
const RATIO_STEP_MS = 100;
/** The frame time the scaler holds the scene to: room to draw 60 frames a second. */
const BUDGET_MS = 1000 / 60;

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
  private readonly residents: Residents;
  private readonly lighting: Lighting;
  private readonly grounds: Grounds;
  private readonly post: Post;
  private readonly streaks = new Streaks();
  private readonly build = new BuildMode();
  private readonly raycaster = new THREE.Raycaster();
  private readonly prefs = displayPrefs();
  private readonly pacer: Pacer;
  private readonly meter = new FrameMeter();
  private readonly shadowMeter = new FrameMeter();
  private readonly readout: Readout;
  private readonly gpu: GpuTimer;
  private readonly forceStats = new URLSearchParams(location.search).get("stats") === "1";
  private level: QualityLevel;
  private scaler: ScalerState = FRESH;
  /** The pixel ratio drawn at now; it eases toward the target. */
  private ratio: number;
  private ratioAt = -Infinity;
  /** Seconds of animation time, the sum of the steps of the frames drawn. */
  private time = 0;
  private shadowsForced = true;
  private shadowAt = -Infinity;
  private labelsStale = true;
  private labelsAt = -Infinity;
  private hasStreaks = false;
  private readonly pointer = new THREE.Vector2();
  private readonly anchorList: RoomAnchor[] = [];
  private readonly anchorPoint = new THREE.Vector3();
  private plan: Plan | null = null;
  /** The house's bounding box, for framing and the miniature blur. */
  private houseBox = new THREE.Box3();
  private houseCorners: THREE.Vector3[] = [];
  private width = 1;
  private height = 1;
  private readonly down = new THREE.Vector2();
  /** Called every frame with each room's label anchor on screen. */
  onFrame: (anchors: RoomAnchor[]) => void = () => {};
  /** Called when a glowing free slot is clicked in build mode. */
  onSlot: (cell: Cell) => void = () => {};
  /** Called with the room the camera flies into, and with null when it returns home. */
  onRoom: (roomId: string | null) => void = () => {};
  /** How much of the scene's left edge a card covers while a room shows, in pixels; the room is kept clear of it. */
  coverLeft: () => number = () => 0;

  constructor(
    private readonly container: HTMLElement,
    private readonly store: Store,
    notify: (text: string) => void,
  ) {
    this.level = LEVELS[this.prefs.get().quality];
    this.ratio = pixelRatioRange(this.prefs.get().quality, window.devicePixelRatio).max;
    this.renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance", stencil: false });
    this.renderer.setPixelRatio(this.ratio);
    this.renderer.shadowMap.enabled = true;
    // The house stands still: the shadow map is redrawn only when something that casts moved (frame-rules.ts).
    this.renderer.shadowMap.autoUpdate = false;
    // Count every pass of a frame, not just the last.
    this.renderer.info.autoReset = false;
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
    this.residents = new Residents(this.house, missing);
    this.lighting = new Lighting(this.scene, this.renderer);
    this.lighting.setShadowSize(this.level.shadowMapSize);
    this.grounds = new Grounds(mats);
    this.post = new Post(this.renderer, this.scene, this.rig.camera, samplesFor(this.level, this.ratio));
    this.post.setEffectScale(this.level.effectScale);
    this.gpu = new GpuTimer(this.renderer.getContext() as WebGL2RenderingContext);
    this.readout = new Readout(container);
    this.pacer = new Pacer(
      {
        setLoop: (callback) => this.renderer.setAnimationLoop(callback),
        draw: (dt, now) => this.frame(dt, now),
        sample: (frameMs, cpuMs, now) => this.sample(frameMs, cpuMs, now),
        idle: (now) => this.refreshReadout(now),
      },
      this.prefs.get().quality,
    );
    this.scene.add(this.house.root, this.props.root, this.residents.root, this.grounds.root, this.streaks.mesh, this.build.root);

    void this.props.load().then(() => this.forceShadows());
    this.listen();
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    store.subscribe((s, prev) => this.onState(s, prev));
    this.onState(store.get(), store.get());
    this.prefs.subscribe((p) => this.applyPrefs(p));
    this.applyPrefs(this.prefs.get());
  }

  start(): void {
    this.pacer.start();
  }

  /** Back to the whole-house view. Returns false when already there. */
  home(): boolean {
    if (this.rig.room === null) return false;
    this.rig.home();
    this.rig.setShift(0);
    this.post.setMiniature(true);
    this.onRoom(null);
    this.pacer.wake();
    return true;
  }

  /** Fly into a room and report it: what a double-click on the room does, and what the panel's room lists do. False for an unknown room. */
  focusRoom(id: string): boolean {
    const view = this.house.rooms.get(id);
    if (!view || this.build.active) return false;
    this.rig.flyTo(view.room.id, view.center, view.extent);
    this.post.setMiniature(false);
    this.onRoom(view.room.id);
    this.rig.setShift(this.coverLeft() / 2);
    this.pacer.wake();
    return true;
  }

  /** Settings (or anything else opaque) covers the whole scene, or no longer does. */
  setCovered(on: boolean): void {
    this.pacer.setCovered(on);
  }

  setBuildMode(on: boolean): void {
    this.build.setActive(on);
    if (on) this.home();
    this.pacer.wake();
  }

  /** Take the window's display preferences: quality, the readout, stepping back. */
  private applyPrefs(p: DisplayPrefs): void {
    const level = LEVELS[p.quality];
    if (level !== this.level) {
      this.level = level;
      this.scaler = FRESH;
      this.post.setMultisampling(samplesFor(level, this.ratio));
      this.post.setEffectScale(level.effectScale);
      this.lighting.setShadowSize(level.shadowMapSize);
      this.forceShadows();
    }
    this.pacer.setQuality(p.quality);
    this.readout.show(p.readout || this.forceStats);
    this.pacer.setStepBack(p.stepBack && workingHere(this.store.get()));
    this.pacer.wake();
  }

  private forceShadows(): void {
    this.shadowsForced = true;
    this.pacer.wake();
  }

  private onState(s: ViewState, prev: ViewState): void {
    if (s.plan && (s.plan !== this.plan || prev.plan === null)) this.rebuild(s.plan);
    const moved = s.roomLights !== prev.roomLights || s.agents !== prev.agents || s.jobs !== prev.jobs;
    if (s.plan && (s.plan !== prev.plan || moved)) this.residents.sync(s.plan, s.roomLights, s);
    this.props.setTalking(s.assistant === "speaking");
    this.pacer.setStepBack(this.prefs.get().stepBack && workingHere(s));
    this.labelsStale = true;
    this.pacer.wake();
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
    this.hasStreaks = hostView !== undefined;
    this.forceShadows();
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
    this.labelsStale = true;
    this.pacer.wake(INPUT_MS);
    this.rig.setAspect(this.width / this.height);
    this.rig.setSize(this.width, this.height);
    if (this.rig.room !== null) this.rig.setShift(this.coverLeft() / 2);
    if (this.plan) this.rig.frame(this.houseBox, this.clearWindow(), this.rig.room === null);
  }

  /** The pointer in normalised device coordinates; the same vector each time. */
  private ndc(ev: MouseEvent): THREE.Vector2 {
    const rect = this.renderer.domElement.getBoundingClientRect();
    return this.pointer.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
  }

  private listen(): void {
    const dom = this.renderer.domElement;
    dom.addEventListener("dblclick", (ev) => {
      if (this.build.active) return;
      this.raycaster.setFromCamera(this.ndc(ev), this.rig.camera);
      const hit = this.raycaster.intersectObjects(this.house.floors(), false)[0];
      const id = hit?.object.userData["roomId"] as string | undefined;
      if (id) this.focusRoom(id);
    });
    dom.addEventListener("pointerdown", (ev) => {
      this.down.set(ev.clientX, ev.clientY);
      this.pacer.wake(INPUT_MS);
    });
    dom.addEventListener("wheel", () => this.pacer.wake(INPUT_MS), { passive: true });
    dom.addEventListener("pointerup", (ev) => {
      this.pacer.wake(INPUT_MS);
      if (Math.hypot(ev.clientX - this.down.x, ev.clientY - this.down.y) > 5) return;
      const cell = this.build.pick(this.ndc(ev), this.rig.camera);
      if (cell) this.onSlot(cell);
    });
    dom.addEventListener("pointermove", (ev) => {
      if (ev.buttons !== 0) this.pacer.wake(INPUT_MS);
      if (!this.build.active) return;
      dom.style.cursor = this.build.hover(this.ndc(ev), this.rig.camera) ? "pointer" : "";
      this.pacer.wake();
    });
  }

  /** Draw one frame `dt` seconds after the last; answers how much of the scene is moving now. */
  private frame(dt: number, now: number): Activity {
    this.time += dt;
    const s = this.store.get();
    const hostId = this.plan ? hostRoom(this.plan)?.id : undefined;
    const camera = this.rig.update(dt);
    const rising = this.house.update(dt);
    const host = this.props.update(dt);
    const figures = this.residents.update(dt, this.rig.camera);
    const signals: FrameSignals = {
      camera,
      rising,
      figuresMoving: figures === "moving",
      figuresAnimating: figures === "animating" || host,
      lights: this.lighting.update(dt, s.roomLights, hostId, s.voiceLevel),
      voice: this.streaks.update(this.time, dt, s.assistant === "speaking" ? s.voiceLevel : 0, this.rig.camera),
      blur: this.post.update(dt, screenBand(this.houseCorners, this.rig.camera)),
      ambient: this.hasStreaks || this.build.active,
    };
    this.build.update(this.time);
    // Before the frame is drawn, never after: resizing clears the canvas, and a
    // cleared canvas left until the next frame shows as a flash.
    this.stepRatio(now);
    const shadows = shadowsDue(signals, this.shadowsForced, now - this.shadowAt);
    this.renderer.shadowMap.needsUpdate = shadows;
    if (shadows) {
      this.shadowsForced = false;
      this.shadowAt = now;
      this.shadowMeter.add(now, 0, 0);
    }
    this.renderer.info.reset();
    this.gpu.begin();
    this.post.render(dt);
    this.gpu.end();
    if (labelsDue(signals, this.labelsStale, now - this.labelsAt)) {
      this.labelsStale = false;
      this.labelsAt = now;
      this.onFrame(this.anchors());
    }
    return activityOf(signals);
  }

  /** One drawn frame's time: for the readout, and for the scaler unless the scene has stepped back for the assistant. */
  private sample(frameMs: number, cpuMs: number, now: number): void {
    this.meter.add(now, frameMs, cpuMs);
    if (!this.pacer.steppedBack) this.scaler = scaleStep(this.scaler, frameMs, Math.max(BUDGET_MS, this.pacer.tickMs()), this.level.minScale);
    this.refreshReadout(now);
  }

  /**
   * Move the drawn pixel ratio one small step toward where the quality and the
   * scaler put it. Called at the start of a frame, so the resized canvas is
   * drawn in the same turn and is never shown empty.
   */
  private stepRatio(now: number): void {
    const range = pixelRatioRange(this.prefs.get().quality, window.devicePixelRatio);
    const target = Math.max(range.min, range.max * this.scaler.scale);
    if (Math.abs(target - this.ratio) < 0.01 || now - this.ratioAt < RATIO_STEP_MS) return;
    this.ratio = easeRatio(this.ratio, target);
    this.ratioAt = now;
    this.renderer.setPixelRatio(this.ratio);
    this.post.setMultisampling(samplesFor(this.level, this.ratio));
    this.post.setSize(this.width, this.height);
    this.pacer.wake();
  }

  private refreshReadout(now: number): void {
    this.readout.refresh(now, () => {
      const info = this.renderer.info.render;
      return {
        reading: this.meter.read(now),
        pace: this.pacer.pace.label,
        quality: this.level.label + (this.scaler.scale < 1 ? ` · scaled to ${Math.round(this.scaler.scale * 100)}%` : ""),
        pixelRatio: this.ratio,
        width: this.renderer.domElement.width,
        height: this.renderer.domElement.height,
        calls: info.calls,
        triangles: info.triangles,
        gpuMs: this.gpu.read(),
        shadows: this.shadowMeter.read(now).fps,
      };
    });
  }

  /** Each room's label anchor on screen; the same objects each time. */
  private anchors(): RoomAnchor[] {
    const v = this.anchorPoint;
    const out = this.anchorList;
    let i = 0;
    for (const view of this.house.rooms.values()) {
      v.copy(view.center).setY(view.wallTop + 0.5).add(view.group.position);
      v.project(this.rig.camera);
      const a = out[i] ?? { id: "", x: 0, y: 0, visible: false };
      a.id = view.room.id;
      a.x = ((v.x + 1) / 2) * this.width;
      a.y = ((1 - v.y) / 2) * this.height;
      a.visible = v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05;
      out[i++] = a;
    }
    out.length = i;
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
