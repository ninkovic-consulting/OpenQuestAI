// How a page reaches the daemon: the pretend one in mock mode (`?mock=1`),
// otherwise the socket with the token from the bridge or the URL fragment.
// The house (main.ts) and the widget (widget.ts) both start here.

import type { Daemon } from "./daemon";
import { MockDaemon } from "./mock";
import { SocketDaemon } from "./socket";
import type { Store } from "./store";
import { readToken } from "./token";

export async function connect(store: Store): Promise<Daemon | null> {
  if (new URLSearchParams(location.search).get("mock") === "1") return new MockDaemon(store);
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
