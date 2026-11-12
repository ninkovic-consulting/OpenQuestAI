// HTTP to the daemon. Every route needs `Authorization: Bearer <token>` (spec 5).

import { asToolRefs } from "./plan";
import type { NewRoom, PostResult, ProposeResult } from "./types";

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
  const text = await res.text();
  try {
    const body: unknown = JSON.parse(text);
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      return typeof detail === "string" ? detail : JSON.stringify(detail);
    }
  } catch {
    // Not JSON: show the body as it came.
  }
  return text || `The house answered ${res.status}.`;
}
