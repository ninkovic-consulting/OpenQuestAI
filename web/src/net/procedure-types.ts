// Procedures as `/api/procedures` carries them. Mirrors vision/procedures;
// the daemon is the source of truth.

/** The owner of a shared procedure in the routes, in place of an agent id. */
export const SHARED = "shared";

/** A procedure without its steps. Times are Unix seconds. */
export interface ProcedureSummary {
  /** Its slug: the file name without `.md`. */
  name: string;
  title: string;
  when: string;
  /** The agent that wrote it; for a shared one, who may change it. */
  author: string;
  shared: boolean;
  changed_at: number;
  /** How often an agent has read it. */
  opened: number;
  /** The length of its steps. */
  chars: number;
}

export interface Procedure extends ProcedureSummary {
  steps: string;
}

export interface AgentProcedures {
  id: string;
  name: string;
  procedures: ProcedureSummary[];
}

export interface ProcedureLimits {
  name: number;
  when: number;
  steps: number;
  per_agent: number;
  shared: number;
}

/** `GET /api/procedures`: every agent's own, and the shared ones, each list by title. */
export interface ProcedureListing {
  agents: AgentProcedures[];
  shared: ProcedureSummary[];
  limits: ProcedureLimits;
}

/** Body of `PUT /api/procedures/{owner}/{name}`: only what changes. */
export interface ProcedureEdit {
  title?: string;
  when?: string;
  steps?: string;
}

export type ProcedureChange = "saved" | "removed";
export const PROCEDURE_CHANGES: readonly ProcedureChange[] = ["saved", "removed"];

/** `procedure.changed`: `owner` is an agent id or `shared`. */
export interface ProcedureChanged {
  owner: string;
  name: string;
  change: ProcedureChange;
}
