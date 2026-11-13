// The strip at the top of the Mac app's full-screen window that a camera
// notch hides. The stylesheets keep every overlay below `--safe-top` (0 by
// default, so a browser and an external display look as they always have);
// the 3D scene still draws behind it. The shell sets the variable itself at
// load and whenever the window's screen or full screen changes; a page can
// also ask the bridge. `?inset=38` pretends one, for screenshots.

const VARIABLE = "--safe-top";

export function setSafeTop(points: number): void {
  document.documentElement.style.setProperty(VARIABLE, `${Math.max(0, Math.round(points))}px`);
}

/** `?inset=<points>`, or null when the page was not asked to pretend one. */
export function insetParam(search: string): number | null {
  const raw = new URLSearchParams(search).get("inset");
  if (raw === null) return null;
  const points = Number(raw);
  return Number.isFinite(points) && points >= 0 ? points : null;
}
