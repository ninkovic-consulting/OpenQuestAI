// Mock mode's library: a few documents to start with, checked the way the
// daemon checks them. Text and Markdown files are read for real; a PDF or a
// Word file stands in with a line of made-up text, and one whose name says
// "scan" is refused as a scanned PDF would be.

import type { LibraryApi } from "./library-api";
import type { DocKind, LibraryDocument, LibraryListing, OpenDocument } from "./library-types";
import { ok, refused, type Result } from "./settings-api";

const MB = 1024 * 1024;
export const MOCK_LIMITS = { max_file_bytes: 20 * MB, max_text_chars: 400_000, max_documents: 500, title_max: 120, endings: [".docx", ".markdown", ".md", ".pdf", ".text", ".txt"] };
export const MOCK_FOLDER = "/Users/you/Library/Application Support/Vision/house/library";
const PART_CHARS = 8000;
const KINDS: Record<string, DocKind> = { ".md": "markdown", ".markdown": "markdown", ".txt": "text", ".text": "text", ".pdf": "pdf", ".docx": "docx" };
const ENDINGS = "The library takes text (.txt), Markdown (.md), PDF (.pdf) and Word (.docx) files.";

interface Stored {
  doc: LibraryDocument;
  text: string;
}

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const DAY = 86_400;

function slug(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60)
      .replace(/-+$/, "") || "document"
  );
}

function gist(text: string): string {
  const para = text.split(/\n\s*\n/).map((p) => p.replace(/^#+\s.*$/gm, "").trim()).find((p) => p.length > 0) ?? "";
  const line = para.replace(/\s+/g, " ");
  return line.length > 140 ? `${line.slice(0, 139).trimEnd()}…` : line;
}

function cleanTitle(title: string): string | null {
  const t = title.replace(/\s+/g, " ").trim();
  return t.length > 0 && t.length <= MOCK_LIMITS.title_max && !/[\u0000-\u001f\u007f]/.test(t) ? t : null;
}

const TITLE_RULE = `A document's title must be 1 to ${MOCK_LIMITS.title_max} characters of plain text.`;

export class MockLibrary implements LibraryApi {
  private docs: Stored[] = [];

  constructor(now = Date.now() / 1000) {
    this.put("About the bakery", "note", null, "# About the bakery\n\nWe bake sourdough, croissants and seasonal cakes in a small shop in Graz, open Tuesday to Sunday.\n\nTwo people run it: Sam bakes, Mara runs the counter and the books.", now - 9 * DAY);
    this.put("Price list 2027", "pdf", 182_400, "Price list 2027\n\nSourdough loaf, 1 kg: 6.50 EUR\nCroissant: 2.20 EUR\nSeasonal cake, whole: 34 EUR\n\nPrices include VAT. Orders over 100 EUR are delivered free within Graz.", now - 4 * DAY);
    this.put("Supplier terms", "docx", 48_900, `Supplier terms, Mühle Steiner\n\nFlour is delivered every Monday before 7:00. Payment within 30 days of the invoice; 2 percent off within 10 days.\n\n${"Further clauses on quality, returns and notice periods. ".repeat(240)}`, now - DAY);
  }

  private put(title: string, kind: DocKind, bytes: number | null, text: string, added: number, fileName?: string): LibraryDocument {
    const taken = new Set(this.docs.map((d) => d.doc.name));
    const base = slug(title);
    let name = base;
    for (let n = 2; taken.has(name); n++) name = `${base}-${n}`;
    const ending = fileName ? fileName.slice(fileName.lastIndexOf(".")).toLowerCase() : "";
    const doc: LibraryDocument = {
      name,
      title,
      kind,
      chars: text.length,
      bytes: bytes ?? new TextEncoder().encode(text).length,
      parts: Math.max(1, Math.ceil(text.length / PART_CHARS)),
      added_at: added,
      gist: gist(text),
      original: kind === "note" ? null : `originals/${name}${ending || (kind === "pdf" ? ".pdf" : kind === "docx" ? ".docx" : ".txt")}`,
      editable: kind === "note",
    };
    this.docs.push({ doc, text });
    return { ...doc };
  }

  private find(name: string): Stored | undefined {
    return this.docs.find((d) => d.doc.name === name);
  }

  list(): Promise<Result<LibraryListing>> {
    const documents = [...this.docs].sort((a, b) => b.doc.added_at - a.doc.added_at).map((d) => ({ ...d.doc }));
    return Promise.resolve(ok({ documents, folder: MOCK_FOLDER, limits: { ...MOCK_LIMITS, endings: [...MOCK_LIMITS.endings] } }));
  }

  async addFile(file: File): Promise<Result<LibraryDocument>> {
    const dot = file.name.lastIndexOf(".");
    const kind = dot >= 0 ? KINDS[file.name.slice(dot).toLowerCase()] : undefined;
    if (!kind) return refused(ENDINGS);
    if (file.size > MOCK_LIMITS.max_file_bytes) return refused(`The file is ${(file.size / MB).toFixed(1)} MB; the library takes files up to 20.0 MB.`);
    if (file.size === 0) return refused("The file is empty.");
    if (this.docs.length >= MOCK_LIMITS.max_documents) return refused(`The library holds ${MOCK_LIMITS.max_documents} documents, its most. Remove one first.`);
    await wait(500);
    if (kind === "pdf" && /scan/i.test(file.name)) {
      return refused("The PDF has no text in it: it looks like scanned pages, which the library cannot read. Add a PDF with selectable text, or the text itself.");
    }
    let text: string;
    if (kind === "pdf" || kind === "docx") {
      text = `${file.name}\n\nMock mode reads no ${kind === "pdf" ? "PDF" : "Word"} files; this line stands in for the text the assistant would take out of it.`;
    } else {
      text = (await file.text()).replace(/\r\n?/g, "\n").trim();
      if (!text) return refused("There is no text in the file.");
    }
    if (text.length > MOCK_LIMITS.max_text_chars) return refused(`The text is ${text.length.toLocaleString("en")} characters; the library keeps documents of up to 400,000 characters. Split it into parts and add them one by one.`);
    const title = cleanTitle(file.name.slice(0, dot).replace(/_/g, " ")) ?? "Document";
    return ok(this.put(title, kind, file.size, text, Date.now() / 1000, file.name));
  }

  addText(title: string, text: string): Promise<Result<LibraryDocument>> {
    const t = cleanTitle(title);
    if (!t) return Promise.resolve(refused(TITLE_RULE));
    const body = text.replace(/\r\n?/g, "\n").trim();
    if (!body) return Promise.resolve(refused("The document has no text."));
    if (body.length > MOCK_LIMITS.max_text_chars) return Promise.resolve(refused("The text is too long; the library keeps documents of up to 400,000 characters."));
    return Promise.resolve(ok(this.put(t, "note", null, body, Date.now() / 1000)));
  }

  open(name: string): Promise<Result<OpenDocument>> {
    const found = this.find(name);
    if (!found) return Promise.resolve(refused(`There is no document called '${name}'.`));
    return wait(150).then(() => ok({ document: { ...found.doc }, text: found.text }));
  }

  rename(name: string, title: string): Promise<Result<LibraryDocument>> {
    const found = this.find(name);
    if (!found) return Promise.resolve(refused(`There is no document called '${name}'.`));
    const t = cleanTitle(title);
    if (!t) return Promise.resolve(refused(TITLE_RULE));
    found.doc = { ...found.doc, title: t };
    return Promise.resolve(ok({ ...found.doc }));
  }

  remove(name: string): Promise<Result<LibraryDocument>> {
    const found = this.find(name);
    if (!found) return Promise.resolve(refused(`There is no document called '${name}'.`));
    this.docs = this.docs.filter((d) => d !== found);
    return Promise.resolve(ok({ ...found.doc }));
  }
}
