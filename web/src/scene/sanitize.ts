// Imported models are cleaned on load. A vertex normal of zero length becomes
// NaN once the vertex shader normalises it, the NaN fills every triangle that
// uses the vertex, and the bloom's mip chain spreads one NaN pixel over the
// whole frame, which tone-maps to black. The cabinet ships four such normals.

import * as THREE from "three";

const TINY = 1e-6;

/** Clean every mesh under `object`. */
export function sanitizeModel(object: THREE.Object3D): void {
  object.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    sanitizeGeometry(o.geometry as THREE.BufferGeometry);
    for (const m of [o.material].flat()) sanitizeMaterial(m as THREE.Material);
  });
}

/** Repair normals, drop broken tangents and zero non-finite UVs. Returns how many vertices were repaired. */
export function sanitizeGeometry(geometry: THREE.BufferGeometry): number {
  let repaired = repairNormals(geometry);
  const tangent = geometry.getAttribute("tangent");
  if (tangent && hasBadVector(tangent)) {
    geometry.deleteAttribute("tangent");
    repaired += tangent.count;
  }
  for (const name of ["uv", "uv1", "uv2", "uv3"]) {
    const uv = geometry.getAttribute(name);
    if (!uv) continue;
    for (let i = 0; i < uv.count; i++) {
      if (Number.isFinite(uv.getX(i)) && Number.isFinite(uv.getY(i))) continue;
      uv.setXY(i, 0, 0);
      repaired++;
    }
  }
  return repaired;
}

/**
 * Give every vertex whose normal is missing, zero or not finite the
 * area-weighted normal of the faces around it (straight up when it has none),
 * and bring the rest to unit length. Returns how many normals were rebuilt.
 */
export function repairNormals(geometry: THREE.BufferGeometry): number {
  const normal = geometry.getAttribute("normal");
  if (!normal) {
    geometry.computeVertexNormals();
    return geometry.getAttribute("position").count;
  }
  const bad = new Set<number>();
  const n = new THREE.Vector3();
  for (let i = 0; i < normal.count; i++) {
    n.fromBufferAttribute(normal, i);
    const length = n.length();
    if (!Number.isFinite(length) || length < TINY) bad.add(i);
    else if (Math.abs(length - 1) > 1e-3) normal.setXYZ(i, n.x / length, n.y / length, n.z / length);
  }
  if (bad.size === 0) return 0;

  const sums = new Map<number, THREE.Vector3>([...bad].map((i) => [i, new THREE.Vector3()]));
  const position = geometry.getAttribute("position");
  const index = geometry.getIndex();
  const vertex = (k: number): number => (index ? index.getX(k) : k);
  const [a, b, c] = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const face = new THREE.Vector3();
  const triangles = (index ? index.count : position.count) / 3;
  for (let t = 0; t < triangles; t++) {
    const ids = [vertex(t * 3), vertex(t * 3 + 1), vertex(t * 3 + 2)] as const;
    if (!ids.some((i) => bad.has(i))) continue;
    a.fromBufferAttribute(position, ids[0]);
    b.fromBufferAttribute(position, ids[1]);
    c.fromBufferAttribute(position, ids[2]);
    // The cross product's length is twice the face's area, so larger faces weigh more.
    face.subVectors(c, b).cross(a.sub(b));
    if (!Number.isFinite(face.lengthSq())) continue;
    for (const i of ids) sums.get(i)?.add(face);
  }
  for (const [i, sum] of sums) {
    if (sum.lengthSq() < TINY * TINY) sum.set(0, 1, 0);
    sum.normalize();
    normal.setXYZ(i, sum.x, sum.y, sum.z);
  }
  normal.needsUpdate = true;
  return bad.size;
}

/** Keep a material's factors in range: a NaN or negative factor poisons the frame the same way. */
export function sanitizeMaterial(material: THREE.Material): void {
  if (!(material instanceof THREE.MeshStandardMaterial)) return;
  material.roughness = unit(material.roughness, 1);
  material.metalness = unit(material.metalness, 0);
  material.emissiveIntensity = Number.isFinite(material.emissiveIntensity) ? Math.max(0, material.emissiveIntensity) : 0;
  if (!Number.isFinite(material.normalScale.x) || !Number.isFinite(material.normalScale.y)) material.normalScale.set(1, 1);
}

function unit(value: number, fallback: number): number {
  return Number.isFinite(value) ? THREE.MathUtils.clamp(value, 0, 1) : fallback;
}

function hasBadVector(attribute: THREE.BufferAttribute | THREE.InterleavedBufferAttribute): boolean {
  const v = new THREE.Vector3();
  for (let i = 0; i < attribute.count; i++) {
    const length = v.fromBufferAttribute(attribute, i).length();
    if (!Number.isFinite(length) || length < TINY || !Number.isFinite(attribute.getW(i))) return true;
  }
  return false;
}
