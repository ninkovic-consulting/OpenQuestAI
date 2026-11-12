// The other agents' figures, one per agent in the cast, each standing in the
// room it is in (residence.ts) at a spot worked out from the room's floor
// (spot.ts). Figures no one can see skip their animation.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import type { Plan, RoomLight } from "../net/types";
import { characterOf } from "./cast";
import { blockObject, FloorGrid, type FloorShape } from "./floor";
import type { HouseView, RoomView } from "./house";
import { DIM } from "./layout";
import { residences } from "./residence";
import { Resident } from "./resident";
import { chooseSpot, SPOT_NEEDS, type Spot } from "./spot";

/** Kept clear around a room's lamp light, so it never sits inside a figure. */
const LAMP_CLEAR = 0.55;
/** Kept clear around a figure already standing in the room. */
const FIGURE_CLEAR = 0.35;

export class Residents {
  readonly root = new THREE.Group();
  private readonly loader = new GLTFLoader();
  private readonly figures = new Map<string, Resident>();
  private readonly loading = new Set<string>();
  /** Spots worked out for the current build of the house: per room, one for each figure in it. */
  private spots = new Map<string, Spot[]>();
  private plan: Plan | null = null;
  private lights: Readonly<Record<string, RoomLight>> = {};
  private readonly frustum = new THREE.Frustum();
  private readonly sphere = new THREE.Sphere();
  private readonly viewProjection = new THREE.Matrix4();

  constructor(
    private readonly house: HouseView,
    private readonly onMissing: (what: string) => void,
  ) {
    this.root.name = "residents";
  }

  /** Put every figure where the plan and the room lights say. Call after the house is rebuilt for a new plan. */
  sync(plan: Plan, lights: Readonly<Record<string, RoomLight>>): void {
    if (plan !== this.plan) this.spots = new Map();
    this.plan = plan;
    this.lights = lights;
    const placed = new Set<string>();
    const count = new Map<string, number>();
    plan.agents.forEach((agent, i) => this.ensure(agent.id, i / Math.max(1, plan.agents.length)));
    for (const home of residences(plan, lights)) {
      const figure = this.figures.get(home.agent);
      const view = this.house.rooms.get(home.room.id);
      if (!figure || !view) continue;
      const k = count.get(view.room.id) ?? 0;
      count.set(view.room.id, k + 1);
      const spot = this.spot(view, k);
      figure.set({ room: view.room.id, ...spot, group: view.group }, home.light === "active");
      placed.add(home.agent);
    }
    for (const [agent, figure] of this.figures) if (!placed.has(agent)) figure.set(null, false);
  }

  update(dt: number, camera: THREE.Camera): void {
    this.viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    this.frustum.setFromProjectionMatrix(this.viewProjection);
    for (const figure of this.figures.values()) {
      const bounds = figure.bounds(this.sphere);
      figure.update(dt, bounds !== null && this.frustum.intersectsSphere(bounds));
    }
  }

  /** Start loading an agent's figure once; it joins the house when it arrives. */
  private ensure(agent: string, phase: number): void {
    const character = characterOf(agent);
    if (!character || this.figures.has(agent) || this.loading.has(agent)) return;
    this.loading.add(agent);
    void Resident.load(this.loader, character, phase).then((figure) => {
      this.loading.delete(agent);
      if (!figure) {
        this.onMissing(`the ${character.model} figure`);
        return;
      }
      this.figures.set(agent, figure);
      this.root.add(figure.root);
      if (this.plan) this.sync(this.plan, this.lights);
    });
  }

  /** The spot for the `k`-th figure in a room, clear of the ones before it. */
  private spot(view: RoomView, k: number): Spot {
    const list = this.spots.get(view.room.id) ?? [];
    this.spots.set(view.room.id, list);
    for (let i = list.length; i <= k; i++) {
      const grid = new FloorGrid(floorShape(view));
      blockObject(grid, view.group, (mesh) => mesh === view.floor || mesh.material instanceof THREE.MeshBasicMaterial);
      grid.blockDisc(view.lampPosition.x, view.lampPosition.z, LAMP_CLEAR);
      for (const other of list) grid.blockDisc(other.x, other.z, FIGURE_CLEAR);
      list.push(
        chooseSpot(grid, {
          ...SPOT_NEEDS,
          doors: view.doors.map((d) => ({ x: d.x, z: d.y })),
          focus: view.focus ? { x: view.focus.x, z: view.focus.y } : null,
          centre: { x: view.center.x, z: view.center.z },
        }),
      );
    }
    return list[k] as Spot;
  }
}

/** The floor inside a room's walls. */
function floorShape(view: RoomView): FloorShape {
  const { center, extent } = view;
  if (view.room.shape === "round") return { kind: "round", cx: center.x, cz: center.z, r: extent.x / 2 };
  const hx = extent.x / 2 - DIM.lining;
  const hz = extent.y / 2 - DIM.lining;
  return { kind: "rect", x0: center.x - hx, z0: center.z - hz, x1: center.x + hx, z1: center.z + hz };
}
