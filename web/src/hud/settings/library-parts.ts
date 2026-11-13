// Small pieces of the Library group: a document's kind, size and date in
// words, and one line per file being added that turns into its outcome.

import type { DocKind, LibraryDocument } from "../../net/library-types";
import { el } from "../dom";
import { statusLine, type Tone } from "./fields";
import { formatBytes, formatWhen } from "./format";

const KIND_WORDS: Record<DocKind, string> = { note: "Note", markdown: "Markdown", text: "Text", pdf: "PDF", docx: "Word" };

export const kindWords = (kind: DocKind): string => KIND_WORDS[kind];

/** "PDF · 178 KB · 3 parts · added 12 Nov 2026, 13:05" */
export function metaWords(doc: LibraryDocument): string {
  const parts = doc.parts > 1 ? ` · ${doc.parts} parts` : "";
  return `${kindWords(doc.kind)} · ${formatBytes(doc.bytes)}${parts} · added ${formatWhen(doc.added_at)}`;
}

export function documentMeta(doc: LibraryDocument): HTMLElement {
  return el("p", "doc-meta caps", metaWords(doc));
}

/** A file's name with how its adding went; `set` changes the outcome. */
export function uploadLine(name: string, tone: Tone, text: string): { root: HTMLElement; set(tone: Tone, text: string): void } {
  const root = el("li", "upload-line");
  const label = el("span", "upload-name", name);
  let status = statusLine(tone, text);
  root.append(label, status);
  return {
    root,
    set(next, words) {
      const fresh = statusLine(next, words);
      status.replaceWith(fresh);
      status = fresh;
    },
  };
}
