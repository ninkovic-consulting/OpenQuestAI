// The first-start wizard: one step per screen with Back, Skip and Continue
// and a step count. It opens on first launch and from Settings. "Later"
// and Escape put it away; it never holds the keyboard, and once a key is
// stored, pressing `/` to type to the assistant puts it away too.

import { nativeHelpers } from "../../../net/native";
import type { SettingsApi } from "../../../net/settings-api";
import type { Store } from "../../../net/store";
import type { ProposeResult } from "../../../net/types";
import { el, setText } from "../../dom";
import type { ModelSource } from "../../pickers/model-picker";
import { button, statusLine } from "../fields";
import { back, forward, skip, startFlow, stepCount, stepOf, STEPS, type Flow, type StepId } from "./flow";
import type { StepView, WizardEnv } from "./step";
import { doneStep, nameStep, roomStep } from "./steps-house";
import { downloadsStep, keyStep, microphoneStep, welcomeStep } from "./steps-setup";

const VIEWS: Record<StepId, (env: WizardEnv) => StepView> = {
  welcome: welcomeStep,
  key: keyStep,
  downloads: downloadsStep,
  microphone: microphoneStep,
  name: nameStep,
  room: roomStep,
  done: doneStep,
};

export interface WizardDeps {
  api: SettingsApi;
  store: Store;
  models: ModelSource;
  propose(folder: string): Promise<ProposeResult>;
}

export interface Wizard {
  open(): void;
  /** Put the wizard away; false when it was not open. */
  close(): boolean;
}

export function mountWizard(parent: HTMLElement, deps: WizardDeps): Wizard {
  const backdrop = el("div", "wizard-backdrop");
  backdrop.hidden = true;
  const card = el("section", "wizard");
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-label", "Setup");
  const head = el("header", "wizard-head");
  const count = el("span", "caps step-count");
  const later = el("button", "settings-close caps", "Later");
  later.type = "button";
  later.title = "Put setup away; it can be run again from Settings, This Mac.";
  const progress = el("ol", "wizard-progress");
  progress.setAttribute("aria-hidden", "true");
  const marks = STEPS.map(() => {
    const li = el("li");
    progress.append(li);
    return li;
  });
  head.append(count, progress, later);
  const kicker = el("div", "caps kicker", "First start");
  const heading = el("h2");
  const lead = el("p", "lead");
  const body = el("div", "wizard-body");
  const scroller = el("div", "wizard-scroll");
  scroller.append(kicker, heading, lead, body);
  const foot = el("footer", "wizard-foot");
  const backBtn = button("Back");
  const skipBtn = button("Skip");
  const next = button("Continue", "primary");
  const spacer = el("span", "spacer");
  foot.append(backBtn, spacer, skipBtn, next);
  card.append(head, scroller, foot);
  backdrop.append(card);
  parent.append(backdrop);

  let flow: Flow = startFlow();
  let env: WizardEnv | null = null;
  let view: StepView | null = null;
  let keyStored = false;

  const show = (): void => {
    if (!env) return;
    env.flow = flow;
    const step = stepOf(flow);
    view = VIEWS[step](env);
    setText(count, stepCount(flow));
    marks.forEach((m, i) => m.classList.toggle("is-on", i <= flow.index));
    setText(heading, view.heading);
    setText(lead, view.lead);
    body.replaceChildren(view.body);
    backBtn.hidden = flow.index === 0;
    skipBtn.hidden = step === "done";
    skipBtn.textContent = step === "welcome" ? "Skip setup" : "Skip";
    next.textContent = view.next ?? "Continue";
    next.disabled = false;
    scroller.scrollTop = 0;
    heading.focus();
  };
  heading.tabIndex = -1;

  const close = (): boolean => {
    if (backdrop.hidden) return false;
    backdrop.hidden = true;
    return true;
  };

  next.addEventListener("click", () => {
    if (!view) return;
    const step = stepOf(flow);
    next.disabled = true;
    void view.finish().then((outcome) => {
      next.disabled = false;
      if (outcome === null) return;
      if (step === "key" && outcome.status === "done") keyStored = true;
      if (step === "done") {
        close();
        return;
      }
      flow = forward(flow, outcome);
      show();
    });
  });
  skipBtn.addEventListener("click", () => {
    flow = skip(flow);
    show();
  });
  backBtn.addEventListener("click", () => {
    flow = back(flow);
    show();
  });
  later.addEventListener("click", close);

  // Only what is typed inside stays inside; Escape puts the wizard away.
  card.addEventListener("keydown", (ev) => {
    const target = ev.target;
    if (ev.key === "Escape") {
      ev.stopPropagation();
      close();
    } else if (ev.code === "Space" && target instanceof HTMLButtonElement) {
      ev.stopPropagation(); // Space presses the button, not push to talk
    }
  });
  window.addEventListener("keydown", (ev) => {
    const typing = ev.target instanceof HTMLInputElement || ev.target instanceof HTMLSelectElement || ev.target instanceof HTMLTextAreaElement;
    if (ev.key === "/" && !typing && keyStored) close();
  });

  return {
    open(): void {
      flow = startFlow();
      backdrop.hidden = false;
      body.replaceChildren(statusLine("idle", "Loading…"));
      void deps.api.settings().then((r) => {
        if (!r.ok) {
          body.replaceChildren(statusLine("bad", `Setup could not load the settings: ${r.message}`));
          return;
        }
        keyStored = r.value.key.stored;
        env = { ...deps, native: nativeHelpers(), settings: r.value, flow };
        show();
      });
    },
    close,
  };
}
