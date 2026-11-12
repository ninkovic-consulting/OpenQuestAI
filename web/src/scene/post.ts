// Post-processing and the signal streaks. One render pass, a tilt-shift for
// the miniature look, then bloom, tone mapping, vignette and film grain in a
// single merged effect pass. The streaks are thin lines of light rising above
// the host room whose brightness and speed follow the voice level.

import {
  BloomEffect,
  BlendFunction,
  EffectComposer,
  EffectPass,
  NoiseEffect,
  RenderPass,
  TiltShiftEffect,
  ToneMappingEffect,
  ToneMappingMode,
  VignetteEffect,
} from "postprocessing";
import * as THREE from "three";
import { palette } from "./palette";

export class Post {
  readonly composer: EffectComposer;
  private readonly tilt: TiltShiftEffect;
  private miniature = 1;
  private miniatureTarget = 1;

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera) {
    this.composer = new EffectComposer(renderer, { frameBufferType: THREE.HalfFloatType, multisampling: 4 });
    this.composer.addPass(new RenderPass(scene, camera));
    this.tilt = new TiltShiftEffect({ focusArea: 0.5, feather: 0.32, offset: 0.04 });
    this.composer.addPass(new EffectPass(camera, this.tilt));
    const bloom = new BloomEffect({ luminanceThreshold: 0.75, luminanceSmoothing: 0.25, intensity: 1.15, radius: 0.72, mipmapBlur: true });
    const tone = new ToneMappingEffect({ mode: ToneMappingMode.ACES_FILMIC });
    const vignette = new VignetteEffect({ offset: 0.28, darkness: 0.72 });
    const grain = new NoiseEffect({ premultiply: true, blendFunction: BlendFunction.ADD });
    grain.blendMode.opacity.value = 0.55;
    this.composer.addPass(new EffectPass(camera, bloom, tone, vignette, grain));
  }

  setSize(width: number, height: number): void {
    this.composer.setSize(width, height);
  }

  /** Full miniature blur at home; mostly sharp inside a room. */
  setMiniature(on: boolean): void {
    this.miniatureTarget = on ? 1 : 0.25;
  }

  render(dt: number): void {
    this.miniature += (this.miniatureTarget - this.miniature) * Math.min(1, dt * 2.5);
    this.tilt.focusArea = 0.5 + (1 - this.miniature) * 0.35;
    this.tilt.feather = 0.32 + (1 - this.miniature) * 0.2;
    this.composer.render(dt);
  }
}

const STREAKS = 46;

const vertexShader = /* glsl */ `
  attribute vec4 streak;   // x, z, phase, speed
  attribute float corner;  // -1 or 1 across the line
  uniform vec3 uRight;
  uniform float uBase;
  uniform float uHeight;
  uniform float uWidth;
  varying float vAlong;
  varying float vPhase;
  varying float vSpeed;
  void main() {
    vAlong = position.y;
    vPhase = streak.z;
    vSpeed = streak.w;
    float h = uHeight * (0.55 + 0.45 * fract(streak.z * 7.13));
    vec3 p = vec3(streak.x, uBase + position.y * h, streak.y) + uRight * corner * uWidth;
    gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform float uLevel;
  uniform vec3 uColor;
  varying float vAlong;
  varying float vPhase;
  varying float vSpeed;
  void main() {
    float fade = smoothstep(0.0, 0.12, vAlong) * (1.0 - smoothstep(0.55, 1.0, vAlong));
    float pulse = fract(vAlong * 1.6 - uTime * vSpeed * (0.35 + uLevel * 1.4) + vPhase);
    float head = smoothstep(0.55, 1.0, pulse);
    float energy = 0.05 + uLevel * 1.7;
    gl_FragColor = vec4(uColor * (0.25 + head * 2.2) * fade * energy, 1.0);
  }
`;

export class Streaks {
  readonly mesh: THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial>;
  private level = 0;

  constructor() {
    const material = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uLevel: { value: 0 },
        uRight: { value: new THREE.Vector3(1, 0, 0) },
        uBase: { value: 1.6 },
        uHeight: { value: 9 },
        uWidth: { value: 0.018 },
        uColor: { value: new THREE.Color(palette.lamp) },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.mesh = new THREE.Mesh(new THREE.BufferGeometry(), material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 2;
  }

  /** Scatter the streaks over a room's floor, rising from its wall tops. */
  place(center: THREE.Vector3, extent: THREE.Vector2, wallTop: number): void {
    const positions: number[] = [];
    const corners: number[] = [];
    const streaks: number[] = [];
    const index: number[] = [];
    for (let i = 0; i < STREAKS; i++) {
      const x = center.x + (hash(i * 3.1) - 0.5) * extent.x * 0.9;
      const z = center.z + (hash(i * 5.7) - 0.5) * extent.y * 0.9;
      const phase = hash(i * 9.3);
      const speed = 0.4 + hash(i * 1.9) * 0.6;
      const base = i * 4;
      for (const [along, corner] of [
        [0, -1],
        [0, 1],
        [1, 1],
        [1, -1],
      ] as const) {
        positions.push(0, along, 0);
        corners.push(corner);
        streaks.push(x, z, phase, speed);
      }
      index.push(base, base + 1, base + 2, base, base + 2, base + 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute("corner", new THREE.Float32BufferAttribute(corners, 1));
    geo.setAttribute("streak", new THREE.Float32BufferAttribute(streaks, 4));
    geo.setIndex(index);
    this.mesh.geometry.dispose();
    this.mesh.geometry = geo;
    this.mesh.material.uniforms["uBase"]!.value = wallTop + 0.4;
  }

  update(time: number, dt: number, level: number, camera: THREE.Camera): void {
    this.level += (level - this.level) * Math.min(1, dt * 12);
    const u = this.mesh.material.uniforms;
    u["uTime"]!.value = time;
    u["uLevel"]!.value = this.level;
    (u["uRight"]!.value as THREE.Vector3).setFromMatrixColumn(camera.matrixWorld, 0).setY(0).normalize();
  }
}

function hash(n: number): number {
  const s = Math.sin(n * 127.1) * 43758.5453;
  return s - Math.floor(s);
}
