// The Proposals view's words and order, apart from the DOM: proposals,
// approved tools and procedures.

import type { ProcedureListing, ProcedureSummary } from "../../net/procedure-types";
import { SHARED } from "../../net/procedure-types";
import type {
  ApproveBody,
  ChangeField,
  Confinement,
  LastRun,
  MadeStatus,
  MadeTier,
  MadeTool,
  Proposal,
  ProposalStatus,
  ProposedChange,
  ProposedTool,
  Who,
} from "../../net/proposal-types";
import { clock, duration } from "../jobs/model";

// ---------------------------------------------------------------- proposals

/** Waiting first, oldest first (the order they came in), then the decided, newest decision first. */
export function proposalRows(list: readonly Proposal[]): Proposal[] {
  const waiting = list.filter((p) => p.status === "waiting").sort((a, b) => a.created_at - b.created_at);
  const decided = list.filter((p) => p.status !== "waiting").sort((a, b) => (b.decided_at ?? b.created_at) - (a.decided_at ?? a.created_at));
  return [...waiting, ...decided];
}

export const waitingCount = (list: readonly Proposal[]): number => list.filter((p) => p.status === "waiting").length;

export const STATUS_WORD: Record<ProposalStatus, string> = { waiting: "waiting for you", approved: "approved", declined: "declined" };

export const FIELD_WORD: Record<ChangeField, string> = { persona: "persona", model: "model", effort: "thinking level" };

/** What the row says it is: "New tool", "New version", or the field a change is about. */
export function kindWord(p: Proposal): string {
  if (p.tool) return p.tool.replaces === null ? "new tool" : "new version";
  return p.change ? FIELD_WORD[p.change.field] : "change";
}

/** When it was proposed or decided, and how: "since 14:02", "12 Nov 14:02 · Only Tink · asks each time · put back 15:10". */
export function decidedWhen(p: Proposal, now: number): string {
  if (p.status === "waiting") return `since ${clock(p.created_at, now)}`;
  const parts = [clock(p.decided_at ?? p.created_at, now)];
  if (p.decision) parts.push(whoWord(p.decision.who, p.agent_name), TIER_WORD[p.decision.tier]);
  if (p.restored_at !== null) parts.push(`put back ${clock(p.restored_at, now)}`);
  return parts.join(" · ");
}

/** The same with its status first: "Waiting since 14:02", "Approved 12 Nov 14:02 · Only Tink · asks each time". */
export function decidedLine(p: Proposal, now: number): string {
  const word = { waiting: "Waiting", approved: "Approved", declined: "Declined" }[p.status];
  return `${word} ${decidedWhen(p, now)}`;
}

/** An approved change that was not yet put back can be. */
export const restorable = (p: Proposal): boolean => p.kind === "change" && p.status === "approved" && p.restored_at === null;

/** The owner's two choices when approving a tool. */
export interface ApproveChoice {
  who: Who;
  tier: MadeTier;
}

export const DEFAULT_CHOICE: ApproveChoice = { who: "author", tier: "ask" };

/** The body sent to approve: who and tier for a tool, nothing for a change. */
export function approveBody(p: Proposal, choice: ApproveChoice): ApproveBody {
  return p.kind === "tool" ? { who: choice.who, tier: choice.tier } : {};
}

/** A tool that runs freely with the network can send anything it reads anywhere, unasked. */
export function networkWarning(tool: Pick<ProposedTool, "reach">, tier: MadeTier): string | null {
  if (tier !== "free" || !tool.reach.network) return null;
  return "Free and with the network, it can send what it reads anywhere without asking you first.";
}

export function whoWord(who: Who, authorName: string): string {
  return who === "author" ? `Only ${authorName}` : "Every agent";
}

export const TIER_WORD: Record<MadeTier, string> = { ask: "asks each time", free: "free" };

export function whoChoices(authorName: string): { value: Who; label: string }[] {
  return [
    { value: "author", label: `Only ${authorName}` },
    { value: "everyone", label: "Every agent" },
  ];
}

export const TIER_CHOICES: readonly { value: MadeTier; label: string }[] = [
  { value: "ask", label: "Ask each time" },
  { value: "free", label: "Free" },
];

/** A hash short enough to read and compare by eye; the full one goes in the title. */
export const shortHash = (sha: string): string => sha.slice(0, 12);

/** For a new version: which one it replaces, and that the tool is off meanwhile. */
export function versionNote(tool: ProposedTool): string | null {
  if (tool.replaces === null) return null;
  return `New version ${tool.version} of ${tool.name}. It would replace version ${tool.replaces}, which is off until you decide.`;
}

export const lineCount = (text: string): number => (text === "" ? 0 : text.replace(/\n$/, "").split("\n").length);

/** One side of a change: its label, its value in words, and whether it is long text. */
export interface Side {
  label: string;
  text: string;
  long: boolean;
}

/** Before and after, labelled for where the proposal stands: "Now" and "Proposed" while it waits. */
export function changeSides(change: ProposedChange, status: ProposalStatus): [Side, Side] {
  const waiting = status === "waiting";
  const value = (v: string): string => (v.trim() === "" ? (change.field === "persona" ? "(no persona)" : "(the default)") : v);
  const long = change.field === "persona";
  return [
    { label: waiting ? "Now" : "Before", text: value(change.before), long },
    { label: waiting ? "Proposed" : "After", text: value(change.after), long },
  ];
}

export interface DiffLine {
  kind: "same" | "add" | "del";
  text: string;
}

/** Lines removed and added from one text to another, in order (longest common subsequence). */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.replace(/\n$/, "").split("\n");
  const b = after.replace(/\n$/, "").split("\n");
  const n = a.length;
  const m = b.length;
  const width = m + 1;
  const keep = new Uint32Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      keep[i * width + j] = a[i] === b[j] ? (keep[(i + 1) * width + j + 1] ?? 0) + 1 : Math.max(keep[(i + 1) * width + j] ?? 0, keep[i * width + j + 1] ?? 0);
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] ?? "" });
      i++;
      j++;
    } else if ((keep[(i + 1) * width + j] ?? 0) >= (keep[i * width + j + 1] ?? 0)) out.push({ kind: "del", text: a[i++] ?? "" });
    else out.push({ kind: "add", text: b[j++] ?? "" });
  }
  while (i < n) out.push({ kind: "del", text: a[i++] ?? "" });
  while (j < m) out.push({ kind: "add", text: b[j++] ?? "" });
  return out;
}

/** The confinement in a sentence when it is missing: approved tools then do not run at all. */
export function confinementProblem(c: Confinement): string | null {
  if (c.available) return null;
  return `This Mac cannot confine a tool's run${c.reason ? `: ${c.reason}` : "."} Approved tools will not run until it can; nothing ever runs unconfined.`;
}

// ---------------------------------------------------------------- made tools

export const MADE_STATUS_WORD: Record<MadeStatus, string> = {
  enabled: "on",
  disabled: "off",
  changed: "changed on disk",
  pending: "new version waiting",
};

/** Those that need the owner first (a new version waiting, a script changed on disk), then by name. */
export function madeRows(tools: readonly MadeTool[]): MadeTool[] {
  const rank: Record<MadeStatus, number> = { pending: 0, changed: 1, enabled: 2, disabled: 3 };
  return [...tools].sort((a, b) => rank[a.status] - rank[b.status] || a.name.localeCompare(b.name));
}

/** How a run ended: "exit 0", "exit 2", or stopped at its time limit. */
export function exitWords(code: number | null): string {
  return code === null ? "stopped at the time limit" : `exit ${code}`;
}

export function lastRunWords(run: LastRun | null, runs: number, now: number): string {
  if (run === null) return "Never run";
  return `${runs} ${runs === 1 ? "run" : "runs"} · last ${clock(run.ts, now)}, ${run.ok ? "ok" : exitWords(run.exit_code)}`;
}

/** How long a run took: "0.84 s" under a minute, else as the jobs say it. */
export function seconds(s: number): string {
  return s < 60 ? `${s.toFixed(2)} s` : duration(s);
}

/** Enable or Disable, or nothing while the owner must decide elsewhere first. */
export function toggleAction(tool: MadeTool): "enable" | "disable" | null {
  if (tool.status === "pending") return null;
  return tool.enabled ? "disable" : "enable";
}

// ---------------------------------------------------------------- procedures

export interface ProcedureGroup {
  /** An agent id, or `shared`. */
  owner: string;
  name: string;
  procedures: ProcedureSummary[];
}

/** Agents with procedures in the plan's order, then the shared ones; the names of agents with none apart. */
export function procedureGroups(listing: ProcedureListing): { groups: ProcedureGroup[]; none: string[] } {
  const groups: ProcedureGroup[] = listing.agents.filter((a) => a.procedures.length > 0).map((a) => ({ owner: a.id, name: a.name, procedures: a.procedures }));
  if (listing.shared.length > 0) groups.push({ owner: SHARED, name: "Shared", procedures: listing.shared });
  return { groups, none: listing.agents.filter((a) => a.procedures.length === 0).map((a) => a.name) };
}

export const procedureKey = (owner: string, name: string): string => `${owner}/${name}`;

/** "by Tink · changed Yesterday 14:02 · read 3 times". */
export function procedureMeta(p: ProcedureSummary, authorName: string, now: number): string {
  const read = p.opened === 0 ? "not read yet" : `read ${p.opened === 1 ? "once" : `${p.opened} times`}`;
  return `by ${authorName} · changed ${clock(p.changed_at, now)} · ${read}`;
}

/** Only what the owner changed, as the edit route takes it; null when nothing did. */
export function procedureEdit(before: { title: string; when: string; steps: string }, draft: { title: string; when: string; steps: string }): Partial<typeof before> | null {
  const out: Partial<typeof before> = {};
  if (draft.title.trim() !== before.title) out.title = draft.title.trim();
  if (draft.when.trim() !== before.when) out.when = draft.when.trim();
  if (draft.steps.trim() !== before.steps.trim()) out.steps = draft.steps.trim();
  return Object.keys(out).length > 0 ? out : null;
}
