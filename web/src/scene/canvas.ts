import * as THREE from "three";

/** Paint a square canvas once and wrap it as a repeating sRGB texture. */
export function canvasTexture(size: number, paint: (g: CanvasRenderingContext2D) => void): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const g = canvas.getContext("2d");
  if (!g) throw new Error("2D canvas is not available");
  paint(g);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  return tex;
}

/** A soft round glow, white in the middle and clear at the rim. */
export function glowTexture(): THREE.CanvasTexture {
  const tex = canvasTexture(128, (g) => {
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.3, "rgba(255,255,255,0.35)");
    grad.addColorStop(0.65, "rgba(255,255,255,0.08)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
  });
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
  return tex;
}

/**
 * Light thrown out of a window onto the ground: brightest at the wall (v = 0)
 * and fading outward, widening as it goes, with no hard rim.
 */
export function spillTexture(): THREE.CanvasTexture {
  const size = 128;
  const tex = canvasTexture(size, (g) => {
    const img = g.createImageData(size, size);
    for (let y = 0; y < size; y++) {
      // Canvas row 0 lands at v = 1 once the texture is flipped.
      const v = 1 - y / (size - 1);
      const along = Math.pow(1 - v, 1.8) * Math.min(1, v * 14);
      const spread = 0.16 + 0.22 * v;
      for (let x = 0; x < size; x++) {
        const u = (x / (size - 1) - 0.5) / spread;
        const a = along * Math.exp(-u * u * 1.6);
        const i = (y * size + x) * 4;
        // Alpha maps read the green channel.
        img.data[i] = img.data[i + 1] = img.data[i + 2] = Math.round(a * 255);
        img.data[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  });
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
  return tex;
}
