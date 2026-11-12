// Shared materials. Textures are tileable and mapped in world metres, so a
// pattern runs on unbroken across walls and floors of any size.

import * as THREE from "three";
import { canvasTexture } from "./canvas";
import { palette } from "./palette";

/** Metres covered by one tile of each texture in assets/textures. */
const TILE_M: Record<string, number> = {
  wallpaper: 1.3,
  "teal-panel": 2.2,
  "wood-floor": 1.8,
  "red-carpet": 2.4,
  "pale-stone": 2.2,
  "roof-shingle": 2.0,
  "stone-tile": 2.8,
};

interface SurfaceLook {
  roughness: number;
  bump: number;
  tint?: number;
}

const LOOK: Record<string, SurfaceLook> = {
  wallpaper: { roughness: 0.82, bump: 0.6 },
  "teal-panel": { roughness: 0.5, bump: 1.6, tint: 0xc9d4cc },
  "wood-floor": { roughness: 0.42, bump: 1.2 },
  "red-carpet": { roughness: 0.97, bump: 1.0, tint: 0xd6c4bc },
  "pale-stone": { roughness: 0.88, bump: 2.6, tint: 0xd8cfc0 },
  "roof-shingle": { roughness: 0.8, bump: 1.5 },
  "stone-tile": { roughness: 0.78, bump: 1.6, tint: 0xb9b0a4 },
};

export class Materials {
  private readonly loader = new THREE.TextureLoader();
  private readonly surfaces = new Map<string, THREE.MeshStandardMaterial>();
  private readonly anisotropy: number;
  readonly wood: THREE.MeshStandardMaterial;
  readonly capStone: THREE.MeshStandardMaterial;
  readonly capWood: THREE.MeshStandardMaterial;
  readonly bronze: THREE.MeshStandardMaterial;
  readonly gilt: THREE.MeshStandardMaterial;
  readonly plinth: THREE.MeshStandardMaterial;

  constructor(
    renderer: THREE.WebGLRenderer,
    private readonly onMissing: (name: string) => void,
  ) {
    this.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    this.wood = new THREE.MeshStandardMaterial({ color: palette.walnut, roughness: 0.55 });
    this.capWood = new THREE.MeshStandardMaterial({ color: palette.capWood, roughness: 0.5 });
    this.bronze = new THREE.MeshStandardMaterial({ color: 0x5a4024, roughness: 0.35, metalness: 0.8 });
    this.gilt = new THREE.MeshStandardMaterial({ color: 0xb08a3e, roughness: 0.32, metalness: 0.9 });
    const stone = this.surface("pale-stone");
    this.capStone = stone.clone();
    this.capStone.color.set(0xf2e8d6);
    this.plinth = stone.clone();
    this.plinth.color.set(0x9a8f80);
  }

  /** The material for a texture named in the plan (floor or wall). */
  surface(name: string): THREE.MeshStandardMaterial {
    const cached = this.surfaces.get(name);
    if (cached) return cached;
    const look = LOOK[name] ?? { roughness: 0.8, bump: 0 };
    const material = new THREE.MeshStandardMaterial({ color: look.tint ?? 0xffffff, roughness: look.roughness });
    if (TILE_M[name] === undefined) {
      material.color.set(0x6b5a4a);
      this.onMissing(name);
    } else {
      const map = this.load(name, 1 / TILE_M[name]);
      material.map = map;
      if (look.bump > 0) {
        material.bumpMap = map;
        material.bumpScale = look.bump;
      }
    }
    this.surfaces.set(name, material);
    return material;
  }

  private load(name: string, repeat: number): THREE.Texture {
    const tex = this.loader.load(`assets/textures/${name}.png`, undefined, undefined, () => this.onMissing(name));
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(repeat, repeat);
    tex.anisotropy = this.anisotropy;
    return tex;
  }

  /** A hedge or lawn texture painted once on a canvas. */
  static foliage(base: string, speck: string, size = 256, count = 2600): THREE.CanvasTexture {
    return canvasTexture(size, (g) => {
      g.fillStyle = base;
      g.fillRect(0, 0, size, size);
      for (let i = 0; i < count; i++) {
        g.fillStyle = speck;
        g.globalAlpha = 0.08 + Math.random() * 0.3;
        const r = 0.6 + Math.random() * 2.2;
        g.beginPath();
        g.arc(Math.random() * size, Math.random() * size, r, 0, Math.PI * 2);
        g.fill();
      }
    });
  }
}

/** Planar UVs in metres from each face's dominant axis. Call once the geometry is in place. */
export function applyWorldUVs(geometry: THREE.BufferGeometry): void {
  const pos = geometry.getAttribute("position");
  const normal = geometry.getAttribute("normal");
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    const nx = Math.abs(normal.getX(i));
    const ny = Math.abs(normal.getY(i));
    const nz = Math.abs(normal.getZ(i));
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    const [u, v] = ny >= nx && ny >= nz ? [x, -z] : nx >= nz ? [z, y] : [x, y];
    uv[i * 2] = u;
    uv[i * 2 + 1] = v;
  }
  geometry.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
}
