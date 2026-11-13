// Narrowing the procedure routes' JSON and the `procedure.changed` event to
// their types, or null when the shape is wrong.

import { PROCEDURE_CHANGES, type Procedure, type ProcedureChanged, type ProcedureListing, type ProcedureSummary } from "./procedure-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function isProcedureSummary(v: unknown): v is ProcedureSummary {
  return (
    isObj(v) &&
    isStr(v["name"]) &&
    v["name"] !== "" &&
    isStr(v["title"]) &&
    isStr(v["when"]) &&
    isStr(v["author"]) &&
    typeof v["shared"] === "boolean" &&
    isNum(v["changed_at"]) &&
    isNum(v["opened"]) &&
    isNum(v["chars"])
  );
}

const LIMIT_KEYS = ["name", "when", "steps", "per_agent", "shared"] as const;

export function asProcedureListing(v: unknown): ProcedureListing | null {
  if (!isObj(v) || !Array.isArray(v["agents"]) || !Array.isArray(v["shared"])) return null;
  const limits = v["limits"];
  if (!isObj(limits) || !LIMIT_KEYS.every((k) => isNum(limits[k]))) return null;
  if (!v["shared"].every(isProcedureSummary)) return null;
  const agentsOk = v["agents"].every((a) => isObj(a) && isStr(a["id"]) && isStr(a["name"]) && Array.isArray(a["procedures"]) && a["procedures"].every(isProcedureSummary));
  return agentsOk ? (v as unknown as ProcedureListing) : null;
}

/** `{procedure}`, as reading or editing one answers. */
export function asOneProcedure(v: unknown): Procedure | null {
  if (!isObj(v)) return null;
  const p = v["procedure"];
  return isProcedureSummary(p) && isStr((p as unknown as Obj)["steps"]) ? (p as Procedure) : null;
}

export function asProcedureChanged(v: unknown): ProcedureChanged | null {
  const ok = isObj(v) && isStr(v["owner"]) && v["owner"] !== "" && isStr(v["name"]) && v["name"] !== "" && PROCEDURE_CHANGES.includes(v["change"] as ProcedureChanged["change"]);
  return ok ? (v as unknown as ProcedureChanged) : null;
}
