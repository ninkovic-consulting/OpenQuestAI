// What the Jobs panel and the store ask of the daemon's job board, and the
// HTTP client for it. Mock mode (mock-jobs.ts) implements the same interface.

import type { Api } from "./api";
import { asJobList, asOneJob, asOneJobDetails, asStarted } from "./job-guards";
import type { Job, JobDetails, JobList, NewJob, Started } from "./job-types";
import { ok, refused, type Result } from "./settings-api";

/** How many jobs the list asks for. */
export const JOB_LIMIT = 50;

export interface JobsApi {
  list(): Promise<Result<JobList>>;
  get(id: string): Promise<Result<JobDetails>>;
  /** A refusal's message is the daemon's sentence, for people. */
  start(body: NewJob): Promise<Result<Started>>;
  cancel(id: string): Promise<Result<Job>>;
}

const SHAPE = "The answer was not in the expected shape.";

export class HttpJobs implements JobsApi {
  constructor(private readonly api: Api) {}

  private async ask<T>(method: string, path: string, narrow: (v: unknown) => T | null, body?: unknown): Promise<Result<T>> {
    const answer = await this.api.call(method, path, body);
    if (!answer.ok) return answer;
    const value = narrow(answer.value);
    return value === null ? refused(SHAPE) : ok(value);
  }

  list = () => this.ask("GET", `/api/jobs?limit=${JOB_LIMIT}`, asJobList);
  get = (id: string) => this.ask("GET", path(id), asOneJobDetails);
  start = (body: NewJob) => this.ask("POST", "/api/jobs", asStarted, body);
  cancel = (id: string) => this.ask("POST", `${path(id)}/cancel`, asOneJob);
}

const path = (id: string): string => `/api/jobs/${encodeURIComponent(id)}`;
