// The frame loop. It listens to every display tick but draws only when a
// frame is due at the current pace (pacing.ts) or something asked for one,
// and stops listening altogether while the page is hidden (minimised,
// occluded, another tab) or the scene is covered (Settings over it). Animation time advances by the time between drawn
// frames, capped, so nothing jumps after a pause or a quiet spell.

import { decidePace, due, nextDue, strongest, type Activity, type Pace } from "./pacing";
import type { Quality } from "./quality";

/** The longest step animation time takes in one frame, in seconds. */
const MAX_DT_S = 0.1;
/** The step of the first frame after a pause, in seconds. */
const FIRST_DT_S = 1 / 60;
/** Display ticks remembered to tell the display's refresh interval. */
const TICKS_KEPT = 90;

export interface LoopHost {
  /** Start or stop the display-tick callback (the renderer's animation loop). */
  setLoop(callback: ((now: number) => void) | null): void;
  /** Draw a frame `dt` seconds after the last; answers the activity the scene shows now. */
  draw(dt: number, now: number): Activity;
  /** One drawn frame took `frameMs` from its tick to the next, `cpuMs` of it in the page's code. */
  sample(frameMs: number, cpuMs: number, now: number): void;
  /** A display tick that drew nothing. */
  idle(now: number): void;
}

export class Pacer {
  private activity: Activity = "interaction";
  private interactUntil = 0;
  private wanted = true;
  private next = 0;
  private lastDraw = -1;
  /** The tick of the frame just drawn, waiting for the next tick to measure it. */
  private drawnAt = -1;
  private drawCpu = 0;
  private lastTick = -1;
  private ticks: number[] = [];
  private running = false;
  private stepBack = false;
  private covered = false;
  private quality: Quality;
  pace: Pace = { fps: 0, label: "starting" };

  constructor(
    private readonly host: LoopHost,
    quality: Quality,
  ) {
    this.quality = quality;
  }

  start(): void {
    document.addEventListener("visibilitychange", () => this.syncVisibility());
    this.syncVisibility();
  }

  /** Draw on the next tick; with `ms`, treat the scene as in the owner's hands for that long. */
  wake(ms = 0): void {
    this.wanted = true;
    if (ms > 0) this.interactUntil = Math.max(this.interactUntil, performance.now() + ms);
  }

  /** Something opaque covers the whole scene: draw nothing until it goes. */
  setCovered(on: boolean): void {
    this.covered = on;
    this.syncVisibility();
  }

  setStepBack(on: boolean): void {
    if (on === this.stepBack) return;
    this.stepBack = on;
    this.wanted = true;
  }

  get steppedBack(): boolean {
    return this.stepBack;
  }

  setQuality(quality: Quality): void {
    this.quality = quality;
    this.wanted = true;
  }

  /** The display's refresh interval as the recent ticks show it, in milliseconds. */
  tickMs(): number {
    if (this.ticks.length < 2) return 1000 / 60;
    let least = Infinity;
    for (let i = 1; i < this.ticks.length; i++) least = Math.min(least, (this.ticks[i] as number) - (this.ticks[i - 1] as number));
    return Math.max(1000 / 240, least);
  }

  private syncVisibility(): void {
    const visible = document.visibilityState === "visible" && !this.covered;
    if (visible === this.running) return;
    this.running = visible;
    if (visible) {
      this.lastDraw = -1;
      this.lastTick = -1;
      this.drawnAt = -1;
      this.ticks = [];
      this.wanted = true;
      this.host.setLoop((now) => this.tick(now));
    } else {
      this.host.setLoop(null);
      this.pace = decidePace({ visible: false, activity: this.activity, stepBack: this.stepBack, quality: this.quality });
    }
  }

  private tick(now: number): void {
    if (this.drawnAt >= 0) {
      this.host.sample(now - this.drawnAt, this.drawCpu, now);
      this.drawnAt = -1;
    }
    if (this.lastTick >= 0) {
      this.ticks.push(now);
      if (this.ticks.length > TICKS_KEPT) this.ticks.shift();
    }
    this.lastTick = now;
    const activity = now < this.interactUntil ? strongest(this.activity, "interaction") : this.activity;
    this.pace = decidePace({ visible: true, activity, stepBack: this.stepBack, quality: this.quality });
    if (!this.wanted && (this.pace.fps === 0 || !due(now, this.next))) {
      this.host.idle(now);
      return;
    }
    this.wanted = false;
    const dt = this.lastDraw < 0 ? FIRST_DT_S : Math.min(MAX_DT_S, (now - this.lastDraw) / 1000);
    const start = performance.now();
    this.activity = this.host.draw(dt, now);
    this.drawCpu = performance.now() - start;
    this.drawnAt = now;
    this.lastDraw = now;
    this.next = nextDue(this.next, now, this.pace.fps);
  }
}
