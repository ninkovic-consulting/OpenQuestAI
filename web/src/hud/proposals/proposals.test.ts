import { describe, expect, it } from "vitest";
import type { ProcedureListing, ProcedureSummary } from "../../net/procedure-types";
import type { MadeTool, Proposal } from "../../net/proposal-types";
import {
  approveBody,
  changeSides,
  decidedLine,
  DEFAULT_CHOICE,
  exitWords,
  kindWord,
  lastRunWords,
  lineDiff,
  madeRows,
  networkWarning,
  procedureEdit,
  procedureGroups,
  procedureMeta,
  proposalRows,
  restorable,
  STATUS_WORD,
  toggleAction,
  versionNote,
  waitingCount,
  whoWord,
} from "./model";

const proposal = (id: string, more: Partial<Proposal> = {}): Proposal => ({
  id,
  kind: "change",
  status: "waiting",
  agent: "maker",
  agent_name: "Tink",
  job: "",
  room: null,
  title: id,
  reason: "",
  created_at: 0,
  decided_at: null,
  note: "",
  tool: null,
  change: { agent: "maker", agent_name: "Tink", field: "model", before: "a", after: "b" },
  decision: null,
  restored_at: null,
  ...more,
});

const tool = (more: Partial<NonNullable<Proposal["tool"]>> = {}): NonNullable<Proposal["tool"]> => ({
  name: "count_lines",
  tool_name: "made_count_lines",
  description: "",
  input_schema: { type: "object" },
  language: "python",
  sha256: "0".repeat(64),
  reach: { folders: [], network: false },
  version: 1,
  replaces: null,
  ...more,
});

const made = (name: string, status: MadeTool["status"]): MadeTool => ({
  name,
  tool_name: `made_${name}`,
  description: "",
  language: "sh",
  author: "scout",
  author_name: "Rook",
  reason: "",
  input_schema: {},
  reach: { folders: [], network: false },
  who: "author",
  tier: "ask",
  enabled: status === "enabled",
  status,
  disabled_reason: "",
  version: 1,
  sha256: "",
  versions: [],
  created_at: 0,
  runs: 0,
  last_run: null,
});

describe("the proposals list", () => {
  it("puts the waiting first, oldest first, then the decided, newest decision first", () => {
    const rows = proposalRows([
      proposal("w-new", { created_at: 30 }),
      proposal("d-old", { status: "approved", created_at: 1, decided_at: 10 }),
      proposal("w-old", { created_at: 20 }),
      proposal("d-new", { status: "declined", created_at: 2, decided_at: 50 }),
    ]);
    expect(rows.map((p) => p.id)).toEqual(["w-old", "w-new", "d-new", "d-old"]);
  });

  it("counts the waiting ones and words each status", () => {
    expect(waitingCount([proposal("a"), proposal("b", { status: "approved" }), proposal("c")])).toBe(2);
    expect(STATUS_WORD).toEqual({ waiting: "waiting for you", approved: "approved", declined: "declined" });
  });

  it("says what kind each is", () => {
    expect(kindWord(proposal("a", { kind: "tool", change: null, tool: tool() }))).toBe("new tool");
    expect(kindWord(proposal("a", { kind: "tool", change: null, tool: tool({ version: 2, replaces: 1 }) }))).toBe("new version");
    expect(kindWord(proposal("a"))).toBe("model");
  });

  it("says when and how one was decided", () => {
    const now = new Date(2026, 10, 13, 18, 0).getTime() / 1000;
    const at = new Date(2026, 10, 13, 14, 2).getTime() / 1000;
    expect(decidedLine(proposal("a", { created_at: at }), now)).toBe("Waiting since 14:02");
    const approved = proposal("t", { kind: "tool", status: "approved", decided_at: at, decision: { who: "author", tier: "ask" }, change: null, tool: tool() });
    expect(decidedLine(approved, now)).toBe("Approved 14:02 · Only Tink · asks each time");
    expect(decidedLine(proposal("c", { status: "approved", decided_at: at, restored_at: at + 60 }), now)).toBe("Approved 14:02 · put back 14:03");
  });

  it("offers Restore only for an approved change not yet put back", () => {
    expect(restorable(proposal("a", { status: "approved" }))).toBe(true);
    expect(restorable(proposal("a", { status: "approved", restored_at: 5 }))).toBe(false);
    expect(restorable(proposal("a"))).toBe(false);
    expect(restorable(proposal("a", { kind: "tool", status: "approved", change: null, tool: tool() }))).toBe(false);
  });
});

describe("approving", () => {
  it("sends who and tier for a tool, nothing for a change; the default is only the author, asking each time", () => {
    const t = proposal("t", { kind: "tool", change: null, tool: tool() });
    expect(approveBody(t, DEFAULT_CHOICE)).toEqual({ who: "author", tier: "ask" });
    expect(approveBody(t, { who: "everyone", tier: "free" })).toEqual({ who: "everyone", tier: "free" });
    expect(approveBody(proposal("c"), { who: "everyone", tier: "free" })).toEqual({});
  });

  it("warns only for a free tool with the network", () => {
    const net = { reach: { folders: [], network: true } };
    expect(networkWarning(net, "free")).toMatch(/send what it reads anywhere/);
    expect(networkWarning(net, "ask")).toBeNull();
    expect(networkWarning({ reach: { folders: [], network: false } }, "free")).toBeNull();
  });

  it("names who may use it and notes a new version", () => {
    expect(whoWord("author", "Rook")).toBe("Only Rook");
    expect(whoWord("everyone", "Rook")).toBe("Every agent");
    expect(versionNote(tool())).toBeNull();
    expect(versionNote(tool({ version: 3, replaces: 2 }))).toBe("New version 3 of count_lines. It would replace version 2, which is off until you decide.");
  });
});

describe("a change's before and after", () => {
  it("labels the sides by where it stands and words an empty value", () => {
    const change = { agent: "maker", agent_name: "Tink", field: "effort" as const, before: "", after: "high" };
    expect(changeSides(change, "waiting")).toEqual([
      { label: "Now", text: "(the default)", long: false },
      { label: "Proposed", text: "high", long: false },
    ]);
    const [before, after] = changeSides({ ...change, field: "persona", before: "Old.", after: "" }, "approved");
    expect(before).toEqual({ label: "Before", text: "Old.", long: true });
    expect(after?.text).toBe("(no persona)");
  });

  it("finds the lines removed and added", () => {
    expect(lineDiff("a\nb\nc\n", "a\nx\nc\nd")).toEqual([
      { kind: "same", text: "a" },
      { kind: "del", text: "b" },
      { kind: "add", text: "x" },
      { kind: "same", text: "c" },
      { kind: "add", text: "d" },
    ]);
  });
});

describe("approved tools", () => {
  it("lists those that need the owner first, then by name", () => {
    const rows = madeRows([made("b", "enabled"), made("z", "pending"), made("a", "disabled"), made("c", "changed"), made("a2", "enabled")]);
    expect(rows.map((t) => t.name)).toEqual(["z", "c", "a2", "b", "a"]);
  });

  it("offers Enable or Disable, none while a new version waits", () => {
    expect(toggleAction(made("a", "enabled"))).toBe("disable");
    expect(toggleAction(made("a", "changed"))).toBe("enable");
    expect(toggleAction(made("a", "pending"))).toBeNull();
  });

  it("words runs and how they ended", () => {
    const now = new Date(2026, 10, 13, 18, 0).getTime() / 1000;
    expect(lastRunWords(null, 0, now)).toBe("Never run");
    expect(lastRunWords({ ts: now - 60, agent: "scout", exit_code: 2, ok: false }, 4, now)).toBe("4 runs · last 17:59, exit 2");
    expect(exitWords(null)).toBe("stopped at the time limit");
  });
});

describe("procedures", () => {
  const summary = (name: string, more: Partial<ProcedureSummary> = {}): ProcedureSummary => ({
    name,
    title: name,
    when: "",
    author: "maker",
    shared: false,
    changed_at: 0,
    opened: 0,
    chars: 0,
    ...more,
  });

  it("groups by agent in the plan's order, then the shared ones, with the agents that have none apart", () => {
    const listing: ProcedureListing = {
      agents: [
        { id: "host", name: "Vision", procedures: [] },
        { id: "steward", name: "Brass", procedures: [summary("b")] },
        { id: "maker", name: "Tink", procedures: [summary("t1"), summary("t2")] },
      ],
      shared: [summary("s", { shared: true })],
      limits: { name: 80, when: 300, steps: 6000, per_agent: 40, shared: 60 },
    };
    const { groups, none } = procedureGroups(listing);
    expect(groups.map((g) => `${g.owner}:${g.procedures.length}`)).toEqual(["steward:1", "maker:2", "shared:1"]);
    expect(groups[2]?.name).toBe("Shared");
    expect(none).toEqual(["Vision"]);
  });

  it("words who wrote it and how often it was read", () => {
    const now = new Date(2026, 10, 13, 18, 0).getTime() / 1000;
    const at = new Date(2026, 10, 13, 9, 5).getTime() / 1000;
    expect(procedureMeta(summary("a", { changed_at: at, opened: 3 }), "Tink", now)).toBe("by Tink · changed 09:05 · read 3 times");
    expect(procedureMeta(summary("a", { changed_at: at, opened: 1 }), "Tink", now)).toMatch(/read once$/);
  });

  it("sends only what the owner changed, nothing when nothing did", () => {
    const before = { title: "T", when: "W", steps: "1. Go." };
    expect(procedureEdit(before, { title: " T ", when: "W", steps: "1. Go.\n" })).toBeNull();
    expect(procedureEdit(before, { title: "New", when: "W", steps: "2. Stop." })).toEqual({ title: "New", steps: "2. Stop." });
  });
});
