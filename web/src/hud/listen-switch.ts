// The quick listening control, in the left panel under the state and in the
// widget: the current mode, a press switching between hold to talk and the
// listening mode last chosen in Settings, and a small mark while a
// microphone stream is open. Going to Always while shell commands are free
// asks first, with the same sentence Settings uses. A refusal (voice off,
// speech models missing) comes as a toast with the daemon's sentence.

import type { SettingsApi } from "../net/settings-api";
import type { Store } from "../net/store";
import { el, setText } from "./dom";
import { micTitle, needsConfirm, quickControl, ROOM_RUNS_COMMANDS } from "./listen";

export function mountListenSwitch(parent: HTMLElement, store: Store, api: SettingsApi): void {
  const root = el("div", "listen-switch");
  const button = el("button", "listen-toggle caps");
  button.type = "button";
  const dot = el("span", "dot");
  const label = el("span", "listen-mode");
  const mark = el("span", "mic-mark caps", "mic");
  button.append(dot, label);
  const confirm = el("div", "listen-confirm");
  confirm.hidden = true;
  root.append(button, mark, confirm);
  parent.append(root);
  let busy = false;

  const render = (): void => {
    const s = store.get();
    const q = quickControl(s.listen, s.plan?.assistant.name ?? "");
    root.hidden = !q.shown;
    setText(label, q.label);
    button.title = q.title;
    button.setAttribute("aria-label", `${q.label}. ${q.title}`);
    button.disabled = q.disabled || busy;
    root.classList.toggle("is-listening", q.listening);
    root.classList.toggle("is-off", q.disabled);
    mark.hidden = !q.mic;
    mark.title = micTitle(s.listen);
    mark.classList.toggle("is-opening", s.listen?.mic === "opening");
  };

  const choose = (): void => {
    const s = store.get();
    const next = quickControl(s.listen, s.plan?.assistant.name ?? "").next;
    if (needsConfirm(next, s.listen?.shell_free ?? false)) return ask();
    send(next);
  };
  const send = (mode: string): void => {
    busy = true;
    render();
    void api.patchSettings({ voice: { listen: mode } }).then((r) => {
      busy = false;
      if (!r.ok) store.dispatch({ kind: "toast", level: "warn", text: r.message });
      render();
    });
  };
  const ask = (): void => {
    const yes = el("button", "caps danger", "Listen always");
    yes.type = "button";
    const no = el("button", "caps", "Cancel");
    no.type = "button";
    const actions = el("div", "row-actions");
    actions.append(yes, no);
    confirm.replaceChildren(el("p", "confirm-question", ROOM_RUNS_COMMANDS), actions);
    confirm.hidden = false;
    yes.focus();
    const close = (): void => {
      confirm.hidden = true;
      confirm.replaceChildren();
    };
    yes.addEventListener("click", () => {
      close();
      send("always");
    });
    no.addEventListener("click", close);
  };

  button.addEventListener("click", choose);
  render();
  store.subscribe((s, prev) => {
    if (s.listen !== prev.listen || s.plan !== prev.plan) render();
  });
}
