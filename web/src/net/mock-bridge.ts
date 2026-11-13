// `?mock=1&bridge=1`: a pretend Mac app bridge, so the controls only the app
// offers (Minimize, Quit) can be looked at in a browser. Its
// methods do nothing; it never pretends the token, which mock mode needs not.

export function installMockBridge(): void {
  if (window.pywebview) return;
  const done = (): Promise<boolean> => Promise.resolve(true);
  const api = Object.freeze({ goToBackground: done, quit: done, safeAreaTop: () => Promise.resolve(0) });
  Object.defineProperty(window, "pywebview", { value: Object.freeze({ api }) });
}
