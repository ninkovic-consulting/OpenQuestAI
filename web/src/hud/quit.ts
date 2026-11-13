// Quit, in the panel: one press asks, the second quits. Only the Mac app can
// quit itself (through its bridge), so a plain browser shows no control.

import { nativeHelpers } from "../net/native";
import { el } from "./dom";

/** What quitting means, said before it happens. */
export function quitQuestion(name: string): string {
  return `Quit ${name}? It stops answering, and its automations and the phone wait until you open it again.`;
}

export interface QuitControl {
  /** The button for the panel's row of actions. */
  readonly button: HTMLElement;
  /** The question with Quit and Stay, shown under the row after a press. */
  readonly confirm: HTMLElement;
  /** Show the button when this window can quit; call it whenever the panel draws. */
  sync(name: string): void;
}

export function makeQuit(): QuitControl {
  const button = el("button", "quit-toggle caps", "Quit");
  button.type = "button";
  button.hidden = true;
  const confirm = el("div", "quit-confirm");
  confirm.hidden = true;
  const question = el("p", "quit-question");
  const yes = el("button", "quit-yes caps", "Quit");
  yes.type = "button";
  const no = el("button", "quit-no caps", "Stay");
  no.type = "button";
  const row = el("div", "quit-actions");
  row.append(yes, no);
  confirm.append(question, row);

  let name = "";
  const close = (): void => {
    confirm.hidden = true;
    button.classList.remove("is-on");
  };
  button.addEventListener("click", () => {
    if (!confirm.hidden) return close();
    question.textContent = quitQuestion(name);
    confirm.hidden = false;
    button.classList.add("is-on");
    no.focus();
  });
  no.addEventListener("click", close);
  yes.addEventListener("click", () => {
    const quit = nativeHelpers().quit;
    if (!quit) return close();
    yes.disabled = true;
    question.textContent = `Quitting ${name}…`;
    void quit().catch(() => {
      yes.disabled = false;
      question.textContent = "The app did not quit. Use Quit in its menu, or press Cmd+Q.";
    });
  });

  return {
    button,
    confirm,
    sync(assistant: string): void {
      name = assistant || "the app";
      const can = nativeHelpers().quit !== null;
      button.hidden = !can;
      if (!can) close();
    },
  };
}
