// Narrowing proposal and made-tool JSON (events and `/api/proposals`,
// `/api/made-tools` answers) to its types, or null when the shape is wrong.
// Like job-guards.ts: check what the screen relies on.

import {
  CHANGE_FIELDS,
  MADE_CHANGES,
  MADE_STATUSES,
  MADE_TIERS,
  PROPOSAL_KINDS,
  PROPOSAL_STATUSES,
  TOOL_LANGUAGES,
  WHO,
  type Confinement,
  type Decision,
  type LastRun,
  type MadeRun,
  type MadeTool,
  type MadeToolChanged,
  type MadeToolDetail,
  type MadeToolList,
  type MadeVersion,
  type Proposal,
  type ProposalChanged,
  type ProposalList,
  type ProposedChange,
  type ProposedTool,
  type Reach,
} from "./proposal-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isIn = <T extends string>(values: readonly T[], v: unknown): v is T => typeof v === "string" && (values as readonly string[]).includes(v);
const strOrNull = (v: unknown): boolean => v === null || isStr(v);
const numOrNull = (v: unknown): boolean => v === null || isNum(v);
const optStr = (v: unknown): boolean => v === undefined || isStr(v);
const isStrList = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);

export function isReach(v: unknown): v is Reach {
  return isObj(v) && isBool(v["network"]) && Array.isArray(v["folders"]) && v["folders"].every((f) => isObj(f) && isStr(f["name"]) && isStr(f["path"]));
}

function isProposedTool(v: unknown): v is ProposedTool {
  return (
    isObj(v) &&
    isStr(v["name"]) &&
    isStr(v["tool_name"]) &&
    isStr(v["description"]) &&
    isObj(v["input_schema"]) &&
    isIn(TOOL_LANGUAGES, v["language"]) &&
    optStr(v["script"]) &&
    isStr(v["sha256"]) &&
    isReach(v["reach"]) &&
    isNum(v["version"]) &&
    numOrNull(v["replaces"])
  );
}

function isProposedChange(v: unknown): v is ProposedChange {
  return isObj(v) && isStr(v["agent"]) && isStr(v["agent_name"]) && isIn(CHANGE_FIELDS, v["field"]) && isStr(v["before"]) && isStr(v["after"]);
}

function isDecision(v: unknown): v is Decision {
  return isObj(v) && isIn(WHO, v["who"]) && isIn(MADE_TIERS, v["tier"]);
}

export function asProposal(v: unknown): Proposal | null {
  if (!isObj(v)) return null;
  const kind = v["kind"];
  const ok =
    isStr(v["id"]) &&
    v["id"] !== "" &&
    isIn(PROPOSAL_KINDS, kind) &&
    isIn(PROPOSAL_STATUSES, v["status"]) &&
    isStr(v["agent"]) &&
    isStr(v["agent_name"]) &&
    isStr(v["job"]) &&
    strOrNull(v["room"]) &&
    isStr(v["title"]) &&
    isStr(v["reason"]) &&
    isNum(v["created_at"]) &&
    numOrNull(v["decided_at"]) &&
    isStr(v["note"]) &&
    (kind === "tool" ? isProposedTool(v["tool"]) : v["tool"] === null) &&
    (kind === "change" ? isProposedChange(v["change"]) : v["change"] === null) &&
    (v["decision"] === null || isDecision(v["decision"])) &&
    numOrNull(v["restored_at"]) &&
    (v["clipped"] === undefined || isBool(v["clipped"]));
  return ok ? (v as unknown as Proposal) : null;
}

export function asProposalList(v: unknown): ProposalList | null {
  if (!isObj(v) || !Array.isArray(v["proposals"]) || !isNum(v["waiting"])) return null;
  const limits = v["limits"];
  if (!isObj(limits) || !["per_agent", "total", "script_max"].every((k) => isNum(limits[k]))) return null;
  return v["proposals"].every((p) => asProposal(p) !== null) ? (v as unknown as ProposalList) : null;
}

/** `{proposal}`, as reading, approving, declining and restoring one answer. */
export function asOneProposal(v: unknown): Proposal | null {
  return isObj(v) ? asProposal(v["proposal"]) : null;
}

function isVersion(v: unknown): v is MadeVersion {
  return isObj(v) && isNum(v["version"]) && isStr(v["sha256"]) && isNum(v["approved_at"]) && isStr(v["proposal"]) && optStr(v["script"]);
}

function isLastRun(v: unknown): v is LastRun {
  return isObj(v) && isNum(v["ts"]) && isStr(v["agent"]) && numOrNull(v["exit_code"]) && isBool(v["ok"]);
}

export function asMadeTool(v: unknown): MadeTool | null {
  const ok =
    isObj(v) &&
    isStr(v["name"]) &&
    v["name"] !== "" &&
    isStr(v["tool_name"]) &&
    isStr(v["description"]) &&
    isIn(TOOL_LANGUAGES, v["language"]) &&
    isStr(v["author"]) &&
    isStr(v["author_name"]) &&
    isStr(v["reason"]) &&
    isObj(v["input_schema"]) &&
    isReach(v["reach"]) &&
    isIn(WHO, v["who"]) &&
    isIn(MADE_TIERS, v["tier"]) &&
    isBool(v["enabled"]) &&
    isIn(MADE_STATUSES, v["status"]) &&
    isStr(v["disabled_reason"]) &&
    isNum(v["version"]) &&
    isStr(v["sha256"]) &&
    Array.isArray(v["versions"]) &&
    v["versions"].every(isVersion) &&
    isNum(v["created_at"]) &&
    isNum(v["runs"]) &&
    (v["last_run"] === null || isLastRun(v["last_run"])) &&
    optStr(v["script"]);
  return ok ? (v as unknown as MadeTool) : null;
}

function isConfinement(v: unknown): v is Confinement {
  return isObj(v) && isBool(v["available"]) && strOrNull(v["reason"]) && isStrList(v["enforced"]) && isStrList(v["not_enforced"]);
}

export function asMadeToolList(v: unknown): MadeToolList | null {
  if (!isObj(v) || !Array.isArray(v["tools"]) || !isConfinement(v["confinement"])) return null;
  return v["tools"].every((t) => asMadeTool(t) !== null) ? (v as unknown as MadeToolList) : null;
}

function isRun(v: unknown): v is MadeRun {
  return (
    isObj(v) &&
    isNum(v["ts"]) &&
    isStr(v["agent"]) &&
    isStr(v["agent_name"]) &&
    isStr(v["job"]) &&
    isNum(v["version"]) &&
    isStr(v["sha256"]) &&
    isStr(v["input"]) &&
    numOrNull(v["exit_code"]) &&
    isNum(v["seconds"]) &&
    isStr(v["output"]) &&
    isBool(v["truncated"]) &&
    isNum(v["swept"])
  );
}

/** `{tool, runs}`, as `GET /api/made-tools/{name}` answers. */
export function asMadeToolDetail(v: unknown): MadeToolDetail | null {
  return isObj(v) && asMadeTool(v["tool"]) !== null && Array.isArray(v["runs"]) && v["runs"].every(isRun) ? (v as unknown as MadeToolDetail) : null;
}

/** `{tool}`, as changing a made tool answers. */
export function asOneMadeTool(v: unknown): MadeTool | null {
  return isObj(v) ? asMadeTool(v["tool"]) : null;
}

/** `{removed: true}`. */
export function asRemoved(v: unknown): true | null {
  return isObj(v) && v["removed"] === true ? true : null;
}

/** `proposal.changed` event data. */
export function asProposalChanged(v: unknown): ProposalChanged | null {
  const ok = isObj(v) && isStr(v["id"]) && isIn(PROPOSAL_KINDS, v["kind"]) && isIn(PROPOSAL_STATUSES, v["status"]) && isStr(v["agent"]) && isNum(v["waiting"]) && v["waiting"] >= 0;
  return ok ? (v as unknown as ProposalChanged) : null;
}

/** `made_tool.changed` event data. */
export function asMadeToolChanged(v: unknown): MadeToolChanged | null {
  return isObj(v) && isStr(v["name"]) && isIn(MADE_CHANGES, v["change"]) && isBool(v["enabled"]) ? (v as unknown as MadeToolChanged) : null;
}
