// Proposals and made tools as `/api/proposals`, `/api/made-tools` and the
// `proposal.changed` and `made_tool.changed` events carry them. Mirrors
// vision/proposals/model.py and made.py; the daemon is the source of truth.

export type ProposalKind = "tool" | "change";
export const PROPOSAL_KINDS: readonly ProposalKind[] = ["tool", "change"];
export type ProposalStatus = "waiting" | "approved" | "declined";
export const PROPOSAL_STATUSES: readonly ProposalStatus[] = ["waiting", "approved", "declined"];
export type ToolLanguage = "python" | "sh";
export const TOOL_LANGUAGES: readonly ToolLanguage[] = ["python", "sh"];
/** Who may use an approved tool: the agent that wrote it, or every agent. */
export type Who = "author" | "everyone";
export const WHO: readonly Who[] = ["author", "everyone"];
/** How an approved tool runs: asking the owner each time, or freely. */
export type MadeTier = "ask" | "free";
export const MADE_TIERS: readonly MadeTier[] = ["ask", "free"];
/** What a change proposal may change: nothing else is ever proposed. */
export type ChangeField = "persona" | "model" | "effort";
export const CHANGE_FIELDS: readonly ChangeField[] = ["persona", "model", "effort"];
/** `changed`: the script on disk no longer matches its pinned hash; `pending`: a new version waits for the owner. */
export type MadeStatus = "enabled" | "disabled" | "changed" | "pending";
export const MADE_STATUSES: readonly MadeStatus[] = ["enabled", "disabled", "changed", "pending"];
export type MadeChange = "approved" | "enabled" | "disabled" | "updated" | "deleted" | "ran";
export const MADE_CHANGES: readonly MadeChange[] = ["approved", "enabled", "disabled", "updated", "deleted", "ran"];

/** A folder a tool may read: the room's short name for it and its absolute path. */
export interface ReachFolder {
  name: string;
  path: string;
}

export interface Reach {
  folders: ReachFolder[];
  network: boolean;
}

/** The tool a proposal brings. A listing leaves the script out. */
export interface ProposedTool {
  name: string;
  /** The name the model sees once approved: `made_<name>`. */
  tool_name: string;
  description: string;
  input_schema: Record<string, unknown>;
  language: ToolLanguage;
  script?: string;
  sha256: string;
  reach: Reach;
  version: number;
  /** The version in use that this one would replace, or null for a new tool. */
  replaces: number | null;
}

/** A persona, model or thinking level, before and after. A listing cuts a persona to 300 characters. */
export interface ProposedChange {
  agent: string;
  agent_name: string;
  field: ChangeField;
  before: string;
  after: string;
}

export interface Decision {
  who: Who;
  tier: MadeTier;
}

/** Times are Unix seconds. */
export interface Proposal {
  id: string;
  kind: ProposalKind;
  status: ProposalStatus;
  agent: string;
  agent_name: string;
  /** The job it was proposed in, or empty. */
  job: string;
  room: string | null;
  title: string;
  reason: string;
  created_at: number;
  decided_at: number | null;
  note: string;
  tool: ProposedTool | null;
  change: ProposedChange | null;
  decision: Decision | null;
  restored_at: number | null;
  /** In a listing: the persona's before or after was cut short. */
  clipped?: boolean;
}

export interface ProposalLimits {
  per_agent: number;
  total: number;
  script_max: number;
}

/** `GET /api/proposals`: waiting oldest first, then decided newest first. */
export interface ProposalList {
  proposals: Proposal[];
  waiting: number;
  limits: ProposalLimits;
}

export interface MadeVersion {
  version: number;
  sha256: string;
  approved_at: number;
  /** The proposal that brought it. */
  proposal: string;
  /** Only in a tool's detail. */
  script?: string;
}

export interface LastRun {
  ts: number;
  agent: string;
  /** Null when the run was stopped at its time limit. */
  exit_code: number | null;
  ok: boolean;
}

export interface MadeTool {
  name: string;
  tool_name: string;
  description: string;
  language: ToolLanguage;
  author: string;
  author_name: string;
  reason: string;
  input_schema: Record<string, unknown>;
  reach: Reach;
  who: Who;
  tier: MadeTier;
  enabled: boolean;
  status: MadeStatus;
  disabled_reason: string;
  /** The version in use. */
  version: number;
  sha256: string;
  versions: MadeVersion[];
  created_at: number;
  runs: number;
  last_run: LastRun | null;
  /** The script of the version in use; only in a tool's detail. */
  script?: string;
}

/** One run of a made tool; the newest 50 are kept. */
export interface MadeRun {
  ts: number;
  agent: string;
  agent_name: string;
  job: string;
  version: number;
  sha256: string;
  /** The input JSON as text, cut to 500 characters. */
  input: string;
  exit_code: number | null;
  seconds: number;
  /** Standard output and error together, cut to 1,000 characters. */
  output: string;
  truncated: boolean;
  /** Leftover processes of the run that were killed after it. */
  swept: number;
}

/** What macOS confines for a made tool's run, and what rests on the owner reading the code. */
export interface Confinement {
  available: boolean;
  reason: string | null;
  enforced: string[];
  not_enforced: string[];
}

export interface MadeToolList {
  tools: MadeTool[];
  confinement: Confinement;
}

export interface MadeToolDetail {
  tool: MadeTool;
  runs: MadeRun[];
}

/** Body of `POST /api/proposals/{id}/approve`: who and tier for a tool, nothing for a change. */
export interface ApproveBody {
  who?: Who;
  tier?: MadeTier;
}

/** Body of `PATCH /api/made-tools/{name}`. */
export interface MadePatch {
  tier?: MadeTier;
  who?: Who;
  enabled?: boolean;
}

/** `proposal.changed`: one arrived or was decided; `waiting` counts those still waiting. */
export interface ProposalChanged {
  id: string;
  kind: ProposalKind;
  status: ProposalStatus;
  agent: string;
  waiting: number;
}

/** `made_tool.changed`. */
export interface MadeToolChanged {
  name: string;
  change: MadeChange;
  enabled: boolean;
}
