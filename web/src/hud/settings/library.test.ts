import { describe, expect, it } from "vitest";
import { documentPath } from "../../net/library-api";
import { asAdded, asListing, asOpen, asRemoved } from "../../net/library-guards";
import type { LibraryDocument } from "../../net/library-types";
import { MockLibrary, MOCK_LIMITS } from "../../net/mock-library";
import { MockSettings } from "../../net/mock-settings";
import { OWNER_LIMITS, ownerProblem } from "../../net/owner";
import { samplePlan } from "../../net/sample-plan";
import { buildPatch, changedFields, draftFrom, saveSummary } from "./draft";
import { kindWords, metaWords } from "./library-parts";
import { aboutOutcome, forward, startFlow, STEPS, stepOf, summary } from "./wizard/flow";

function mockHouse() {
  const plan = samplePlan();
  return { plan: () => plan, changed: () => {}, reset: () => {}, tools: () => [], forgetAutomations: () => {}, forgetPhone: () => {} };
}

async function value<T>(p: Promise<{ ok: true; value: T } | { ok: false; message: string }>): Promise<T> {
  const r = await p;
  if (!r.ok) throw new Error(r.message);
  return r.value;
}

async function refusal(p: Promise<{ ok: true } | { ok: false; message: string }>): Promise<string> {
  const r = await p;
  if (r.ok) throw new Error("expected a refusal");
  return r.message;
}

const file = (name: string, text: string): File => new File([text], name);

describe("the owner's profile", () => {
  it("checks values the way the daemon does", () => {
    expect(ownerProblem("name", "Sam")).toBeNull();
    expect(ownerProblem("name", "De\nni")).toBe("What to call you must be one line of plain text.");
    expect(ownerProblem("business", "Line one\nline two")).toBeNull();
    expect(ownerProblem("business", "x".repeat(OWNER_LIMITS.business + 1))).toBe("The business can be at most 600 characters.");
    expect(ownerProblem("notes", "ok\n## Call me")).toContain("start with ##");
    expect(ownerProblem("notes", "bell\u0007")).toBe("Use plain text, without control characters.");
    expect(ownerProblem("age", "40")).toContain("no part called 'age'");
    expect(ownerProblem("name", 4)).toBe("Send text; an empty text clears the part.");
  });

  it("is part of the Assistant group's draft and saves on its own", async () => {
    const api = new MockSettings(mockHouse());
    const saved = draftFrom(await value(api.settings()));
    expect(saved["owner.name"]).toBe("");
    const draft = { ...saved, "owner.name": " Sam ", "owner.business": "A bakery in Graz." };
    expect(changedFields(saved, draft, ["assistant.", "owner."])).toEqual(["owner.name", "owner.business"]);
    const { patch } = buildPatch(saved, draft, ["assistant.", "owner."]);
    expect(patch).toEqual({ owner: { name: "Sam", business: "A bakery in Graz." } });
    const answer = await value(api.patchSettings(patch));
    expect(answer.settings.owner).toEqual({ name: "Sam", business: "A bakery in Graz.", notes: "" });
    expect(saveSummary(answer)).toBe("Saved. Applied now: what to call you, your business.");
    const bad = await api.patchSettings({ owner: { name: "x".repeat(61) } });
    expect(bad.ok ? [] : bad.errors).toEqual([{ field: "owner.name", message: "What to call you can be at most 60 characters." }]);
  });

  it("survives a settings reset and goes with starting over", async () => {
    const api = new MockSettings(mockHouse());
    await value(api.patchSettings({ owner: { name: "Sam" } }));
    await value(api.reset("settings", false));
    expect((await value(api.settings())).owner.name).toBe("Sam");
    await value(api.reset("everything", false));
    expect((await value(api.settings())).owner.name).toBe("");
  });
});

describe("the wizard's About you step", () => {
  it("comes right after the name", () => {
    expect(STEPS.indexOf("about")).toBe(STEPS.indexOf("name") + 1);
    let flow = startFlow();
    while (stepOf(flow) !== "about") flow = forward(flow);
    flow = forward(flow, aboutOutcome({ name: "Sam", business: "A bakery in Graz.\nSince 2019.", notes: "" }, true));
    expect(summary(flow).find((s) => s.id === "about")?.outcome).toEqual({ status: "done", text: "Calls you Sam; the business: A bakery in Graz." });
  });

  it("says what was kept, told or skipped", () => {
    expect(aboutOutcome({ name: "Sam", business: "", notes: "Speak German." }, false)).toEqual({ status: "done", text: "Kept: calls you Sam; and more to keep in mind." });
    expect(aboutOutcome({ name: "", business: "", notes: "" }, false).status).toBe("skipped");
    expect(aboutOutcome({ name: "", business: "b".repeat(80), notes: "" }, true).text).toMatch(/^the business: b{59}…\.$/);
  });
});

describe("the mock library", () => {
  it("starts with a few documents, newest first, in the daemon's shape", async () => {
    const listing = await value(new MockLibrary().list());
    expect(asListing(JSON.parse(JSON.stringify(listing)))).not.toBeNull();
    expect(listing.documents.map((d) => d.title)).toEqual(["Supplier terms", "Price list 2027", "About the bakery"]);
    expect(listing.documents[0]?.parts).toBeGreaterThan(1);
    expect(listing.limits.endings).toEqual(MOCK_LIMITS.endings);
  });

  it("adds files and pasted text, and refuses what the daemon refuses", async () => {
    const lib = new MockLibrary();
    const md = await value(lib.addFile(file("Opening hours.md", "# Hours\n\nTuesday to Sunday, 7 to 18.")));
    expect(md).toMatchObject({ name: "opening-hours", title: "Opening hours", kind: "markdown", original: "originals/opening-hours.md", editable: false });
    expect(md.gist).toBe("Tuesday to Sunday, 7 to 18.");
    expect(await refusal(lib.addFile(file("photo.jpg", "x")))).toContain("PDF (.pdf) and Word (.docx)");
    expect(await refusal(lib.addFile(file("scan of invoice.pdf", "%PDF")))).toContain("looks like scanned pages");
    expect(await refusal(lib.addFile(file("empty.txt", "")))).toBe("The file is empty.");
    const note = await value(lib.addText("Opening hours", "Closed on Mondays."));
    expect(note).toMatchObject({ name: "opening-hours-2", kind: "note", editable: true, original: null });
    expect(await refusal(lib.addText("  ", "text"))).toContain("title must be 1 to 120");
    expect(await refusal(lib.addText("Empty", "   "))).toBe("The document has no text.");
  });

  it("opens, renames and removes", async () => {
    const lib = new MockLibrary();
    const opened = await value(lib.open("price-list-2027"));
    expect(asOpen(JSON.parse(JSON.stringify(opened)))?.text).toContain("Croissant: 2.20 EUR");
    const renamed = await value(lib.rename("price-list-2027", "Prices 2027"));
    expect(asAdded({ document: renamed })?.title).toBe("Prices 2027");
    expect(await refusal(lib.rename("price-list-2027", "\u0001"))).toContain("plain text");
    const removed = await value(lib.remove("price-list-2027"));
    expect(asRemoved({ removed })?.name).toBe("price-list-2027");
    expect((await value(lib.list())).documents.map((d) => d.name)).not.toContain("price-list-2027");
    expect(await refusal(lib.open("price-list-2027"))).toContain("no document called");
  });
});

describe("library words and shapes", () => {
  const doc: LibraryDocument = { name: "q3", title: "Q3", kind: "pdf", chars: 20_000, bytes: 182_400, parts: 3, added_at: 1_794_000_000, gist: "", original: "originals/q3.pdf", editable: false };

  it("says kind, size, parts and when", () => {
    expect(kindWords("docx")).toBe("Word");
    expect(metaWords(doc)).toMatch(/^PDF · 182 KB · 3 parts · added \d+ \w{3} 2026, \d{2}:\d{2}$/);
    expect(metaWords({ ...doc, parts: 1, kind: "note" })).not.toContain("parts");
  });

  it("refuses answers in the wrong shape", () => {
    expect(asListing({ documents: [{ ...doc, kind: "image" }], folder: "/x", limits: MOCK_LIMITS })).toBeNull();
    expect(asListing({ documents: [doc], folder: "/x", limits: { ...MOCK_LIMITS, endings: [1] } })).toBeNull();
    expect(asOpen({ document: doc })).toBeNull();
  });

  it("keeps a document's name in one piece in its route", () => {
    expect(documentPath("projects/shop notes")).toBe("/api/library/documents/projects/shop%20notes");
  });
});
