// The scene's performance readout (`?stats=1`, or Settings › Display): a
// small block of figures in the scene's top right corner, refreshed twice a
// second while it shows.

import type { MeterReading } from "./meter";

/** What the readout shows; the stage gathers it. */
export interface ReadoutFigures {
  reading: MeterReading;
  /** The pacing state, in words. */
  pace: string;
  quality: string;
  pixelRatio: number;
  /** The drawing buffer, in device pixels. */
  width: number;
  height: number;
  calls: number;
  triangles: number;
  /** Average GPU time per frame, in milliseconds; null where the browser does not tell. */
  gpuMs: number | null;
  /** Shadow map updates per second. */
  shadows: number;
}

const REFRESH_MS = 500;

export class Readout {
  private readonly node: HTMLElement;
  private shown = false;
  private last = -Infinity;

  constructor(parent: HTMLElement) {
    this.node = document.createElement("pre");
    this.node.className = "scene-readout";
    this.node.setAttribute("aria-hidden", "true");
    this.node.hidden = true;
    parent.append(this.node);
  }

  show(on: boolean): void {
    this.shown = on;
    this.node.hidden = !on;
    this.last = -Infinity;
  }

  /** Redraw the figures if they are due; `figures` is only called then. */
  refresh(now: number, figures: () => ReadoutFigures): void {
    if (!this.shown || now - this.last < REFRESH_MS) return;
    this.last = now;
    this.node.textContent = format(figures());
  }
}

/** The readout's lines. */
function format(f: ReadoutFigures): string {
  const r = f.reading;
  return [
    `${r.fps.toFixed(1)} fps · ${f.pace}`,
    `frame ${r.avgMs.toFixed(1)} ms avg · ${r.worstMs.toFixed(1)} worst`,
    `gpu ${f.gpuMs === null ? "n/a" : `${f.gpuMs.toFixed(2)} ms`} · cpu ${r.cpuMs.toFixed(2)} ms`,
    `pixel ratio ${f.pixelRatio.toFixed(2)} · ${f.width}×${f.height}`,
    `${f.calls} draw calls · ${formatCount(f.triangles)} triangles`,
    `shadows ${f.shadows.toFixed(1)}/s · ${f.quality}`,
  ].join("\n");
}

function formatCount(n: number): string {
  return n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n);
}
