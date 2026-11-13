import type { AutomationsApi } from "./automations-api";
import type { JobsApi } from "./jobs-api";
import type { LibraryApi } from "./library-api";
import type { PhoneApi } from "./phone-api";
import type { Result, SettingsApi } from "./settings-api";
import type { InboundEvent, NewRoom, PostResult, ProposeResult } from "./types";

/** What the HUD and scene need from the daemon. The real socket and the mock both implement it. */
export interface Daemon {
  start(): void;
  send(event: InboundEvent): void;
  postRoom(room: NewRoom): Promise<PostResult>;
  /** The tools proposed for a project folder on this Mac. */
  proposeTools(folder: string): Promise<ProposeResult>;
  /** Earlier turns from `/api/history`, oldest first; the chat thread narrows the answer. */
  history(): Promise<Result<unknown>>;
  /** The settings routes: settings, models, voice, downloads, folders, doctor, resets, rooms. */
  readonly settings: SettingsApi;
  /** The automations routes. */
  readonly automations: AutomationsApi;
  /** The phone channel routes. */
  readonly phone: PhoneApi;
  /** The job board routes. */
  readonly jobs: JobsApi;
  /** The library's documents. */
  readonly library: LibraryApi;
}
