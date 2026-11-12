import type { InboundEvent, NewRoom, PostResult, ProposeResult } from "./types";

/** What the HUD and scene need from the daemon. The real socket and the mock both implement it. */
export interface Daemon {
  start(): void;
  send(event: InboundEvent): void;
  postRoom(room: NewRoom): Promise<PostResult>;
  /** The tools proposed for a project folder on this Mac. */
  proposeTools(project: string): Promise<ProposeResult>;
}
