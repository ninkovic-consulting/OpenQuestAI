// What the Automations group asks of the daemon, and the HTTP client for it.
// Mock mode (mock-automations.ts) implements the same interface.

import type { Api } from "./api";
import { asAutomationList, asOneAutomation } from "./automation-guards";
import type { Automation, AutomationBody, AutomationList, AutomationPatch } from "./automation-types";
import { ok, refused, type Result } from "./settings-api";

export interface AutomationsApi {
  list(): Promise<Result<AutomationList>>;
  create(body: AutomationBody): Promise<Result<Automation>>;
  update(id: string, patch: AutomationPatch): Promise<Result<Automation>>;
  remove(id: string): Promise<Result<null>>;
  /** Run it once now, outside its schedule; it starts when the assistant is free. */
  run(id: string): Promise<Result<Automation>>;
}

const SHAPE = "The answer was not in the expected shape.";

export class HttpAutomations implements AutomationsApi {
  constructor(private readonly api: Api) {}

  private async ask<T>(method: string, path: string, narrow: (v: unknown) => T | null, body?: unknown): Promise<Result<T>> {
    const answer = await this.api.call(method, path, body);
    if (!answer.ok) return answer;
    const value = narrow(answer.value);
    return value === null ? refused(SHAPE) : ok(value);
  }

  list = () => this.ask("GET", "/api/automations", asAutomationList);
  create = (body: AutomationBody) => this.ask("POST", "/api/automations", asOneAutomation, body);
  update = (id: string, patch: AutomationPatch) => this.ask("PATCH", path(id), asOneAutomation, patch);
  remove = (id: string) => this.ask("DELETE", path(id), accepted).then(done);
  run = (id: string) => this.ask("POST", `${path(id)}/run`, asOneAutomation);
}

const path = (id: string): string => `/api/automations/${encodeURIComponent(id)}`;
/** A delete answers `{deleted: id}`; only success matters. */
const accepted = (): true => true;
const done = (r: Result<true>): Result<null> => (r.ok ? ok(null) : r);
