// Narrowing the library routes' JSON to their types, or null when the shape is wrong.

import type { DocKind, LibraryDocument, LibraryListing, OpenDocument } from "./library-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const KINDS: readonly DocKind[] = ["note", "markdown", "text", "pdf", "docx"];

export function isDocument(v: unknown): v is LibraryDocument {
  return (
    isObj(v) &&
    isStr(v["name"]) &&
    isStr(v["title"]) &&
    KINDS.includes(v["kind"] as DocKind) &&
    isNum(v["chars"]) &&
    isNum(v["bytes"]) &&
    isNum(v["parts"]) &&
    isNum(v["added_at"]) &&
    isStr(v["gist"]) &&
    (v["original"] === null || isStr(v["original"])) &&
    typeof v["editable"] === "boolean"
  );
}

export function asListing(v: unknown): LibraryListing | null {
  if (!isObj(v) || !Array.isArray(v["documents"]) || !v["documents"].every(isDocument) || !isStr(v["folder"])) return null;
  const limits = v["limits"];
  if (!isObj(limits) || !isNum(limits["max_file_bytes"]) || !isNum(limits["max_text_chars"]) || !isNum(limits["max_documents"]) || !isNum(limits["title_max"])) return null;
  if (!Array.isArray(limits["endings"]) || !limits["endings"].every(isStr)) return null;
  return v as unknown as LibraryListing;
}

/** `{document}`, the answer to adding or renaming one. */
export function asAdded(v: unknown): LibraryDocument | null {
  return isObj(v) && isDocument(v["document"]) ? v["document"] : null;
}

export function asOpen(v: unknown): OpenDocument | null {
  return isObj(v) && isDocument(v["document"]) && isStr(v["text"]) ? { document: v["document"], text: v["text"] } : null;
}

export function asRemoved(v: unknown): LibraryDocument | null {
  return isObj(v) && isDocument(v["removed"]) ? v["removed"] : null;
}
