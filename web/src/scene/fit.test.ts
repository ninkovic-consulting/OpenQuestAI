import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { boxCorners, fitView, screenBand, type NdcWindow } from "./fit";

const FOV = THREE.MathUtils.degToRad(30);
const house = new THREE.Box3(new THREE.Vector3(-4, -0.5, -12), new THREE.Vector3(22, 3.4, 9));
const dir = new THREE.Vector3(Math.sin(-0.7) * Math.cos(0.87), Math.sin(0.87), Math.cos(-0.7) * Math.cos(0.87)).normalize();
const full: NdcWindow = { left: -0.95, right: 0.95, bottom: -0.95, top: 0.95 };

function cameraFor(aspect: number, window: NdcWindow): THREE.PerspectiveCamera {
  const fit = fitView(boxCorners(house), dir, FOV, aspect, window);
  const camera = new THREE.PerspectiveCamera(30, aspect, 0.5, 600);
  camera.position.copy(fit.target).addScaledVector(dir, fit.distance);
  camera.lookAt(fit.target);
  camera.updateMatrixWorld();
  return camera;
}

function projected(camera: THREE.Camera): THREE.Vector3[] {
  return boxCorners(house).map((p) => p.project(camera));
}

describe("fitting the house in view", () => {
  for (const aspect of [0.6, 1, 1.5, 2.4]) {
    it(`keeps every corner inside the window at aspect ${aspect}`, () => {
      const points = projected(cameraFor(aspect, full));
      for (const p of points) {
        expect(Math.abs(p.x)).toBeLessThanOrEqual(0.95 + 1e-6);
        expect(Math.abs(p.y)).toBeLessThanOrEqual(0.95 + 1e-6);
      }
      // Tight: the box touches the window on one axis, so it is as large as it can be.
      const spanX = Math.max(...points.map((p) => p.x)) - Math.min(...points.map((p) => p.x));
      const spanY = Math.max(...points.map((p) => p.y)) - Math.min(...points.map((p) => p.y));
      expect(Math.max(spanX, spanY)).toBeCloseTo(1.9, 3);
    });
  }

  it("stands further back on a narrow screen than on a wide one", () => {
    const narrow = fitView(boxCorners(house), dir, FOV, 0.8, full).distance;
    const wide = fitView(boxCorners(house), dir, FOV, 2, full).distance;
    expect(narrow).toBeGreaterThan(wide);
  });

  it("centres the box in an off-centre window", () => {
    const window: NdcWindow = { left: -0.9, right: 0.9, bottom: -0.7, top: 0.85 };
    const points = projected(cameraFor(1.4, window));
    const lo = Math.min(...points.map((p) => p.y));
    const hi = Math.max(...points.map((p) => p.y));
    expect(lo).toBeGreaterThanOrEqual(-0.7 - 1e-6);
    expect(hi).toBeLessThanOrEqual(0.85 + 1e-6);
    expect((lo + hi) / 2).toBeCloseTo(0.075, 2);
  });
});

describe("the house's band on screen", () => {
  it("spans the projected corners", () => {
    const camera = cameraFor(1.5, full);
    const band = screenBand(boxCorners(house), camera);
    const ys = projected(camera).map((p) => p.y);
    expect(band?.center).toBeCloseTo((Math.min(...ys) + Math.max(...ys)) / 2, 6);
    expect(band?.half).toBeCloseTo((Math.max(...ys) - Math.min(...ys)) / 2, 6);
  });

  it("is unknown when part of the house is behind the camera", () => {
    const camera = new THREE.PerspectiveCamera(30, 1.5, 0.5, 600);
    camera.position.set(9, 1, -1);
    camera.lookAt(9, 1, -20);
    camera.updateMatrixWorld();
    expect(screenBand(boxCorners(house), camera)).toBeNull();
  });
});
