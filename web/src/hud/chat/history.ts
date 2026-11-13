// `GET /api/history` answers `{turns: [TurnRecord...]}`, oldest first. This
// narrows it to what the thread shows; anything malformed is left out.

import type { Result } from "../../net/settings-api";
import { asOrigin, type HistoryTurn } from "./entries";

/** Fetches `/api/history`; the daemon client provides it. */
export type HistoryLoader = () => Promise<Result<unknown>>;

const STATUSES: ReadonlySet<string> = new Set(["ok", "interrupted", "failed"]);

/** The first line of a job report's text (vision/jobs/words.py): `Tink finished job 3f2a91c0, "Title".` or `Tink's job 3f2a91c0, "Title", failed: ...`. */
const REPORT_HEAD = /^(.+?)(?: finished job |'s job )\S+, "(.*)"/;

/** A job report's turn shows the resident and the job's title instead of the text the host was given. */
export function reportOf(text: string): { agent: string; title: string } | null {
  const m = REPORT_HEAD.exec(text.split("\n", 1)[0] ?? "");
  return m ? { agent: m[1] ?? "", title: m[2] ?? "" } : null;
}

function asTurn(raw: unknown): HistoryTurn | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const { started_at, source, user_text, reply, status } = r;
  if (typeof started_at !== "number") return null;
  if (typeof user_text !== "string" || typeof reply !== "string") return null;
  if (typeof status !== "string" || !STATUSES.has(status)) return null;
  const origin = asOrigin(typeof source === "string" ? source : null);
  const report = origin === "job" ? reportOf(user_text) : null;
  return {
    startedAt: started_at,
    origin,
    ...(report ? { agent: report.agent } : {}),
    user: report ? report.title : user_text,
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
