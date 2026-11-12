// Build mode: every free slot of the plan glows on the lawn, and clicking one
// asks for a new room there.

import * as THREE from "three";
import type { Cell, Plan } from "../net/types";
import { DIM } from "./layout";
import { palette } from "./palette";

const vertexShader = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform float uHover;
  uniform vec3 uColor;
  varying vec2 vUv;
  void main() {
    vec2 d = abs(vUv - 0.5);
    float edge = max(d.x, d.y);
    float rim = smoothstep(0.43, 0.49, edge) * (1.0 - smoothstep(0.49, 0.5, edge));
    float fill = (1.0 - smoothstep(0.0, 0.5, edge)) * 0.18;
    float plus = (step(d.x, 0.012) * step(d.y, 0.09) + step(d.y, 0.012) * step(d.x, 0.09));
    float pulse = 0.65 + 0.35 * sin(uTime * 2.4);
    float k = (rim * 1.6 + fill + min(plus, 1.0) * 1.2) * pulse * (1.0 + uHover * 1.2);
    gl_FragColor = vec4(uColor * k, 1.0);
  }
`;

export class BuildMode {
  readonly root = new THREE.Group();
  private tiles: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>[] = [];
  private readonly raycaster = new THREE.Raycaster();
  private hovered: THREE.Mesh | null = null;
  active = false;

  constructor() {
    this.root.name = "build-slots";
    this.root.visible = false;
  }

  setPlan(plan: Plan): void {
    for (const t of this.tiles) {
      t.geometry.dispose();
      t.material.dispose();
      this.root.remove(t);
    }
    const c = plan.cell_m;
    this.tiles = plan.free_slots.map(([x, y]) => {
      const material = new THREE.ShaderMaterial({
        vertexShader,
        fragmentShader,
        uniforms: { uTime: { value: 0 }, uHover: { value: 0 }, uColor: { value: new THREE.Color(palette.mustard) } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const tile = new THREE.Mesh(new THREE.PlaneGeometry(c - 0.3, c - 0.3), material);
      tile.rotation.x = -Math.PI / 2;
      tile.position.set((x + 0.5) * c, DIM.ground + 0.08, (y + 0.5) * c);
      tile.userData["cell"] = [x, y] satisfies Cell;
      tile.renderOrder = 3;
      this.root.add(tile);
      return tile;
    });
  }

  setActive(on: boolean): void {
    this.active = on;
    this.root.visible = on;
  }

  /** The free slot under a point in normalised device coordinates, if build mode is on. */
  pick(ndc: THREE.Vector2, camera: THREE.Camera): Cell | null {
    if (!this.active) return null;
    this.raycaster.setFromCamera(ndc, camera);
    const hit = this.raycaster.intersectObjects(this.tiles, false)[0];
    return hit ? (hit.object.userData["cell"] as Cell) : null;
  }

  hover(ndc: THREE.Vector2, camera: THREE.Camera): boolean {
    if (!this.active) return false;
    this.raycaster.setFromCamera(ndc, camera);
    this.hovered = this.raycaster.intersectObjects(this.tiles, false)[0]?.object as THREE.Mesh | null ?? null;
    return this.hovered !== null;
  }

  update(time: number): void {
    if (!this.active) return;
    for (const t of this.tiles) {
      t.material.uniforms["uTime"]!.value = time;
      t.material.uniforms["uHover"]!.value = t === this.hovered ? 1 : 0;
    }
  }
}
