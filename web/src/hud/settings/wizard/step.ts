// What each wizard step is given and gives back.

import type { NativeHelpers } from "../../../net/native";
import type { SettingsApi } from "../../../net/settings-api";
import type { Settings } from "../../../net/settings-types";
import type { Store } from "../../../net/store";
import type { ProposeResult } from "../../../net/types";
import type { ModelSource } from "../../pickers/model-picker";
import type { Flow, Outcome } from "./flow";

export interface WizardEnv {
  api: SettingsApi;
  store: Store;
  native: NativeHelpers;
  models: ModelSource;
  propose(folder: string): Promise<ProposeResult>;
  settings: Settings;
  flow: Flow;
}

export interface StepView {
  heading: string;
  lead: string;
  body: HTMLElement;
  /** The Continue button's words, when not "Continue". */
  next?: string;
  /** Called on Continue: how the step ended, or null to stay (a save failed and says why). */
  finish(): Promise<Outcome | null>;
}
