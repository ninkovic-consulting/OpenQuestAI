// What the Procedures tab asks of the daemon, and the HTTP client for it.
// Mock mode (mock-procedures.ts) implements the same interface.

import type { Api } from "./api";
import { asOneProcedure, asProcedureListing } from "./procedure-guards";
import type { Procedure, ProcedureEdit, ProcedureListing } from "./procedure-types";
import { asRemoved } from "./proposal-guards";
import { ok, refused, type Result } from "./settings-api";

export interface ProceduresApi {
  list(): Promise<Result<ProcedureListing>>;
  /** `owner` is an agent id or `shared`. */
  get(owner: string, name: string): Promise<Result<Procedure>>;
  edit(owner: string, name: string, edit: ProcedureEdit): Promise<Result<Procedure>>;
  remove(owner: string, name: string): Promise<Result<true>>;
}

const SHAPE = "The answer was not in the expected shape.";

export class HttpProcedures implements ProceduresApi {
  constructor(private readonly api: Api) {}

  private async ask<T>(method: string, path: string, narrow: (v: unknown) => T | null, body?: unknown): Promise<Result<T>> {
    const answer = await this.api.call(method, path, body);
    if (!answer.ok) return answer;
    const value = narrow(answer.value);
    return value === null ? refused(SHAPE) : ok(value);
  }

  list = () => this.ask("GET", "/api/procedures", asProcedureListing);
  get = (owner: string, name: string) => this.ask("GET", path(owner, name), asOneProcedure);
  edit = (owner: string, name: string, edit: ProcedureEdit) => this.ask("PUT", path(owner, name), asOneProcedure, edit);
  remove = (owner: string, name: string) => this.ask("DELETE", path(owner, name), asRemoved);
}

const path = (owner: string, name: string): string => `/api/procedures/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
