// Minimize, in the panel beside Quit: closes the house window and leaves the
// app in the menu bar only (no Dock icon, not in the app switcher), with
// everything still running: the assistant, automations, the phone, the
// shortcuts and the widget if it is on. Opening the house again (the menu bar
// item, the widget, opening the app) brings the window and the Dock icon
// back. Nothing stops, so it does not ask first. Only the Mac app can do this
// (through its bridge), so a plain browser shows no control.

import { nativeHelpers } from "../net/native";
import { el } from "./dom";

export interface MinimizeControl {
  readonly button: HTMLButtonElement;
  /** Show the button when this window can go to the menu bar; call it whenever the panel draws. */
  sync(): void;
}

export function makeMinimize(): MinimizeControl {
  const button = el("button", "minimize-toggle caps", "Minimize");
  button.type = "button";
  button.title = "Keep running in the menu bar";
  button.hidden = true;
  button.addEventListener("click", () => void nativeHelpers().goToBackground?.());
  return {
    button,
    sync(): void {
      button.hidden = nativeHelpers().goToBackground === null;
    },
  };
}
