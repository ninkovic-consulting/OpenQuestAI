// What the Library group asks of the daemon, and the HTTP client for it.
// Mock mode (mock-library.ts) implements the same interface. A file goes up
// as the whole request body, its name in a header, never in the URL.

import type { Api } from "./api";
import { asAdded, asListing, asOpen, asRemoved } from "./library-guards";
import type { LibraryDocument, LibraryListing, OpenDocument } from "./library-types";
import { ok, refused, type Result } from "./settings-api";

export interface LibraryApi {
  list(): Promise<Result<LibraryListing>>;
  /** Adds a text, Markdown, PDF or Word file; its text is taken out now and the file kept. */
  addFile(file: File): Promise<Result<LibraryDocument>>;
  addText(title: string, text: string): Promise<Result<LibraryDocument>>;
  open(name: string): Promise<Result<OpenDocument>>;
  rename(name: string, title: string): Promise<Result<LibraryDocument>>;
  remove(name: string): Promise<Result<LibraryDocument>>;
}

const SHAPE = "The answer was not in the expected shape.";

/** A document's route; its name may hold a slash (a note in a subfolder), kept as one. */
export const documentPath = (name: string): string => `/api/library/documents/${name.split("/").map(encodeURIComponent).join("/")}`;

export class HttpLibrary implements LibraryApi {
  constructor(private readonly api: Api) {}

  private async ask<T>(method: string, path: string, narrow: (v: unknown) => T | null, body?: unknown): Promise<Result<T>> {
    const answer = await this.api.call(method, path, body);
    return narrowed(answer, narrow);
  }

  list = () => this.ask("GET", "/api/library", asListing);
  addFile = async (file: File) => narrowed(await this.api.upload("/api/library/files", file.name, file), asAdded);
  addText = (title: string, text: string) => this.ask("POST", "/api/library/text", asAdded, { title, text });
  open = (name: string) => this.ask("GET", documentPath(name), asOpen);
  rename = (name: string, title: string) => this.ask("PATCH", documentPath(name), asAdded, { title });
  remove = (name: string) => this.ask("DELETE", documentPath(name), asRemoved);
}

function narrowed<T>(answer: Result<unknown>, narrow: (v: unknown) => T | null): Result<T> {
  if (!answer.ok) return answer;
  const value = narrow(answer.value);
  return value === null ? refused(SHAPE) : ok(value);
}
