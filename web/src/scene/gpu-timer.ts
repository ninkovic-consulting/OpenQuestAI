// GPU time per drawn frame, where the browser offers the WebGL timer query
// (Chrome does; the Mac app's WebKit does not, and the readout then says so).

interface TimerExt {
  TIME_ELAPSED_EXT: number;
  GPU_DISJOINT_EXT: number;
}

/** Results kept for the average. */
const KEEP = 30;

export class GpuTimer {
  private readonly ext: TimerExt | null;
  private readonly pending: WebGLQuery[] = [];
  private active: WebGLQuery | null = null;
  private results: number[] = [];

  constructor(private readonly gl: WebGL2RenderingContext) {
    this.ext = gl.getExtension("EXT_disjoint_timer_query_webgl2") as TimerExt | null;
  }

  begin(): void {
    if (!this.ext || this.active || this.pending.length > 4) return;
    const q = this.gl.createQuery();
    this.gl.beginQuery(this.ext.TIME_ELAPSED_EXT, q);
    this.active = q;
  }

  end(): void {
    if (!this.ext || !this.active) return;
    this.gl.endQuery(this.ext.TIME_ELAPSED_EXT);
    this.pending.push(this.active);
    this.active = null;
  }

  /** The average GPU time of the recent frames, in milliseconds; null when unknown. */
  read(): number | null {
    if (!this.ext) return null;
    const gl = this.gl;
    const disjoint = gl.getParameter(this.ext.GPU_DISJOINT_EXT) === true;
    while (this.pending.length > 0) {
      const q = this.pending[0] as WebGLQuery;
      if (!gl.getQueryParameter(q, gl.QUERY_RESULT_AVAILABLE)) break;
      this.pending.shift();
      if (!disjoint) this.results.push((gl.getQueryParameter(q, gl.QUERY_RESULT) as number) / 1e6);
      gl.deleteQuery(q);
    }
    if (this.results.length > KEEP) this.results = this.results.slice(-KEEP);
    if (this.results.length === 0) return null;
    return this.results.reduce((a, b) => a + b, 0) / this.results.length;
  }
}
