// The library routes' shapes (`/api/library`). The daemon is the source of
// truth; library-guards.ts narrows its JSON to these.

/** `note` is written (by hand, by the assistant or pasted); the others came from a file of that kind. */
export type DocKind = "note" | "markdown" | "text" | "pdf" | "docx";

export interface LibraryDocument {
  /** How routes and tools name it: its text file in the library, without `.md`. */
  name: string;
  title: string;
  kind: DocKind;
  chars: number;
  /** The original file's size, or the text's when there is none. */
  bytes: number;
  parts: number;
  added_at: number;
  gist: string;
  /** The kept original, relative to the library folder. */
  original: string | null;
  /** Its text may be changed (a written document, not one from a file). */
  editable: boolean;
}

export interface LibraryLimits {
  max_file_bytes: number;
  max_text_chars: number;
  max_documents: number;
  title_max: number;
  /** File endings the library takes, like `.pdf`. */
  endings: string[];
}

export interface LibraryListing {
  documents: LibraryDocument[];
  /** Where the files live on this Mac. */
  folder: string;
  limits: LibraryLimits;
}

export interface OpenDocument {
  document: LibraryDocument;
  text: string;
}
