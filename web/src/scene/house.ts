// The mansion, built from the plan: floors, low-cut walls with doors and
// windows, a round tower, and enough dressing that empty rooms feel lived in.
// Each room owns a group; a room that is new since the last build rises into
// place.

import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import type { Plan, Room } from "../net/types";
import { glowTexture, spillTexture } from "./canvas";
import { floorDressing, lamp, painting, type Add, type DecorContext } from "./decor";
import { cellKey, cellOwners, edgeOf, towers, wallEdges, wallRuns, type Tower, type WallRun } from "./grid";
import { furnish } from "./furnish";
import { DIM, HOST_LAYOUT } from "./layout";
import { applyWorldUVs, type Materials } from "./materials";
import { palette } from "./palette";
import { box, flat, slab } from "./shapes";

export interface RoomView {
  room: Room;
  group: THREE.Group;
  /** Pickable floor. */
  floor: THREE.Mesh;
  /** Centre of the floor, world space. */
  center: THREE.Vector3;
  /** Floor size in metres (x, z). */
  extent: THREE.Vector2;
  wallTop: number;
  /** Where the room's lamp light hangs, in the group's space. */
  lampPosition: THREE.Vector3;
  /** Door centres on the floor, in metres (x, z). */
  doors: THREE.Vector2[];
  /** The middle of the room's main built piece (x, z), or null when it has none. */
  focus: THREE.Vector2 | null;
  /** Lamp shades and window glass; its emissive follows the room's light. */
  glow: THREE.MeshStandardMaterial;
  /** Light thrown on the lawn under the windows. */
  spill: THREE.MeshBasicMaterial;
}

const RISE_S = 1.6;
const POOL_TEXTURE = glowTexture();
const SPILL_TEXTURE = spillTexture();
const SPILL_DEPTH = 3.4;

export class HouseView {
  readonly root = new THREE.Group();
  readonly rooms = new Map<string, RoomView>();
  private rising: { group: THREE.Group; depth: number; t: number }[] = [];
  private builtOnce = false;

  constructor(
    private readonly mats: Materials,
    private readonly furnished: (plan: Plan) => string | undefined,
  ) {
    this.root.name = "house";
  }

  /** Rebuild from the plan. Returns the ids of rooms that are new since the last build. */
  build(plan: Plan): string[] {
    const before = new Set(this.rooms.keys());
    this.clear();
    const builder = new Builder(plan, this.mats, this.furnished(plan));
    for (const view of builder.build()) {
      this.rooms.set(view.room.id, view);
      this.root.add(view.group);
    }
    const added = this.builtOnce ? [...this.rooms.keys()].filter((id) => !before.has(id)) : [];
    for (const id of added) {
      const view = this.rooms.get(id);
      if (view) {
        const depth = view.wallTop + 1.2;
        view.group.position.y = -depth;
        this.rising.push({ group: view.group, depth, t: 0 });
      }
    }
    this.builtOnce = true;
    return added;
  }

  update(dt: number): void {
    this.rising = this.rising.filter((r) => {
      r.t = Math.min(1, r.t + dt / RISE_S);
      const eased = 1 - Math.pow(1 - r.t, 3);
      const settle = Math.sin(r.t * Math.PI) * 0.06;
      r.group.position.y = r.t >= 1 ? 0 : (eased - 1) * r.depth + settle;
      return r.t < 1;
    });
  }

  floors(): THREE.Object3D[] {
    return [...this.rooms.values()].map((v) => v.floor);
  }

  private clear(): void {
    for (const view of this.rooms.values()) {
      this.root.remove(view.group);
      view.group.traverse((o) => {
        if (o instanceof THREE.Mesh) o.geometry.dispose();
      });
      view.glow.dispose();
      view.spill.dispose();
    }
    this.rooms.clear();
    this.rising = [];
  }
}

/** One build of the whole house. */
class Builder {
  private readonly c: number;
  private readonly hInt: number;
  private readonly hExt: number;
  private readonly owners: Map<string, Room>;
  private readonly order: Map<string, number>;
  private readonly buckets = new Map<string, Map<THREE.Material, THREE.BufferGeometry[]>>();
  private readonly extras = new Map<string, THREE.Object3D[]>();
  private readonly glows = new Map<string, THREE.MeshStandardMaterial>();
  private readonly spills = new Map<string, THREE.MeshBasicMaterial>();

  constructor(
    private readonly plan: Plan,
    private readonly mats: Materials,
    private readonly furnishedId: string | undefined,
  ) {
    this.c = plan.cell_m;
    this.hInt = plan.wall_height_m * DIM.interiorCut;
    this.hExt = plan.wall_height_m * DIM.exteriorCut;
    this.owners = cellOwners(plan);
    this.order = new Map(plan.rooms.map((r, i) => [r.id, i]));
    for (const room of plan.rooms) {
      const round = room.shape === "round";
      // A round tower's lining glows itself: its wall texture lit from within in deep red.
      const lining = round ? mats.surface(room.wall).map : null;
      this.glows.set(
        room.id,
        new THREE.MeshStandardMaterial({
          color: round ? 0x4a0c06 : 0x3a2a18,
          map: lining,
          emissive: round ? palette.towerGlow : palette.lamp,
          emissiveMap: lining,
          emissiveIntensity: 0,
          roughness: round ? 0.9 : 0.4,
          side: THREE.DoubleSide,
        }),
      );
      this.spills.set(
        room.id,
        new THREE.MeshBasicMaterial({
          color: round ? palette.towerGlow : palette.lamp,
          alphaMap: round ? POOL_TEXTURE : SPILL_TEXTURE,
          transparent: true,
          opacity: 0,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        }),
      );
    }
  }

  build(): RoomView[] {
    for (const run of wallRuns(this.plan)) this.wall(run);
    this.corners();
    const towerList = towers(this.plan);
    for (const t of towerList) this.tower(t);
    const views: RoomView[] = [];
    for (const room of this.plan.rooms) {
      const tower = towerList.find((t) => t.room.id === room.id);
      views.push(tower ? this.towerRoom(tower) : this.rectRoom(room));
    }
    return views;
  }

  // ---------------------------------------------------------------- buckets

  private adder(roomId: string): Add {
    return (material, geometry) => {
      let byMat = this.buckets.get(roomId);
      if (!byMat) this.buckets.set(roomId, (byMat = new Map()));
      const list = byMat.get(material);
      if (list) list.push(geometry);
      else byMat.set(material, [geometry]);
    };
  }

  private isRect(id: string | null): id is string {
    return id !== null && this.plan.rooms.some((r) => r.id === id && r.shape === "rect");
  }

  /** The longest-standing of the given rooms owns shared pieces, so they stay put when a neighbour rises. */
  private elder(ids: (string | null | undefined)[]): string | undefined {
    return ids
      .filter((id): id is string => typeof id === "string" && this.order.has(id))
      .sort((p, q) => (this.order.get(p) ?? 0) - (this.order.get(q) ?? 0))[0];
  }

  /** A mesh that keeps its own UVs and material, outside the merge. */
  private extra(roomId: string, object: THREE.Object3D): void {
    const list = this.extras.get(roomId);
    if (list) list.push(object);
    else this.extras.set(roomId, [object]);
  }

  private finishGroup(roomId: string, group: THREE.Group): void {
    for (const [material, geometries] of this.buckets.get(roomId) ?? []) {
      const merged = mergeGeometries(geometries);
      for (const g of geometries) g.dispose();
      if (!merged) continue;
      applyWorldUVs(merged);
      const mesh = new THREE.Mesh(merged, material);
      mesh.castShadow = material instanceof THREE.MeshStandardMaterial && material !== this.glows.get(roomId);
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    for (const o of this.extras.get(roomId) ?? []) group.add(o);
  }

  // ---------------------------------------------------------------- walls

  private wall(run: WallRun): void {
    const { c } = this;
    const line = run.line * c;
    const windowed = run.exterior && (this.isRect(run.a) || this.isRect(run.b));
    const pieces = this.pieces(run, windowed);
    const sides: { id: string | null; sign: -1 | 1 }[] = [
      { id: run.a, sign: -1 },
      { id: run.b, sign: 1 },
    ];
    const inner = sides.filter((s) => this.isRect(s.id));
    const outer = sides.find((s) => !this.isRect(s.id));
    const capOwner = this.elder(inner.map((s) => s.id)) ?? "";
    let lo = 0;
    let hi = 0;

    for (const side of inner) {
      const id = side.id as string;
      const add = this.adder(id);
      const wallMat = this.mats.surface(this.roomOf(id).wall);
      const t = side.sign * DIM.lining;
      for (const p of pieces) {
        add(wallMat, slab(run.axis, line, [p.a, p.b], sorted(0, t), [-DIM.floorDepth, p.top]));
        add(this.mats.wood, slab(run.axis, line, [p.a, p.b], sorted(t, t + side.sign * 0.022), [0, Math.min(0.13, p.top)]));
      }
      lo = Math.min(lo, t);
      hi = Math.max(hi, t);
    }
    if (outer) {
      const add = this.adder(capOwner);
      const t = outer.sign * DIM.stone;
      for (const p of pieces) add(this.mats.surface("pale-stone"), slab(run.axis, line, [p.a, p.b], sorted(0, t), [-DIM.floorDepth, p.top]));
      lo = Math.min(lo, t);
      hi = Math.max(hi, t);
    }
    const capMat = run.exterior ? this.mats.capStone : this.mats.capWood;
    const add = this.adder(capOwner);
    for (const p of pieces) add(capMat, slab(run.axis, line, [p.a, p.b], [lo - 0.025, hi + 0.025], [p.top, p.top + DIM.cap]));
    for (const d of run.doors) {
      const mid = d * c;
      add(this.mats.capWood, slab(run.axis, line, [mid - DIM.door / 2, mid + DIM.door / 2], [lo, hi], [-0.02, 0.012]));
    }
    if (windowed && outer) this.windows(run, pieces, line, outer.sign, capOwner);
  }

  /** Solid stretches of a run, with door gaps cut out and window stretches lowered to the sill. */
  private pieces(run: WallRun, windowed: boolean): { a: number; b: number; top: number }[] {
    const { c } = this;
    const h = run.exterior ? this.hExt : this.hInt;
    const cuts: { a: number; b: number; top: number }[] = run.doors.map((d) => ({ a: d * c - DIM.door / 2, b: d * c + DIM.door / 2, top: 0 }));
    if (windowed) {
      for (let k = run.from; k < run.to; k++) {
        if (run.doors.some((d) => d > k && d < k + 1)) continue;
        const mid = (k + 0.5) * c;
        cuts.push({ a: mid - DIM.window / 2, b: mid + DIM.window / 2, top: DIM.sill });
      }
    }
    cuts.sort((p, q) => p.a - q.a);
    const out: { a: number; b: number; top: number }[] = [];
    let at = run.from * c;
    for (const cut of cuts) {
      if (cut.a > at) out.push({ a: at, b: cut.a, top: h });
      if (cut.top > 0) out.push(cut);
      at = cut.b;
    }
    if (run.to * c > at) out.push({ a: at, b: run.to * c, top: h });
    return out;
  }

  private windows(run: WallRun, pieces: { a: number; b: number; top: number }[], line: number, out: -1 | 1, owner: string): void {
    const room = run.a !== null && this.isRect(run.a) ? run.a : (run.b as string);
    const add = this.adder(room);
    const glow = this.glows.get(room) as THREE.Material;
    const spill = this.spills.get(room) as THREE.Material;
    const top = this.hExt;
    for (const p of pieces.filter((q) => q.top === DIM.sill)) {
      const across = sorted(-out * DIM.lining * 0.5, out * DIM.stone * 0.5);
      add(glow, slab(run.axis, line, [p.a, p.b], [across[0] * 0.2, across[1] * 0.2], [DIM.sill, top - 0.03]));
      const mid = (p.a + p.b) / 2;
      add(this.mats.capWood, slab(run.axis, line, [mid - 0.03, mid + 0.03], [-0.04, 0.04], [DIM.sill, top - 0.03]));
      add(this.mats.capWood, slab(run.axis, line, [p.a, p.b], [-0.04, 0.04], [DIM.sill + (top - DIM.sill) * 0.55, DIM.sill + (top - DIM.sill) * 0.55 + 0.05]));
      this.adder(owner)(this.mats.capStone, slab(run.axis, line, [p.a - 0.08, p.b + 0.08], sorted(0, out * (DIM.stone + 0.08)), [DIM.sill - 0.06, DIM.sill]));
      this.extra(room, spillMesh(windowSpill(run.axis, line, mid, out), spill));
    }
  }

  /** Fill the corner squares that no run covers, so walls meet cleanly. */
  private corners(): void {
    const edges = wallEdges(this.plan);
    const vertices = new Set<string>();
    for (const e of edges.values()) {
      vertices.add(cellKey(e.x, e.y));
      vertices.add(e.axis === "h" ? cellKey(e.x + 1, e.y) : cellKey(e.x, e.y + 1));
    }
    for (const v of vertices) {
      const [gx, gy] = v.split(",").map(Number) as [number, number];
      const arm = { n: edges.get(`v:${gx}:${gy - 1}`), s: edges.get(`v:${gx}:${gy}`), w: edges.get(`h:${gx - 1}:${gy}`), e: edges.get(`h:${gx}:${gy}`) };
      const exterior = Object.values(arm).some((e) => e?.exterior);
      const top = exterior ? this.hExt : this.hInt;
      const quadrants = [
        { cell: [gx - 1, gy - 1], arms: [arm.n, arm.w], sx: -1, sz: -1 },
        { cell: [gx, gy - 1], arms: [arm.n, arm.e], sx: 1, sz: -1 },
        { cell: [gx - 1, gy], arms: [arm.s, arm.w], sx: -1, sz: 1 },
        { cell: [gx, gy], arms: [arm.s, arm.e], sx: 1, sz: 1 },
      ] as const;
      const rooms = quadrants.map((q) => this.owners.get(cellKey(q.cell[0], q.cell[1]))?.id);
      const elder = this.elder(rooms.filter((id) => this.isRect(id ?? null))) ?? "";
      quadrants.forEach((q, i) => {
        if (q.arms.some((a) => a !== undefined)) return;
        const id = rooms[i] ?? null;
        const rect = this.isRect(id);
        const size = rect ? DIM.lining : DIM.stone;
        const x = gx * this.c;
        const z = gy * this.c;
        const geo = box(x, -DIM.floorDepth, z, x + q.sx * size, top, z + q.sz * size);
        const owner = rect ? (id as string) : elder;
        this.adder(owner)(rect ? this.mats.surface(this.roomOf(owner).wall) : this.mats.surface("pale-stone"), geo);
        const cap = rect ? this.mats.capWood : this.mats.capStone;
        this.adder(owner)(cap, box(x - q.sx * 0.025, top, z - q.sz * 0.025, x + q.sx * (size + 0.025), top + DIM.cap, z + q.sz * (size + 0.025)));
      });
    }
  }

  // ---------------------------------------------------------------- rooms

  private roomOf(id: string): Room {
    const room = this.plan.rooms.find((r) => r.id === id);
    if (!room) throw new Error(`no room ${id}`);
    return room;
  }

  private doorCentres(room: Room): THREE.Vector2[] {
    return this.plan.doors
      .filter((d) => d.a === room.id || d.b === room.id)
      .map((d) => {
        const e = edgeOf(d.cell, d.side);
        return e.axis === "h" ? new THREE.Vector2((e.x + 0.5) * this.c, e.y * this.c) : new THREE.Vector2(e.x * this.c, (e.y + 0.5) * this.c);
      });
  }

  private rectRoom(room: Room): RoomView {
    const { c } = this;
    const add = this.adder(room.id);
    const x0 = room.at[0] * c;
    const z0 = room.at[1] * c;
    const x1 = x0 + room.size[0] * c;
    const z1 = z0 + room.size[1] * c;
    const floorGeo = box(x0, -DIM.floorDepth, z0, x1, 0, z1);
    applyWorldUVs(floorGeo);
    const floor = new THREE.Mesh(floorGeo, this.mats.surface(room.floor));
    floor.receiveShadow = true;
    floor.userData["roomId"] = room.id;
    const o = DIM.plinthOverhang;
    add(this.mats.plinth, box(x0 - o, DIM.ground, z0 - o, x1 + o, -DIM.floorDepth, z1 + o));

    const glow = this.glows.get(room.id) as THREE.MeshStandardMaterial;
    const ctx: DecorContext = {
      room,
      x0: x0 + DIM.lining,
      z0: z0 + DIM.lining,
      x1: x1 - DIM.lining,
      z1: z1 - DIM.lining,
      doors: this.doorCentres(room),
      add,
      mats: this.mats,
      glow,
    };
    floorDressing(ctx, this.order.get(room.id) ?? 0);
    const center = new THREE.Vector3((x0 + x1) / 2, 0, (z0 + z1) / 2);
    let lampPosition: THREE.Vector3;
    let focus: THREE.Vector2 | null = null;
    if (room.id === this.furnishedId) {
      // Hung high and back, so the lamp warms the room without blowing out the seated figure.
      lampPosition = center.clone().add(new THREE.Vector3(HOST_LAYOUT.lamp.x * 0.6, 2.9, -1.6));
    } else {
      lampPosition = lamp(ctx);
      focus = furnish(ctx);
      if (!focus) {
        const art = painting(ctx, this.order.get(room.id) ?? 0);
        if (art) this.extra(room.id, art);
      }
    }
    const group = new THREE.Group();
    group.name = `room:${room.id}`;
    group.add(floor);
    this.finishGroup(room.id, group);
    return {
      room,
      group,
      floor,
      center,
      extent: new THREE.Vector2(x1 - x0, z1 - z0),
      wallTop: this.hExt,
      lampPosition,
      doors: ctx.doors,
      focus,
      glow,
      spill: this.spills.get(room.id) as THREE.MeshBasicMaterial,
    };
  }

  private tower(t: Tower): void {
    const add = this.adder(t.room.id);
    const cx = t.cx * this.c;
    const cz = t.cy * this.c;
    const r = t.radius * this.c - 0.3;
    const top = this.plan.wall_height_m * DIM.towerCut;
    const gap = DIM.door / r;
    const segments = 48;
    // Angles follow Three's cylinder: theta 0 points to +z (south), increasing toward +x (east).
    const doorAngles = t.doorSides.map((s) => ({ s: 0, e: Math.PI / 2, n: Math.PI, w: (3 * Math.PI) / 2 })[s]);
    const arcs: [number, number][] = [];
    if (doorAngles.length === 0) arcs.push([0, Math.PI * 2]);
    else {
      const sortedAngles = [...doorAngles].sort((p, q) => p - q);
      sortedAngles.forEach((a, i) => {
        const next = sortedAngles[(i + 1) % sortedAngles.length] ?? a;
        const end = i + 1 < sortedAngles.length ? next : next + Math.PI * 2;
        arcs.push([a + gap / 2, end - a - gap]);
      });
    }
    const lining = this.glows.get(t.room.id) as THREE.Material;
    for (const [start, length] of arcs) {
      const steps = Math.max(4, Math.round((segments * length) / (Math.PI * 2)));
      const outer = new THREE.CylinderGeometry(r + DIM.stone, r + DIM.stone, top + DIM.floorDepth, steps, 1, true, start, length);
      outer.translate(cx, (top - DIM.floorDepth) / 2, cz);
      add(this.mats.surface("pale-stone"), outer);
      const inner = facingIn(new THREE.CylinderGeometry(r, r, top + DIM.floorDepth, steps, 1, true, start, length));
      inner.translate(cx, (top - DIM.floorDepth) / 2, cz);
      add(lining, inner);
      // Ring angles start at +x; cylinder angles start at +z.
      const cap = new THREE.RingGeometry(r - 0.03, r + DIM.stone + 0.03, steps, 1, start - Math.PI / 2, length);
      cap.rotateX(-Math.PI / 2);
      cap.translate(cx, top, cz);
      add(this.mats.capStone, cap);
    }
    // Battlements: merlons around the rim, clear of the doors.
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2;
      if (doorAngles.some((d) => Math.abs(Math.atan2(Math.sin(a - d), Math.cos(a - d))) < gap)) continue;
      const m = new THREE.BoxGeometry(DIM.merlon, DIM.merlon, DIM.stone + 0.04);
      m.translate(0, 0, r + DIM.stone / 2);
      m.rotateY(a);
      m.translate(cx, top + DIM.merlon / 2, cz);
      add(this.mats.capStone, m);
    }
    // Arrow slits glowing red on the outside.
    for (const a of [Math.PI * 0.25, Math.PI * 0.75, Math.PI * 1.25, Math.PI * 1.75]) {
      if (doorAngles.some((d) => Math.abs(Math.atan2(Math.sin(a - d), Math.cos(a - d))) < 0.6)) continue;
      const slit = new THREE.BoxGeometry(0.16, 0.9, 0.04);
      slit.translate(0, 0, r + DIM.stone + 0.005);
      slit.rotateY(a);
      slit.translate(cx, top * 0.5, cz);
      add(lining, slit);
    }
  }

  private towerRoom(t: Tower): RoomView {
    const room = t.room;
    const add = this.adder(room.id);
    const cx = t.cx * this.c;
    const cz = t.cy * this.c;
    const r = t.radius * this.c - 0.3;
    const floorGeo = new THREE.CylinderGeometry(r + 0.02, r + 0.02, DIM.floorDepth, 40).translate(cx, -DIM.floorDepth / 2, cz);
    applyWorldUVs(floorGeo);
    const floor = new THREE.Mesh(floorGeo, this.mats.surface(room.floor));
    floor.receiveShadow = true;
    floor.userData["roomId"] = room.id;
    add(this.mats.plinth, new THREE.CylinderGeometry(r + DIM.stone + 0.4, r + DIM.stone + 0.5, -DIM.ground - DIM.floorDepth, 40).translate(cx, (DIM.ground - DIM.floorDepth) / 2, cz));
    add(this.mats.surface("red-carpet"), new THREE.CylinderGeometry(r * 0.62, r * 0.62, 0.014, 40).translate(cx, 0.007, cz));
    const spill = this.spills.get(room.id) as THREE.MeshBasicMaterial;
    this.extra(room.id, spillMesh(flat(cx, DIM.ground + 0.025, cz, r * 3.4, r * 3.4), spill));
    const group = new THREE.Group();
    group.name = `room:${room.id}`;
    group.add(floor);
    this.finishGroup(room.id, group);
    return {
      room,
      group,
      floor,
      center: new THREE.Vector3(cx, 0, cz),
      extent: new THREE.Vector2(r * 2, r * 2),
      wallTop: this.plan.wall_height_m * DIM.towerCut,
      lampPosition: new THREE.Vector3(cx, 1.5, cz),
      doors: this.doorCentres(room),
      focus: null,
      glow: this.glows.get(room.id) as THREE.MeshStandardMaterial,
      spill,
    };
  }
}

function sorted(p: number, q: number): [number, number] {
  return p < q ? [p, q] : [q, p];
}

/** Turn a geometry inside out: reverse the winding and the normals. */
function facingIn(g: THREE.BufferGeometry): THREE.BufferGeometry {
  const index = g.getIndex();
  if (index) {
    for (let i = 0; i < index.count; i += 3) {
      const b = index.getX(i + 1);
      index.setX(i + 1, index.getX(i + 2));
      index.setX(i + 2, b);
    }
  }
  const n = g.getAttribute("normal");
  for (let i = 0; i < n.count; i++) n.setXYZ(i, -n.getX(i), -n.getY(i), -n.getZ(i));
  return g;
}

/** The fan of light below a window, from the plinth edge outward. */
function windowSpill(axis: "h" | "v", line: number, mid: number, out: -1 | 1): THREE.BufferGeometry {
  const g = new THREE.PlaneGeometry(2.6, SPILL_DEPTH);
  g.rotateX(-Math.PI / 2);
  // After that turn the far end (v = 1) points to -z; swing it to face outward.
  const turn = axis === "h" ? (out < 0 ? 0 : Math.PI) : out > 0 ? -Math.PI / 2 : Math.PI / 2;
  g.rotateY(turn);
  const offset = line + out * (DIM.stone + DIM.plinthOverhang + SPILL_DEPTH / 2 - 0.1);
  return axis === "h" ? g.translate(mid, DIM.ground + 0.03, offset) : g.translate(offset, DIM.ground + 0.03, mid);
}

function spillMesh(geometry: THREE.BufferGeometry, material: THREE.Material): THREE.Mesh {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 1;
  return mesh;
}
