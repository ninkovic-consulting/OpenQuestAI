// A room's folder list, apart from the DOM: cleaning what was typed, comparing
// two lists, and the short texts the control shows.

/** The paths as the daemon should get them: trimmed, none empty. */
export function cleanFolders(folders: readonly string[]): string[] {
  return folders.map((f) => f.trim()).filter((f) => f !== "");
}

/** The same folders in the same order; the first is where programs run, so order matters. */
export function sameFolders(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((f, i) => f === b[i]);
}

/** The same folders in any order. */
export function sameFolderSet(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((f) => b.includes(f));
}

/** The list with one more folder at the end; blank text changes nothing. The daemon refuses a duplicate. */
export function withFolder(folders: readonly string[], path: string): string[] {
  const next = path.trim();
  return next === "" ? [...folders] : [...folders, next];
}

/** The list without the folder at `index`. */
export function withoutFolder(folders: readonly string[], index: number): string[] {
  return folders.filter((_, i) => i !== index);
}

/** The reason "Add folder" is off, or null while there is room for another. */
export function limitReason(count: number, max: number): string | null {
  return count >= max ? `A room can have at most ${max} folders.` : null;
}

/** What to tell the owner about how the folders are used. */
export function foldersNote(count: number): string {
  if (count === 0) return "Add a folder and the agent can work in it.";
  return "Programs run in the first folder unless an agent says otherwise. Agents write file paths as folder-name/path.";
}
