// The camera: an isometric-like view of the whole house, orbit and zoom within
// limits, a flight into a room on double-click and back home on request.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const FOV = 30;
/** Home view direction: from the south and a little west, well above the roofline. */
const HOME_AZIMUTH = THREE.MathUtils.degToRad(-40);
const HOME_ELEVATION = THREE.MathUtils.degToRad(50);
const ROOM_ELEVATION = THREE.MathUtils.degToRad(46);
const FLIGHT_S = 1.4;

interface Flight {
  fromPos: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toPos: THREE.Vector3;
  toTarget: THREE.Vector3;
  t: number;
}

export class CameraRig {
  readonly camera: THREE.PerspectiveCamera;
  readonly controls: OrbitControls;
  private homeTarget = new THREE.Vector3();
  private homeDistance = 40;
  private flight: Flight | null = null;
  /** The room the camera has flown into, or null at home. */
  room: string | null = null;

  constructor(dom: HTMLElement) {
    this.camera = new THREE.PerspectiveCamera(FOV, 1, 0.5, 600);
    this.controls = new OrbitControls(this.camera, dom);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.enablePan = false;
    this.controls.minPolarAngle = THREE.MathUtils.degToRad(14);
    this.controls.maxPolarAngle = THREE.MathUtils.degToRad(68);
    this.controls.rotateSpeed = 0.6;
    this.controls.zoomSpeed = 0.8;
  }

  setAspect(aspect: number): void {
    this.camera.aspect = aspect;
    this.camera.updateProjectionMatrix();
  }

  /** Fit the home view to the house: jump there, or glide there if the camera is home. */
  frame(center: THREE.Vector3, radius: number, jump: boolean): void {
    this.homeTarget.copy(center);
    const fit = radius / Math.sin(THREE.MathUtils.degToRad(FOV / 2));
    this.homeDistance = fit * Math.max(0.85, 1.25 / Math.min(1.6, this.camera.aspect));
    this.controls.minDistance = 5;
    this.controls.maxDistance = this.homeDistance * 1.5;
    if (jump) {
      this.camera.position.copy(this.homePosition());
      this.controls.target.copy(center);
      this.controls.update();
    } else if (this.room === null) {
      this.fly(this.homePosition(), center);
    }
  }

  home(): void {
    this.room = null;
    this.fly(this.homePosition(), this.homeTarget);
  }

  flyTo(room: string, center: THREE.Vector3, extent: THREE.Vector2): void {
    this.room = room;
    const size = Math.max(extent.x, extent.y, 4);
    const distance = size * 1.55 + 3;
    const target = center.clone().setY(0.6);
    const azimuth = Math.atan2(this.camera.position.x - this.controls.target.x, this.camera.position.z - this.controls.target.z);
    this.fly(target.clone().add(offset(azimuth, ROOM_ELEVATION, distance)), target);
  }

  /** Distance from the camera to what it looks at, for the depth of field. */
  focusDistance(): number {
    return this.camera.position.distanceTo(this.controls.target);
  }

  update(dt: number): void {
    if (this.flight) {
      const f = this.flight;
      f.t = Math.min(1, f.t + dt / FLIGHT_S);
      const k = f.t < 0.5 ? 4 * f.t ** 3 : 1 - (-2 * f.t + 2) ** 3 / 2;
      this.camera.position.lerpVectors(f.fromPos, f.toPos, k);
      this.controls.target.lerpVectors(f.fromTarget, f.toTarget, k);
      if (f.t >= 1) {
        this.flight = null;
        this.controls.enabled = true;
      }
    }
    this.controls.update(dt);
  }

  private homePosition(): THREE.Vector3 {
    return this.homeTarget.clone().add(offset(HOME_AZIMUTH, HOME_ELEVATION, this.homeDistance));
  }

  private fly(toPos: THREE.Vector3, toTarget: THREE.Vector3): void {
    this.controls.enabled = false;
    this.flight = {
      fromPos: this.camera.position.clone(),
      fromTarget: this.controls.target.clone(),
      toPos,
      toTarget: toTarget.clone(),
      t: 0,
    };
  }
}

/** A camera offset from its target: azimuth 0 looks from the south (+z). */
function offset(azimuth: number, elevation: number, distance: number): THREE.Vector3 {
  const flat = Math.cos(elevation) * distance;
  return new THREE.Vector3(Math.sin(azimuth) * flat, Math.sin(elevation) * distance, Math.cos(azimuth) * flat);
}
