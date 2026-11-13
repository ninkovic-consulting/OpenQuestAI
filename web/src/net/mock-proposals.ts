// Mock mode's proposals and made tools: the sample from mock-proposals-data.ts,
// decided and changed with the daemon's checks, each change announced with
// the same events the daemon sends.

import { mockHash, SCRIPTS, seedMadeTools, seedProposals, seedRuns } from "./mock-proposals-data";
import type { ProposalsApi } from "./proposals-api";
import type { ApproveBody, Confinement, MadePatch, MadeRun, MadeTool, MadeToolDetail, MadeToolList, Proposal, ProposalList } from "./proposal-types";
import { ok, refused, type Result } from "./settings-api";
import type { OutboundData, OutboundType } from "./types";

const LIMITS = { per_agent: 3, total: 12, script_max: 20_000 };
const NOTE_MAX = 500;
const SUMMARY_CLIP = 300;
const OFF_REASON = "You turned it off.";

/** As the daemon says it on a Mac that can confine runs: sandbox.py's sentences. */
export const MOCK_CONFINEMENT: Confinement = {
  available: true,
  reason: null,
  enforced: [
    "macOS itself confines every run with a sandbox; where it cannot, the tool does not run at all.",
    "The script can write only in its own empty scratch folder, which is deleted after the run.",
    "It can read only macOS system files, the Python runtime, its scratch folder and the folders you approved for it, and those only for reading.",
    "It cannot read the assistant's own folder, your SSH, cloud, GPG, Docker and Kubernetes keys, ~/.config, your Keychains and cookies, or protected files (.env files, private keys, credential and secrets files) inside the approved folders.",
    "Without network approval it cannot open any network connection, not even to this Mac. With it, it can only connect out; it can never listen for connections.",
    "It cannot reach the Keychain, the clipboard, other apps (no Apple Events, no opening apps) or local services through their sockets.",
    "It gets no secrets in its environment: a minimal PATH, its input on stdin and the list of its folders in FOLDERS.",
    "It is stopped at its time limit, and its CPU time, the size of each file it writes, its open files and the number of processes it can start are capped.",
    "Any process it leaves behind, even a detached one, is found and killed when the run ends.",
  ],
  not_enforced: [
    "What the script does with what it may read: it can print any of it back to the agent.",
    "With network approval, where it connects: any address on the internet or your network, so it could send what it read anywhere.",
    "Memory is not capped, nor the scratch folder as a whole (only each file in it).",
    "It can see whether a file exists and its size and dates almost anywhere on the disk; only reading contents is confined.",
    "It can read the system's own files like any program, for example the list of user accounts.",
    "Timing and other side channels, and flaws in macOS itself, are beyond this confinement.",
  ],
};

/** What the mock proposals need from the mock daemon. */
export interface MockProposalsHost {
  emit<K extends OutboundType>(type: K, data: OutboundData[K]): void;
}

const now = (): number => Date.now() / 1000;
const no = <T>(message: string): Promise<Result<T>> => Promise.resolve(refused(message));
const yes = <T>(value: T): Promise<Result<T>> => Promise.resolve(ok(structuredClone(value)));

/** A listing's row: no script, a persona cut short. */
function summary(p: Proposal): Proposal {
  const { tool, change } = p;
  const out: Proposal = { ...p, tool: tool ? { ...tool } : null, change: change ? { ...change, before: change.before.slice(0, SUMMARY_CLIP), after: change.after.slice(0, SUMMARY_CLIP) } : null };
  if (out.tool) delete out.tool.script;
  out.clipped = change !== null && Math.max(change.before.length, change.after.length) > SUMMARY_CLIP;
  return out;
}

export class MockProposals implements ProposalsApi {
  private items: Proposal[];
  private made: MadeTool[];
  private runs: Record<string, MadeRun[]>;
  /** Made tools whose held status comes back when their new version is declined. */
  private readonly held = new Map<string, { status: MadeTool["status"]; reason: string }>();

  constructor(private readonly host: MockProposalsHost) {
    const t = now();
    this.items = seedProposals(t);
    this.made = seedMadeTools(t);
    this.runs = seedRuns(t);
    this.held.set("fetch_feed", { status: "enabled", reason: "" });
  }

  waiting(): number {
    return this.items.filter((p) => p.status === "waiting").length;
  }

  list(): Promise<Result<ProposalList>> {
    const waiting = this.items.filter((p) => p.status === "waiting").sort((a, b) => a.created_at - b.created_at);
    const decided = this.items.filter((p) => p.status !== "waiting").sort((a, b) => (b.decided_at ?? 0) - (a.decided_at ?? 0));
    return yes({ proposals: [...waiting, ...decided].map(summary), waiting: waiting.length, limits: LIMITS });
  }

  get(id: string): Promise<Result<Proposal>> {
    const p = this.find(id);
    return p ? yes(p) : no(`There is no proposal ${id}.`);
  }

  approve(id: string, body: ApproveBody): Promise<Result<Proposal>> {
    const p = this.find(id);
    if (!p) return no(`There is no proposal ${id}.`);
    if (p.status !== "waiting") return no(`This proposal was already ${p.status}.`);
    if (p.tool) {
      const part = p.tool;
      const existing = this.made.find((t) => t.name === part.name);
      if (part.replaces === null && existing) return no(`There is already a tool called ${part.name}. Decline this one.`);
      if (part.replaces !== null && !existing) return no(`The tool ${part.name} was deleted after this was proposed, so its new version cannot be approved. Decline it.`);
      p.decision = { who: body.who ?? "author", tier: body.tier ?? "ask" };
      this.install(p, existing ?? null);
    }
    p.status = "approved";
    p.decided_at = now();
    this.decided(p);
    return yes(p);
  }

  decline(id: string, note: string): Promise<Result<Proposal>> {
    const p = this.find(id);
    if (!p) return no(`There is no proposal ${id}.`);
    if (p.status !== "waiting") return no(`This proposal was already ${p.status}.`);
    const tool = p.tool ? this.made.find((t) => t.name === p.tool?.name && t.status === "pending") : undefined;
    if (tool) {
      const back = this.held.get(tool.name) ?? { status: "disabled" as const, reason: OFF_REASON };
      this.held.delete(tool.name);
      tool.status = back.status;
      tool.disabled_reason = back.reason;
      tool.enabled = tool.status === "enabled";
      this.host.emit("made_tool.changed", { name: tool.name, change: tool.enabled ? "enabled" : "disabled", enabled: tool.enabled });
    }
    p.status = "declined";
    p.decided_at = now();
    p.note = note.trim().slice(0, NOTE_MAX);
    this.decided(p);
    return yes(p);
  }

  restore(id: string): Promise<Result<Proposal>> {
    const p = this.find(id);
    if (!p) return no(`There is no proposal ${id}.`);
    if (p.change === null || p.status !== "approved") return no("Only an approved change can be put back.");
    if (p.restored_at !== null) return no("This change was already put back.");
    p.restored_at = now();
    this.decided(p);
    return yes(p);
  }

  tools(): Promise<Result<MadeToolList>> {
    return yes({ tools: [...this.made].sort((a, b) => a.name.localeCompare(b.name)), confinement: MOCK_CONFINEMENT });
  }

  tool(name: string): Promise<Result<MadeToolDetail>> {
    const tool = this.made.find((t) => t.name === name);
    if (!tool) return no(`There is no made tool '${name}'.`);
    const script = (n: number): string => SCRIPTS[name]?.[n] ?? "";
    const detail: MadeTool = { ...tool, script: script(tool.version), versions: tool.versions.map((v) => ({ ...v, script: script(v.version) })) };
    return yes({ tool: detail, runs: this.runs[name] ?? [] });
  }

  patchTool(name: string, patch: MadePatch): Promise<Result<MadeTool>> {
    const tool = this.made.find((t) => t.name === name);
    if (!tool) return no(`There is no made tool '${name}'.`);
    const toggled = patch.enabled !== undefined && patch.enabled !== tool.enabled;
    if (toggled && tool.status === "pending") return no(`A new version of ${name} waits for your decision in Proposals; approve or decline it first.`);
    if (toggled && patch.enabled && tool.status === "changed")
      return no(`The script of ${name} changed on disk since you approved it, so it cannot be turned on. Go back to an approved version instead.`);
    if (toggled) {
      tool.status = patch.enabled ? "enabled" : "disabled";
      tool.disabled_reason = patch.enabled ? "" : OFF_REASON;
      tool.enabled = patch.enabled === true;
    }
    if (patch.tier) tool.tier = patch.tier;
    if (patch.who) tool.who = patch.who;
    this.host.emit("made_tool.changed", { name, change: toggled ? (tool.enabled ? "enabled" : "disabled") : "updated", enabled: tool.enabled });
    return yes(tool);
  }

  useVersion(name: string, version: number): Promise<Result<MadeTool>> {
    const tool = this.made.find((t) => t.name === name);
    if (!tool) return no(`There is no made tool '${name}'.`);
    if (tool.status === "pending") return no(`A new version of ${name} waits for your decision in Proposals; approve or decline it first.`);
    const v = tool.versions.find((x) => x.version === version);
    if (!v) return no(`${name} has no version ${version}.`);
    Object.assign(tool, { version, sha256: v.sha256, status: "enabled", disabled_reason: "", enabled: true });
    this.host.emit("made_tool.changed", { name, change: "updated", enabled: true });
    return yes(tool);
  }

  deleteTool(name: string): Promise<Result<true>> {
    if (!this.made.some((t) => t.name === name)) return no(`There is no made tool '${name}'.`);
    this.made = this.made.filter((t) => t.name !== name);
    delete this.runs[name];
    this.host.emit("made_tool.changed", { name, change: "deleted", enabled: false });
    return yes(true as const);
  }

  private find(id: string): Proposal | undefined {
    return this.items.find((p) => p.id === id);
  }

  /** An approved tool proposal: a new made tool, or a new version of one, in use at once. */
  private install(p: Proposal, existing: MadeTool | null): void {
    const part = p.tool;
    if (!part || !p.decision) return;
    const t = now();
    SCRIPTS[part.name] = { ...SCRIPTS[part.name], [part.version]: part.script ?? "" };
    const version = { version: part.version, sha256: part.script ? mockHash(part.script) : part.sha256, approved_at: t, proposal: p.id };
    const fields = { description: part.description, language: part.language, input_schema: part.input_schema, reach: part.reach, reason: p.reason, version: part.version, sha256: version.sha256 };
    const state = { who: p.decision.who, tier: p.decision.tier, status: "enabled" as const, enabled: true, disabled_reason: "" };
    if (existing) {
      Object.assign(existing, fields, state, { versions: [...existing.versions, version] });
      this.held.delete(existing.name);
    } else {
      this.made.push({ name: part.name, tool_name: part.tool_name, author: p.agent, author_name: p.agent_name, ...fields, ...state, versions: [version], created_at: t, runs: 0, last_run: null });
    }
    this.host.emit("made_tool.changed", { name: part.name, change: "approved", enabled: true });
  }

  private decided(p: Proposal): void {
    this.host.emit("proposal.changed", { id: p.id, kind: p.kind, status: p.status, agent: p.agent, waiting: this.waiting() });
  }
}
