import { describe, expect, it } from "vitest";
import { MockProcedures } from "./mock-procedures";
import { MOCK_CONFINEMENT, MockProposals } from "./mock-proposals";
import { asOneProcedure, asProcedureChanged, asProcedureListing } from "./procedure-guards";
import { asMadeToolChanged, asMadeToolDetail, asMadeToolList, asOneProposal, asProposal, asProposalChanged, asProposalList } from "./proposal-guards";
import { samplePlan } from "./sample-plan";
import { initialState, reduce, type ViewState } from "./store";
import { asOutbound, type OutboundData, type OutboundEvent, type OutboundType } from "./types";

type Emitted = { type: OutboundType; data: unknown };

function host(): { emitted: Emitted[]; emit<K extends OutboundType>(type: K, data: OutboundData[K]): void } {
  const emitted: Emitted[] = [];
  return { emitted, emit: (type, data) => emitted.push({ type, data }) };
}

const value = <T>(r: { ok: true; value: T } | { ok: false; message: string }): T => {
  if (!r.ok) throw new Error(r.message);
  return r.value;
};

const ev = <K extends OutboundType>(type: K, data: OutboundData[K]): { kind: "event"; event: OutboundEvent } => ({ kind: "event", event: { type, ts: 1, data } as OutboundEvent });

describe("proposal guards", () => {
  it("take the mock's listing, detail and made tools, and refuse a wrong shape", async () => {
    const api = new MockProposals(host());
    const list = value(await api.list());
    expect(asProposalList(list)).not.toBeNull();
    const first = list.proposals[0];
    if (!first) throw new Error("the sample has proposals");
    expect(first.tool?.script).toBeUndefined();
    expect(asOneProposal({ proposal: value(await api.get(first.id)) })).not.toBeNull();
    expect(asMadeToolList(value(await api.tools()))).not.toBeNull();
    expect(asMadeToolDetail(value(await api.tool("todo_scan")))).not.toBeNull();
    expect(asProposal({ ...first, kind: "change" })).toBeNull();
    expect(asProposal({ ...first, status: "maybe" })).toBeNull();
    expect(asProposalList({ proposals: [], waiting: 0 })).toBeNull();
    expect(asMadeToolList({ tools: [], confinement: { available: true } })).toBeNull();
  });

  it("check the three events before they reach the store", () => {
    expect(asProposalChanged({ id: "a", kind: "tool", status: "waiting", agent: "maker", waiting: 2 })).not.toBeNull();
    expect(asProposalChanged({ id: "a", kind: "tool", status: "waiting", agent: "maker", waiting: -1 })).toBeNull();
    expect(asMadeToolChanged({ name: "x", change: "ran", enabled: true })).not.toBeNull();
    expect(asMadeToolChanged({ name: "x", change: "exploded", enabled: true })).toBeNull();
    expect(asProcedureChanged({ owner: "shared", name: "x", change: "removed" })).not.toBeNull();
    expect(asProcedureChanged({ owner: "", name: "x", change: "saved" })).toBeNull();
    expect(asOutbound({ type: "proposal.changed", data: { id: "a" } })).toBeNull();
    expect(asOutbound({ type: "procedure.changed", data: { owner: "maker", name: "x", change: "saved" } })?.type).toBe("procedure.changed");
  });

  it("take the procedures listing and one procedure", async () => {
    const api = new MockProcedures({ ...host(), plan: samplePlan });
    expect(asProcedureListing(value(await api.list()))).not.toBeNull();
    expect(asOneProcedure({ procedure: value(await api.get("maker", "release-the-shop-app")) })).not.toBeNull();
    expect(asOneProcedure({ procedure: { name: "x" } })).toBeNull();
  });
});

describe("the store", () => {
  it("keeps the waiting count from proposal.changed and the list, and counts every change", () => {
    let s: ViewState = initialState();
    expect(s.proposalsWaiting).toBeNull();
    s = reduce(s, { kind: "proposals", waiting: 3 });
    expect(s.proposalsWaiting).toBe(3);
    s = reduce(s, ev("proposal.changed", { id: "a", kind: "tool", status: "approved", agent: "maker", waiting: 2 }));
    expect(s.proposalsWaiting).toBe(2);
    expect(s.proposalsRevision).toBe(1);
    s = reduce(s, ev("made_tool.changed", { name: "x", change: "ran", enabled: true }));
    s = reduce(s, ev("procedure.changed", { owner: "maker", name: "x", change: "saved" }));
    expect([s.madeToolsRevision, s.proceduresRevision]).toEqual([1, 1]);
  });

  it("does not change for the same count", () => {
    const s = reduce(initialState(), { kind: "proposals", waiting: 1 });
    expect(reduce(s, { kind: "proposals", waiting: 1 })).toBe(s);
  });
});

describe("mock proposals", () => {
  it("lists the waiting oldest first, then the decided newest first, with the persona cut short", async () => {
    const api = new MockProposals(host());
    const list = value(await api.list());
    const waiting = list.proposals.filter((p) => p.status === "waiting");
    expect(list.waiting).toBe(4);
    expect(waiting.map((p) => p.created_at)).toEqual([...waiting.map((p) => p.created_at)].sort((a, b) => a - b));
    const persona = list.proposals.find((p) => p.change?.field === "persona");
    expect(persona?.clipped).toBe(true);
    expect(persona?.change?.after.length).toBe(300);
  });

  it("approving a new tool makes it, in use with the owner's choices, and says so", async () => {
    const h = host();
    const api = new MockProposals(h);
    const done = value(await api.approve("a1b2c3d4", { who: "everyone", tier: "free" }));
    expect(done.status).toBe("approved");
    expect(done.decision).toEqual({ who: "everyone", tier: "free" });
    const tool = value(await api.tools()).tools.find((t) => t.name === "count_lines");
    expect(tool).toMatchObject({ status: "enabled", who: "everyone", tier: "free", version: 1 });
    expect(h.emitted.map((e) => e.type)).toEqual(["made_tool.changed", "proposal.changed"]);
    expect(h.emitted[1]?.data).toMatchObject({ id: "a1b2c3d4", status: "approved", waiting: 3 });
    expect((await api.approve("a1b2c3d4", {})).ok).toBe(false);
  });

  it("approving a new version moves the tool to it; declining one gives the tool back its status", async () => {
    const api = new MockProposals(host());
    value(await api.approve("b7e4f019", {}));
    const tool = value(await api.tool("fetch_feed")).tool;
    expect(tool.version).toBe(2);
    expect(tool.versions.map((v) => v.version)).toEqual([1, 2]);
    expect(tool.script).toContain("Only https feeds");

    const other = new MockProposals(host());
    const declined = value(await other.decline("b7e4f019", "  Keep the first one.  "));
    expect(declined.note).toBe("Keep the first one.");
    expect(value(await other.tools()).tools.find((t) => t.name === "fetch_feed")?.status).toBe("enabled");
  });

  it("puts back an approved change once", async () => {
    const api = new MockProposals(host());
    expect(value(await api.restore("e8a2c4d0")).restored_at).not.toBeNull();
    expect(await api.restore("e8a2c4d0")).toMatchObject({ ok: false, message: "This change was already put back." });
    expect(await api.restore("c3d9a7e2")).toMatchObject({ ok: false, message: "Only an approved change can be put back." });
  });

  it("refuses to turn on a script changed on disk, and to toggle a tool whose new version waits", async () => {
    const api = new MockProposals(host());
    expect((await api.patchTool("csv_check", { enabled: true })).ok).toBe(false);
    expect((await api.patchTool("fetch_feed", { enabled: true })).ok).toBe(false);
    expect(value(await api.useVersion("csv_check", 1)).status).toBe("enabled");
    expect(value(await api.patchTool("todo_scan", { enabled: false, tier: "free" }))).toMatchObject({ status: "disabled", tier: "free", disabled_reason: "You turned it off." });
  });

  it("deletes a tool and announces it", async () => {
    const h = host();
    const api = new MockProposals(h);
    value(await api.deleteTool("todo_scan"));
    expect(value(await api.tools()).tools.map((t) => t.name)).not.toContain("todo_scan");
    expect(h.emitted).toEqual([{ type: "made_tool.changed", data: { name: "todo_scan", change: "deleted", enabled: false } }]);
  });

  it("says confinement is available, with the sandbox's sentences", () => {
    expect(MOCK_CONFINEMENT.available).toBe(true);
    expect(MOCK_CONFINEMENT.enforced.length).toBeGreaterThan(0);
    expect(MOCK_CONFINEMENT.not_enforced.length).toBeGreaterThan(0);
  });
});

describe("mock procedures", () => {
  it("lists every agent of the plan and the shared ones, by title", async () => {
    const api = new MockProcedures({ ...host(), plan: samplePlan });
    const listing = value(await api.list());
    expect(listing.agents.map((a) => a.id)).toEqual(samplePlan().agents.map((a) => a.id));
    expect(listing.agents.find((a) => a.id === "maker")?.procedures.map((p) => p.title)).toEqual(["Fix a date format bug", "Release the shop app"]);
    expect(listing.shared.every((p) => p.shared)).toBe(true);
  });

  it("edits, refuses a title too long, and removes, announcing each change", async () => {
    const h = host();
    const api = new MockProcedures({ ...h, plan: samplePlan });
    const edited = value(await api.edit("maker", "release-the-shop-app", { title: "  Release   the shop  ", steps: "1. Ship." }));
    expect(edited).toMatchObject({ title: "Release the shop", steps: "1. Ship.", chars: 8 });
    expect(await api.edit("maker", "release-the-shop-app", { title: "x".repeat(81) })).toMatchObject({ ok: false, message: "A title must be at most 80 characters; it has 81." });
    value(await api.remove("shared", "hand-work-to-another-resident"));
    expect(h.emitted.map((e) => e.data)).toEqual([
      { owner: "maker", name: "release-the-shop-app", change: "saved" },
      { owner: "shared", name: "hand-work-to-another-resident", change: "removed" },
    ]);
    expect((await api.get("shared", "hand-work-to-another-resident")).ok).toBe(false);
  });
});
