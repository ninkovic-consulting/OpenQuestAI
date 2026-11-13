// The daemon's rules for a room's project name, as guards the window and mock
// mode share: plain text on one line, at most 60 characters, not a folder path.

/** The longest project name the daemon takes. */
export const MAX_PROJECT_NAME = 60;

/** Why the daemon would refuse this text as a project name, in its words, or null when it is fine (blank means none). */
export function projectProblem(text: string): string | null {
  const name = text.trim();
  if (name.startsWith("/") || name.startsWith("~")) return "That looks like a folder path. A project name is a name, such as Harbor Books; put folders in Project folders.";
  if (name.length > MAX_PROJECT_NAME) return `The project name is ${name.length} characters; use at most ${MAX_PROJECT_NAME}.`;
  if (/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/.test(name)) return "The project name must be one line of plain text.";
  return null;
}
