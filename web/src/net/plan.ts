import type { Cell, Plan, Room, ToolRef } from "./types";

function isCell(v: unknown): v is Cell {
  return Array.isArray(v) && v.length === 2 && v.every((n) => Number.isInteger(n));
}

function isToolRef(v: unknown): v is ToolRef {
  if (typeof v !== "object" || v === null) return false;
  const t = v as Record<string, unknown>;
  return typeof t["id"] === "string" && typeof t["title"] === "string" && typeof t["available"] === "boolean" && typeof t["built_in"] === "boolean";
}

function isRoom(v: unknown): v is Room {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r["id"] === "string" &&
    typeof r["name"] === "string" &&
    (r["shape"] === "rect" || r["shape"] === "round") &&
    isCell(r["at"]) &&
    isCell(r["size"]) &&
    typeof r["floor"] === "string" &&
    typeof r["wall"] === "string" &&
    Array.isArray(r["tools"]) &&
    r["tools"].every(isToolRef)
  );
}

/** Narrow a JSON list to tool refs, or null when it is not one. */
export function asToolRefs(v: unknown): ToolRef[] | null {
  return Array.isArray(v) && v.every(isToolRef) ? v : null;
}

/** Narrow the JSON from `GET /api/house` to a plan, or null when it is not one. */
export function asPlan(raw: unknown): Plan | null {
  if (typeof raw !== "object" || raw === null) return null;
  const p = raw as Record<string, unknown>;
  const ok =
    typeof p["revision"] === "number" &&
    typeof p["cell_m"] === "number" &&
    typeof p["wall_height_m"] === "number" &&
    Array.isArray(p["agents"]) &&
    Array.isArray(p["rooms"]) &&
    p["rooms"].every(isRoom) &&
    Array.isArray(p["doors"]) &&
    Array.isArray(p["free_slots"]) &&
    p["free_slots"].every(isCell);
  return ok ? (raw as Plan) : null;
}

export function roomById(plan: Plan, id: string): Room | undefined {
  return plan.rooms.find((r) => r.id === id);
}

/**
 * The agent that is the assistant: the one running the room with id `hall`,
 * else the agent with id `host`, else the one carrying the assistant's name.
 */
export function hostAgentId(plan: Plan): string | undefined {
  const hall = plan.rooms.find((r) => r.id === "hall")?.agent;
  if (hall !== undefined) return hall;
  if (plan.agents.some((a) => a.id === "host")) return "host";
  return (plan.agents.find((a) => a.name === plan.assistant.name) ?? plan.agents[0])?.id;
}

/** The room the assistant sits in: the room with id `hall`, else the assistant's first room. */
export function hostRoom(plan: Plan): Room | undefined {
  const host = hostAgentId(plan);
  return plan.rooms.find((r) => r.id === "hall") ?? plan.rooms.find((r) => r.agent === host) ?? plan.rooms[0];
}
