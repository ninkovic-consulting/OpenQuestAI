// How a page reaches the daemon: the pretend one in mock mode (`?mock=1`,
// with a pretend Mac app bridge on `&bridge=1`), otherwise the socket with the token from the bridge or the URL fragment.
// The house (main.ts) and the widget (widget.ts) both start here.

import type { Daemon } from "./daemon";
import { MockDaemon } from "./mock";
import { installMockBridge } from "./mock-bridge";
import { SocketDaemon } from "./socket";
import type { Store } from "./store";
import { readToken } from "./token";

export async function connect(store: Store): Promise<Daemon | null> {
  const params = new URLSearchParams(location.search);
  if (params.get("mock") === "1") {
    if (params.get("bridge") === "1") installMockBridge();
    return new MockDaemon(store);
  }
  const token = await readToken();
  if (token === null) {
    store.dispatch({
      kind: "toast",
      level: "error",
      text: "No token: open this page with `vision ui`, or add ?mock=1 to try it without a daemon.",
    });
    store.dispatch({ kind: "connection", connection: "offline" });
    return null;
  }
  return new SocketDaemon(store, token);
}
