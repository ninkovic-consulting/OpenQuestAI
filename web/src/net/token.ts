// Where the page gets its token (spec 4.6). In the native window the token
// comes through the pywebview script bridge; in a browser it comes in the URL
// fragment, which never leaves the browser. The fragment is removed at once.

interface PywebviewBridge {
  api: { token(): Promise<string> };
}

declare global {
  interface Window {
    pywebview?: PywebviewBridge;
  }
}

const BRIDGE_WAIT_MS = 4000;

function fromFragment(): string | null {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("token");
  if (token === null) return null;
  history.replaceState(null, "", location.pathname + location.search);
  return token;
}

function bridge(): Promise<PywebviewBridge | null> {
  if (window.pywebview) return Promise.resolve(window.pywebview);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), BRIDGE_WAIT_MS);
    window.addEventListener(
      "pywebviewready",
      () => {
        clearTimeout(timer);
        resolve(window.pywebview ?? null);
      },
      { once: true },
    );
  });
}

export async function readToken(): Promise<string | null> {
  const fragment = fromFragment();
  if (fragment !== null) return fragment;
  const api = await bridge();
  return api ? api.api.token() : null;
}
