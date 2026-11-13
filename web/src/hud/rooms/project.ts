// A room's project name, apart from the DOM: the limit and the daemon's rules
// as guards, and the name a room's first folder suggests. A suggestion is only
// offered; nothing is saved until the owner saves the room.

import { projectProblem } from "../../net/project-name";
import type { Room } from "../../net/types";

/** "harbor-books-project", "HarborBooks_app" and "harbor.books" read as "Harbor Books Project", "Harbor Books App" and "Harbor Books". */
export function tidyName(folderName: string): string {
  return folderName
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[\s\-_.]+/)
    .filter((word) => word !== "")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** The first folder's own name, tidied; null without folders, for a folder with no name of its own (`/`, `~`), or when the result would not be a valid project name. */
export function suggestProject(folders: readonly string[]): string | null {
  const first = folders.find((f) => f.trim() !== "");
  if (first === undefined) return null;
  const last = first.trim().replace(/\/+$/, "").split("/").pop() ?? "";
  const name = tidyName(last === "~" ? "" : last);
  return name !== "" && projectProblem(name) === null ? name : null;
}

/** What the room card says about the name: the name itself, or that there is none when the room has folders to suggest one from. */
export type ProjectLine = { kind: "named"; name: string } | { kind: "none" } | null;

export function projectLine(room: Pick<Room, "project" | "folders">): ProjectLine {
  if (room.project) return { kind: "named", name: room.project };
  return room.folders.length > 0 ? { kind: "none" } : null;
}

/** The example the field shows while the room has no folder to suggest a name from. */
export const EXAMPLE_PROJECT = "The project's name, such as Harbor Books";

/** What the project field shows for its text: the placeholder, whether "Use this name" is offered, and the message to show, a refusal first and else the guard's. */
export interface FieldView {
  placeholder: string;
  /** The suggestion "Use this name" would fill in; null when it is not offered (no suggestion, or the field is not empty). */
  offer: string | null;
  error: string;
}

export function fieldView(text: string, folders: readonly string[], refusal: string): FieldView {
  const suggestion = suggestProject(folders);
  return { placeholder: suggestion ?? EXAMPLE_PROJECT, offer: text.trim() === "" ? suggestion : null, error: refusal || projectProblem(text) || "" };
}
