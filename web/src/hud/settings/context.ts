// What every settings group is given: the daemon, the saved settings, the
// shared draft of edits, and ways to move about the screen.

import type { AutomationsApi } from "../../net/automations-api";
import type { NativeHelpers } from "../../net/native";
import type { PhoneApi } from "../../net/phone-api";
import type { SettingsApi } from "../../net/settings-api";
import type { Settings } from "../../net/settings-types";
import type { Store } from "../../net/store";
import type { ProposeResult } from "../../net/types";
import type { ModelSource } from "../pickers/model-picker";
import type { Draft } from "./draft";

export type GroupId = "assistant" | "models" | "agents" | "rooms" | "voice" | "asking" | "automations" | "phone" | "key" | "mac" | "reset";

export interface SettingsContext {
  api: SettingsApi;
  automations: AutomationsApi;
  phone: PhoneApi;
  store: Store;
  native: NativeHelpers;
  models: ModelSource;
  settings: Settings;
  /** The saved values as a draft, to compare edits against. */
  saved: Draft;
  /** The edits, shared by every group until saved or reverted. */
  draft: Draft;
  /** Set one field of the draft. */
  edit(field: string, value: string): void;
  /** The error the last save gave this field. */
  errorFor(field: string): string | undefined;
  /** Take new settings from the daemon and draw the group again. */
  adopt(settings: Settings): void;
  /**
   * Ask the daemon for the settings again. With `redraw` false the group on
   * screen stays as it is; with `discard` unsaved edits are dropped (after a reset).
   */
  reload(opts?: { redraw?: boolean; discard?: boolean }): Promise<void>;
  /** Restart the assistant; answers the line to show. */
  restart(): Promise<string>;
  openWizard(): void;
  goTo(group: GroupId, roomId?: string): void;
  /** The room the Rooms group opens at. */
  roomId: string | null;
  /** The tools proposed for a project folder. */
  propose(folder: string): Promise<ProposeResult>;
  /** A group with its own Save (Rooms) says whether it holds unsaved edits. */
  markDirty(dirty: boolean): void;
}

export interface Group {
  id: GroupId;
  title: string;
  blurb: string;
  /** Draft fields this group edits; empty for groups that act at once. */
  prefixes: readonly string[];
  render(ctx: SettingsContext): HTMLElement;
}

/** How to restart without the app's help. */
export const RESTART_HELP =
  "Quit the app from its menu bar item and open it again. If you started the assistant in Terminal, stop it with Ctrl-C and run `vision` again.";
