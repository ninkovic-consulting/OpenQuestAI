// The quick offline switch in the left panel, under the state: small and
// quiet. A refusal (the model is not on this Mac yet, say) comes as a toast
// with the daemon's sentence, which says where to fix it.

import type { SettingsApi } from "../net/settings-api";
import type { Store } from "../net/store";
import { el } from "./dom";
import { switchButton } from "./settings/offline-block";

export function mountOfflineSwitch(parent: HTMLElement, store: Store, api: SettingsApi): void {
  const root = el("div", "mode-switch");
  const label = el("span", "caps", "Offline");
  let toggle = switchButton("Offline mode", false, true);
  root.append(label, toggle);
  parent.append(root);
  let busy = false;

  const render = (): void => {
    const mode = store.get().mode;
    root.hidden = mode === null;
    const next = switchButton("Offline mode", mode?.offline === true, true);
    next.disabled = busy;
    next.title = mode?.offline ? "Offline mode is on: nothing is sent to Anthropic. Click to go back to Claude." : "Work offline on the local model, on this Mac";
    next.addEventListener("click", press);
    toggle.replaceWith(next);
    toggle = next;
    root.classList.toggle("is-on", mode?.offline === true);
  };
  const press = (): void => {
    busy = true;
    render();
    void api.patchSettings({ models: { offline: !store.get().mode?.offline } }).then((r) => {
      busy = false;
      if (!r.ok) store.dispatch({ kind: "toast", level: "warn", text: r.message });
      render();
    });
  };
  render();
  store.subscribe((s, prev) => {
    if (s.mode !== prev.mode) render();
  });
}
