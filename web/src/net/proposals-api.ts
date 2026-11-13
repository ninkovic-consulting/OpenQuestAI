// What the Proposals view asks of the daemon's proposals and made tools, and
// the HTTP client for it. Approving, declining and putting back exist only
// here, at the Mac. Mock mode (mock-proposals.ts) implements the same interface.

import type { Api } from "./api";
import { asMadeToolDetail, asMadeToolList, asOneMadeTool, asOneProposal, asProposalList, asRemoved } from "./proposal-guards";
import type { ApproveBody, MadePatch, MadeTool, MadeToolDetail, MadeToolList, Proposal, ProposalList } from "./proposal-types";
import { ok, refused, type Result } from "./settings-api";

/** How many proposals the list asks for. */
export const PROPOSAL_LIMIT = 50;

export interface ProposalsApi {
  list(): Promise<Result<ProposalList>>;
  /** One in full: the whole script, the whole persona. */
  get(id: string): Promise<Result<Proposal>>;
  /** A refusal's message is the daemon's sentence, for people; the proposal stays waiting. */
  approve(id: string, body: ApproveBody): Promise<Result<Proposal>>;
  decline(id: string, note: string): Promise<Result<Proposal>>;
  /** Puts back what an approved change replaced. */
  restore(id: string): Promise<Result<Proposal>>;
  tools(): Promise<Result<MadeToolList>>;
  tool(name: string): Promise<Result<MadeToolDetail>>;
  patchTool(name: string, patch: MadePatch): Promise<Result<MadeTool>>;
  useVersion(name: string, version: number): Promise<Result<MadeTool>>;
  deleteTool(name: string): Promise<Result<true>>;
}

const SHAPE = "The answer was not in the expected shape.";

export class HttpProposals implements ProposalsApi {
  constructor(private readonly api: Api) {}

  private async ask<T>(method: string, path: string, narrow: (v: unknown) => T | null, body?: unknown): Promise<Result<T>> {
    const answer = await this.api.call(method, path, body);
    if (!answer.ok) return answer;
    const value = narrow(answer.value);
    return value === null ? refused(SHAPE) : ok(value);
  }

  list = () => this.ask("GET", `/api/proposals?limit=${PROPOSAL_LIMIT}`, asProposalList);
  get = (id: string) => this.ask("GET", proposalPath(id), asOneProposal);
  approve = (id: string, body: ApproveBody) => this.ask("POST", `${proposalPath(id)}/approve`, asOneProposal, body);
  decline = (id: string, note: string) => this.ask("POST", `${proposalPath(id)}/decline`, asOneProposal, note ? { note } : {});
  restore = (id: string) => this.ask("POST", `${proposalPath(id)}/restore`, asOneProposal);
  tools = () => this.ask("GET", "/api/made-tools", asMadeToolList);
  tool = (name: string) => this.ask("GET", toolPath(name), asMadeToolDetail);
  patchTool = (name: string, patch: MadePatch) => this.ask("PATCH", toolPath(name), asOneMadeTool, patch);
  useVersion = (name: string, version: number) => this.ask("POST", `${toolPath(name)}/versions/${version}/use`, asOneMadeTool);
  deleteTool = (name: string) => this.ask("DELETE", toolPath(name), asRemoved);
}

const proposalPath = (id: string): string => `/api/proposals/${encodeURIComponent(id)}`;
const toolPath = (name: string): string => `/api/made-tools/${encodeURIComponent(name)}`;
