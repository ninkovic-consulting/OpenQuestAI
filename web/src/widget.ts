// The widget page (`widget.html`): the Mac app's small floating window onto
// the assistant. Same store, connection and modules as the house; no scene.

import "@fontsource/fraunces/latin-400.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/josefin-sans/latin-300.css";
import "@fontsource/josefin-sans/latin-400.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "./styles/tokens.css";
import "./styles/hud.css";
import "./styles/chat.css";
import "./styles/widget.css";

import { mountWidget } from "./hud/widget/view";
import { connect } from "./net/connect";
import { Store } from "./net/store";

async function main(): Promise<void> {
  const store = new Store();
  const daemon = await connect(store);
  if (!daemon) return;
  mountWidget(document.body, store, daemon, new URLSearchParams(location.search).get("mock") === "1");
  daemon.start();
}

void main();
