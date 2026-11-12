// `GET /api/history` answers `{turns: [TurnRecord...]}`, oldest first. This
// narrows it to what the thread shows; anything malformed is left out.

import type { Result } from "../../net/settings-api";
import { asOrigin, type HistoryTurn } from "./entries";

/** Fetches `/api/history`; the daemon client provides it. */
export type HistoryLoader = () => Promise<Result<unknown>>;

const STATUSES: ReadonlySet<string> = new Set(["ok", "interrupted", "failed"]);

function asTurn(raw: unknown): HistoryTurn | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const { started_at, source, user_text, reply, status } = r;
  if (typeof started_at !== "number") return null;
  if (typeof user_text !== "string" || typeof reply !== "string") return null;
  if (typeof status !== "string" || !STATUSES.has(status)) return null;
  return {
    startedAt: started_at,
    origin: asOrigin(typeof source === "string" ? source : null),
    user: user_text,
    reply,
    status: status as HistoryTurn["status"],
  };
}

export function asTurns(raw: unknown): HistoryTurn[] {
  if (typeof raw !== "object" || raw === null) return [];
  const turns = (raw as { turns?: unknown }).turns;
  if (!Array.isArray(turns)) return [];
  return turns.flatMap((t) => {
    const turn = asTurn(t);
    return turn ? [turn] : [];
  });
}
