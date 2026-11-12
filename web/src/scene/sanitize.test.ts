import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { repairNormals, sanitizeGeometry, sanitizeMaterial } from "./sanitize";

/** Two triangles in the z = 0 plane facing +z, the shape the cabinet's broken corner has. */
function quad(normals: number[]): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  return g;
}

const good = [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1];

describe("repairing normals", () => {
  it("leaves sound normals alone", () => {
    const g = quad(good);
    expect(repairNormals(g)).toBe(0);
    expect([...(g.getAttribute("normal").array as Float32Array)]).toEqual(good);
  });

  it("rebuilds zero and NaN normals from the faces around them", () => {
    const g = quad([0, 0, 0, 0, 0, 1, Number.NaN, 0, 0, 0, 0, 1]);
    expect(repairNormals(g)).toBe(2);
    const n = g.getAttribute("normal");
    for (const i of [0, 2]) expect([n.getX(i), n.getY(i), n.getZ(i)]).toEqual([0, 0, 1]);
  });

  it("points a vertex with only degenerate faces straight up", () => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 2, 0, 0], 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute([0, 0, 0, 0, 0, 0, 0, 0, 0], 3));
    expect(repairNormals(g)).toBe(3);
    expect(g.getAttribute("normal").getY(1)).toBe(1);
  });

  it("brings long normals to unit length", () => {
    const g = quad([0, 0, 3, 0, 0, 1, 0, 0, 1, 0, 0, 1]);
    repairNormals(g);
    expect(g.getAttribute("normal").getZ(0)).toBeCloseTo(1, 6);
  });

  it("computes normals a geometry lacks", () => {
    const g = quad(good);
    g.deleteAttribute("normal");
    repairNormals(g);
    expect(g.getAttribute("normal").getZ(3)).toBeCloseTo(1, 6);
  });
});

describe("sanitising a geometry", () => {
  it("drops tangents with a zero vector and zeroes non-finite UVs", () => {
    const g = quad(good);
    g.setAttribute("tangent", new THREE.Float32BufferAttribute([1, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1], 4));
    g.getAttribute("uv").setXY(2, Number.POSITIVE_INFINITY, 0.5);
    sanitizeGeometry(g);
    expect(g.getAttribute("tangent")).toBeUndefined();
    expect([g.getAttribute("uv").getX(2), g.getAttribute("uv").getY(2)]).toEqual([0, 0]);
  });

  it("keeps sound tangents", () => {
    const g = quad(good);
    g.setAttribute("tangent", new THREE.Float32BufferAttribute(new Array(4).fill([1, 0, 0, 1]).flat(), 4));
    expect(sanitizeGeometry(g)).toBe(0);
    expect(g.getAttribute("tangent")).toBeDefined();
  });
});

describe("sanitising a material", () => {
  it("clamps factors into range", () => {
    const m = new THREE.MeshStandardMaterial({ roughness: 1.7, metalness: Number.NaN, emissiveIntensity: -2 });
    m.normalScale.set(Number.NaN, 1);
    sanitizeMaterial(m);
    expect([m.roughness, m.metalness, m.emissiveIntensity, m.normalScale.x]).toEqual([1, 0, 0, 1]);
  });
});
