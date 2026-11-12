// Dusk: a low cool sky and a moon with soft shadows outside; inside, one warm
// tungsten lamp per room whose brightness eases toward the room's state.

import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import type { RoomLight } from "../net/types";
import type { HouseView, RoomView } from "./house";
import { palette } from "./palette";

const LEVEL: Record<RoomLight, number> = { dark: 0.04, idle: 0.75, active: 1 };
/** The tower always smoulders, whatever its state. */
const TOWER_FLOOR = 0.7;
const EASE_PER_S = 2.2;

interface Lamp {
  view: RoomView;
  light: THREE.PointLight;
  level: number;
  base: number;
}

export class Lighting {
  readonly moon: THREE.DirectionalLight;
  private lamps: Lamp[] = [];

  constructor(scene: THREE.Scene, renderer: THREE.WebGLRenderer) {
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environmentIntensity = 0.07;
    pmrem.dispose();

    scene.add(new THREE.HemisphereLight(palette.sky, palette.earth, 1.15));

    this.moon = new THREE.DirectionalLight(palette.moon, 2.1);
    this.moon.castShadow = true;
    this.moon.shadow.mapSize.set(2048, 2048);
    this.moon.shadow.radius = 4;
    this.moon.shadow.bias = -0.0006;
    this.moon.shadow.normalBias = 0.03;
    scene.add(this.moon, this.moon.target);
  }

  /** Re-attach one lamp per room after the house was rebuilt, and aim the moon at it. */
  sync(house: HouseView, center: THREE.Vector3, radius: number): void {
    const previous = new Map(this.lamps.map((l) => [l.view.room.id, l.level]));
    this.lamps = [];
    for (const view of house.rooms.values()) {
      const round = view.room.shape === "round";
      const size = Math.max(view.extent.x, view.extent.y);
      const light = new THREE.PointLight(round ? palette.towerGlow : palette.lamp, 0, size * 1.35 + 3, 1.6);
      light.position.copy(view.lampPosition);
      view.group.add(light);
      const base = round ? 70 : 14 + view.extent.x * view.extent.y * 0.45;
      this.lamps.push({ view, light, level: previous.get(view.room.id) ?? 0, base });
    }
    this.moon.position.set(center.x - radius * 1.1, radius * 1.5, center.z + radius * 0.7);
    this.moon.target.position.copy(center);
    const cam = this.moon.shadow.camera;
    cam.left = cam.bottom = -radius * 1.25;
    cam.right = cam.top = radius * 1.25;
    cam.near = 1;
    cam.far = radius * 5;
    cam.updateProjectionMatrix();
  }

  update(dt: number, lights: Record<string, RoomLight>, hostId: string | undefined, voice: number): void {
    const step = Math.min(1, dt * EASE_PER_S);
    for (const lamp of this.lamps) {
      const room = lamp.view.room;
      let target = LEVEL[lights[room.id] ?? room.state];
      if (room.shape === "round") target = Math.max(target, TOWER_FLOOR);
      lamp.level += (target - lamp.level) * step;
      const flicker = room.id === hostId ? 1 + voice * 0.18 : 1;
      const k = lamp.level * flicker;
      lamp.light.intensity = lamp.base * k;
      lamp.view.glow.emissiveIntensity = 3.2 * k;
      lamp.view.spill.opacity = (room.shape === "round" ? 0.1 : 0.05) * k;
    }
  }
}
