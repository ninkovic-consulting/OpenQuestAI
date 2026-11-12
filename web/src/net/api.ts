// HTTP to the daemon. Every route needs `Authorization: Bearer <token>` (spec 5).

import { asToolRefs } from "./plan";
import { ok, refused, type Result } from "./settings-api";
import { asFieldErrors } from "./settings-guards";
import type { FieldError } from "./settings-types";
import type { NewRoom, PostResult, ProposeResult } from "./types";

const UNREACHABLE = "The assistant could not be reached.";

export class Api {
  constructor(private readonly token: string) {}

  private headers(): HeadersInit {
    return { authorization: `Bearer ${this.token}`, "content-type": "application/json" };
  }

  async get(path: string): Promise<unknown> {
    const res = await fetch(path, { headers: this.headers() });
    if (!res.ok) throw new Error(`${path} answered ${res.status}`);
    return res.json();
  }

  /** Any route, JSON both ways; a refusal comes back as text, with the field errors when there are some. */
  async call(method: string, path: string, body?: unknown): Promise<Result<unknown>> {
    let res: Response;
    try {
      res = await fetch(path, { method, headers: this.headers(), ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    } catch {
      return refused(UNREACHABLE);
    }
    const text = await res.text();
    if (!res.ok) {
      const why = readRefusal(res.status, text);
      return refused(why.message, why.errors);
    }
    try {
      return ok(text ? (JSON.parse(text) as unknown) : null);
    } catch {
      return refused("The answer was not JSON.");
    }
  }

  async proposeTools(project: string): Promise<ProposeResult> {
    let res: Response;
    try {
      res = await fetch(`/api/house/tools/propose?${new URLSearchParams({ project })}`, { headers: this.headers() });
    } catch {
      return { ok: false, message: "The house could not be reached." };
    }
    if (!res.ok) return { ok: false, message: await refusal(res) };
    const tools = asToolRefs(((await res.json()) as { tools?: unknown }).tools);
    return tools ? { ok: true, tools } : { ok: false, message: "The proposal was not in the expected shape." };
  }

  async postRoom(room: NewRoom): Promise<PostResult> {
    let res: Response;
    try {
      res = await fetch("/api/house/rooms", {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify(room),
      });
    } catch {
      return { ok: false, message: "The house could not be reached." };
    }
    if (res.ok) return { ok: true };
    return { ok: false, message: await refusal(res) };
  }
}

/** The server's refusal, verbatim: FastAPI puts it in `detail`. */
async function refusal(res: Response): Promise<string> {
  return readRefusal(res.status, await res.text()).message;
}

/**
 * A refusal's text and field errors. `detail` is a string, or for a settings
 * 400 `{"errors": [{field, message}]}`, whose messages are joined for the text.
 */
export function readRefusal(status: number, text: string): { message: string; errors: FieldError[] } {
  try {
    const body: unknown = JSON.parse(text);
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return { message: detail, errors: [] };
      const errors = asFieldErrors(detail);
      if (errors) return { message: errors.map((e) => e.message).join(" "), errors };
      return { message: JSON.stringify(detail), errors: [] };
    }
  } catch {
    // Not JSON: show the body as it came.
  }
  return { message: text || `The assistant answered ${status}.`, errors: [] };
}
