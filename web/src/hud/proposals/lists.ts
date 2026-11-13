// The lists on the left of the Proposals view: the proposals (waiting, then
// decided), the approved tools, and the procedures by agent.

import type { ProcedureListing } from "../../net/procedure-types";
import type { MadeTool, Proposal } from "../../net/proposal-types";
import { el } from "../dom";
import { clock } from "../jobs/model";
import { decidedLine, kindWord, lastRunWords, MADE_STATUS_WORD, madeRows, procedureGroups, procedureKey, proposalRows, STATUS_WORD, TIER_WORD, whoWord } from "./model";

interface Row {
  key: string;
  status: string;
  title: string;
  who: string;
  lines: string[];
}

function rowButton(r: Row, selected: string | null, pick: (key: string) => void): HTMLElement {
  const item = el("li");
  const b = el("button", `job-row pr-row is-${r.status}`);
  b.type = "button";
  b.setAttribute("aria-current", String(r.key === selected));
  const text = el("span", "job-row-text");
  text.append(el("span", "job-title", r.title), el("span", "job-who caps", r.who), ...r.lines.map((l) => el("span", "job-when", l)));
  b.append(el("span", "dot"), text);
  b.addEventListener("click", () => pick(r.key));
  item.append(b);
  return item;
}

const heading = (text: string): HTMLElement => el("li", "pr-heading caps", text);

function listOf(label: string): HTMLUListElement {
  const list = el("ul", "job-list pr-list");
  list.setAttribute("aria-label", label);
  return list;
}

export function proposalList(all: readonly Proposal[] | null, selected: string | null, now: number, pick: (id: string) => void): HTMLElement {
  const list = listOf("Proposals");
  if (all === null) return loading(list, "Loading the proposals…");
  const rows = proposalRows(all);
  if (rows.length === 0) {
    list.append(el("li", "job-empty", "Nothing proposed yet. When an agent proposes a new tool or a change to itself, it waits here for you."));
    return list;
  }
  const waiting = rows.filter((p) => p.status === "waiting");
  list.append(heading(waiting.length > 0 ? `Waiting for you · ${waiting.length}` : "Nothing waiting"));
  let decided = false;
  for (const p of rows) {
    if (p.status !== "waiting" && !decided) {
      decided = true;
      list.append(heading("Decided"));
    }
    const who = `${p.agent_name} · ${kindWord(p)} · ${STATUS_WORD[p.status]}`;
    list.append(rowButton({ key: p.id, status: p.status, title: p.title, who, lines: [p.status === "waiting" ? clock(p.created_at, now) : decidedLine(p, now)] }, selected, pick));
  }
  return list;
}

export function madeList(tools: readonly MadeTool[] | null, selected: string | null, now: number, pick: (name: string) => void): HTMLElement {
  const list = listOf("Approved tools");
  if (tools === null) return loading(list, "Loading the tools…");
  if (tools.length === 0) {
    list.append(el("li", "job-empty", "No approved tools yet. A tool an agent proposes appears here once you approve it."));
    return list;
  }
  for (const t of madeRows(tools)) {
    const who = `${t.author_name} · version ${t.version} · ${MADE_STATUS_WORD[t.status]}`;
    const lines = [`${whoWord(t.who, t.author_name)}, ${TIER_WORD[t.tier]}`, lastRunWords(t.last_run, t.runs, now)];
    list.append(rowButton({ key: t.name, status: t.status, title: t.name, who, lines }, selected, pick));
  }
  return list;
}

export function procedureList(listing: ProcedureListing | null, selected: string | null, now: number, pick: (key: string) => void): HTMLElement {
  const list = listOf("Procedures");
  if (listing === null) return loading(list, "Loading the procedures…");
  const { groups, none } = procedureGroups(listing);
  if (groups.length === 0) list.append(el("li", "job-empty", "No procedures yet. An agent writes one when it has worked out how to do something it will do again."));
  const author = (id: string): string => listing.agents.find((a) => a.id === id)?.name ?? id;
  for (const g of groups) {
    list.append(heading(`${g.name} · ${g.procedures.length}`));
    for (const p of g.procedures) {
      const who = `by ${author(p.author)} · read ${p.opened}×`;
      const lines = [p.when, `changed ${clock(p.changed_at, now)}`].filter((l) => l !== "");
      list.append(rowButton({ key: procedureKey(g.owner, p.name), status: p.shared ? "shared" : "own", title: p.title, who, lines }, selected, pick));
    }
  }
  if (groups.length > 0 && none.length > 0) list.append(el("li", "job-empty pr-none", `None yet: ${none.join(", ")}.`));
  return list;
}

function loading(list: HTMLUListElement, text: string): HTMLUListElement {
  list.append(el("li", "job-empty", text));
  return list;
}
