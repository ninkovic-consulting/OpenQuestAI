// Mock mode's rules for a room's project folders, worded as the daemon words
// its refusals: at most the limit, none empty, none listed twice, none inside
// another, not the home folder, and each one must exist.

const bare = (path: string): string => (path.length > 1 ? path.replace(/\/+$/, "") : path);

/** Whether `inner` lies inside `outer`. */
const isInside = (inner: string, outer: string): boolean => inner.startsWith(`${outer}/`);

/** Why a folder cannot hold new projects, in the daemon's words, or null when it can. */
export function rootProblem(path: string, exists: (path: string) => boolean): string | null {
  const given = bare(path.trim());
  if (!given.startsWith("/") && !given.startsWith("~")) return `${given || "An empty path"} is not a full path; start it with / or ~.`;
  if (given === "/" || given === "~" || given === "/Users") return `${given} is the disk, the home folder or a folder above it; new projects need a folder of their own, such as ~/Projects.`;
  return exists(given) ? null : `${given} is not a folder on this Mac.`;
}

/** The first rule the list breaks, in the daemon's words, or null when it is fine. */
export function folderRefusal(folders: readonly string[], max: number): string | null {
  if (folders.length > max) return `A room can have at most ${max} folders.`;
  const paths = folders.map((f) => bare(f.trim()));
  for (const [i, path] of paths.entries()) {
    if (path === "") return "A folder path cannot be empty.";
    if (path === "~" || path === "/") return "Your home folder is too wide to give to a room.";
    if (path.includes("nowhere")) return `${path} is not a folder.`;
    if (paths.indexOf(path) !== i) return `${path} is listed twice.`;
  }
  for (const inner of paths) {
    const outer = paths.find((p) => isInside(inner, p));
    if (outer !== undefined) return `${inner} is inside ${outer}; keep one of them.`;
  }
  return null;
}
