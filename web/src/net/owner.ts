// The owner's profile as Settings carries it (`owner`), with the daemon's rules
// (vision/memory/profile.py), for the forms' limits and mock mode's checks.

export type OwnerPart = "name" | "business" | "notes";

export interface Owner {
  /** What the owner asks to be called. */
  name: string;
  /** The business, its name and what it does, in the owner's words. */
  business: string;
  /** Anything else the assistant should always keep in mind. */
  notes: string;
}

export const OWNER_PARTS: readonly OwnerPart[] = ["name", "business", "notes"];

export const OWNER_LIMITS: Record<OwnerPart, number> = { name: 60, business: 600, notes: 2000 };

const WHAT: Record<OwnerPart, string> = { name: "What to call you", business: "The business", notes: "What to keep in mind" };

export const emptyOwner = (): Owner => ({ name: "", business: "", notes: "" });

/** Why the daemon would refuse this value for a part; null when it is fine. */
export function ownerProblem(part: string, value: unknown): string | null {
  if (!OWNER_PARTS.includes(part as OwnerPart)) return `The profile has no part called '${part}'; it has name, business, notes.`;
  const key = part as OwnerPart;
  if (typeof value !== "string") return "Send text; an empty text clears the part.";
  const text = value.trim();
  const bad = key === "name" ? /[\u0000-\u001f\u007f]/ : /[\u0000-\u0008\u000b-\u001f\u007f]/;
  if (bad.test(text.replace(/\r\n/g, "\n"))) return key === "name" ? "What to call you must be one line of plain text." : "Use plain text, without control characters.";
  if (key !== "name" && /^## +\S/m.test(text)) return "A line may not start with ## here; that marks a part of the file.";
  if (text.length > OWNER_LIMITS[key]) return `${WHAT[key]} can be at most ${OWNER_LIMITS[key]} characters.`;
  return null;
}
