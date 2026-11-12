// Narrowing `/api/automations` JSON to its types, or null when the shape is
// wrong. Like settings-guards.ts: check what the screen relies on.

import { WEEKDAYS, type Automation, type AutomationList, type RunResult, type Schedule } from "./automation-types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isIn = <T extends string>(values: readonly T[], v: unknown): v is T => typeof v === "string" && (values as readonly string[]).includes(v);

export function isSchedule(v: unknown): v is Schedule {
  if (!isObj(v)) return false;
  switch (v["kind"]) {
    case "once":
      return isStr(v["at"]);
    case "daily":
      return isStr(v["time"]);
    case "weekly":
      return isStr(v["time"]) && Array.isArray(v["days"]) && v["days"].every((d) => isIn(WEEKDAYS, d));
    case "interval":
      return isNum(v["every"]) && isIn(["minutes", "hours"], v["unit"]);
    case "cron":
      return isStr(v["expr"]);
    default:
      return false;
  }
}

function isResult(v: unknown): v is RunResult {
  return (
    isObj(v) &&
    isNum(v["started_at"]) &&
    isNum(v["ended_at"]) &&
    isIn(["ok", "failed", "interrupted", "needed_approval", "missed"], v["status"]) &&
    isStr(v["reply"]) &&
    isIn(["schedule", "catch_up", "manual"], v["trigger"])
  );
}

export function asAutomation(v: unknown): Automation | null {
  const ok =
    isObj(v) &&
    isStr(v["id"]) &&
    isStr(v["name"]) &&
    isStr(v["instruction"]) &&
    isSchedule(v["schedule"]) &&
    isBool(v["speak"]) &&
    isBool(v["paused"]) &&
    isBool(v["finished"]) &&
    (v["next_run"] === null || isNum(v["next_run"])) &&
    Array.isArray(v["results"]) &&
    v["results"].every(isResult) &&
    isStr(v["words"]) &&
    isBool(v["running"]);
  return ok ? (v as unknown as Automation) : null;
}

export function asAutomationList(v: unknown): AutomationList | null {
  if (!isObj(v) || !Array.isArray(v["automations"]) || !isStr(v["timezone"]) || !isNum(v["now"])) return null;
  const limits = v["limits"];
  if (!isObj(limits) || !isNum(limits["max_automations"]) || !isNum(limits["name_max"]) || !isNum(limits["instruction_max"])) return null;
  const automations = v["automations"].map(asAutomation);
  if (automations.some((a) => a === null)) return null;
  return v as unknown as AutomationList;
}

/** `{automation: ...}`, as POST, PATCH and run answer. */
export function asOneAutomation(v: unknown): Automation | null {
  return isObj(v) ? asAutomation(v["automation"]) : null;
}
