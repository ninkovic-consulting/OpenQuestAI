// Counts the frames the scene draws and how long each one takes, over the
// last couple of seconds, for the readout and the resolution scaler.
//
// A frame's time is measured from the display tick that drew it to the next
// tick the browser gives the page: when the GPU falls behind, that next tick
// comes late. It does not depend on how often the scene chooses to draw.

/** How far back the readout looks, in milliseconds. */
export const WINDOW_MS = 2000;

interface Sample {
  at: number;
  frameMs: number;
  cpuMs: number;
}

export interface MeterReading {
  /** Frames drawn per second over the window. */
  fps: number;
  /** Average and worst frame time, in milliseconds; 0 with no frames. */
  avgMs: number;
  worstMs: number;
  /** Average time spent in the page's own code per frame (updating and submitting), in milliseconds. */
  cpuMs: number;
}

export class FrameMeter {
  private samples: Sample[] = [];

  /** One frame drawn at `at` that took `frameMs`, `cpuMs` of it in the page's code. */
  add(at: number, frameMs: number, cpuMs: number): void {
    this.samples.push({ at, frameMs, cpuMs });
    this.trim(at);
  }

  read(now: number): MeterReading {
    this.trim(now);
    const n = this.samples.length;
    if (n === 0) return { fps: 0, avgMs: 0, worstMs: 0, cpuMs: 0 };
    let sum = 0;
    let worst = 0;
    let cpu = 0;
    for (const s of this.samples) {
      sum += s.frameMs;
      cpu += s.cpuMs;
      worst = Math.max(worst, s.frameMs);
    }
    return { fps: (n * 1000) / WINDOW_MS, avgMs: sum / n, worstMs: worst, cpuMs: cpu / n };
  }

  private trim(now: number): void {
    const from = now - WINDOW_MS;
    let i = 0;
    while (i < this.samples.length && (this.samples[i] as Sample).at < from) i++;
    if (i > 0) this.samples.splice(0, i);
  }
}
