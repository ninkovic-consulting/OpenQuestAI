// The pieces of the room card that follow the board: who and where, what is
// happening, the tools, and the last jobs. Each is a plain function of the model.

import { el } from "../dom";
import { PHASE_WORD, TOOL_WORD, type RoomCardModel } from "./model";

function row(label: string, value: string | string[], muted = false): HTMLElement {
  const node = el("div", "row");
  const dd = el("dd", muted ? "is-muted" : "");
  if (typeof value === "string") dd.textContent = value;
  else dd.append(...value.map((path) => el("span", "path", path)));
  node.append(el("dt", "caps", label), dd);
  return node;
}

/** Who runs the room, on which model, and its project folders in full. */
export function setup(m: RoomCardModel): HTMLElement {
  const facts = el("dl");
  const model = row("Model", m.agent.model);
  model.querySelector("dd")?.setAttribute("title", m.agent.modelId);
  facts.append(
    row("Agent", m.agent.name),
    model,
    m.folders.length > 0 ? row(m.folders.length === 1 ? "Folder" : "Folders", m.folders) : row("Folders", "No project folders attached", true),
  );
  return facts;
}

function jobButton(id: string, className: string, onOpen: (id: string) => void): HTMLButtonElement {
  const b = el("button", `card-job ${className}`);
  b.type = "button";
  b.addEventListener("click", () => onOpen(id));
  return b;
}

/** Jobs working or waiting in the room, or the line that it is quiet. */
export function happening(m: RoomCardModel, onOpen: (id: string) => void): HTMLElement {
  const list = el("ul", "card-jobs");
  list.setAttribute("aria-label", "Happening now");
  if (m.now.length === 0) {
    list.append(el("li", "is-quiet", "Quiet: nothing is going on here."));
    return list;
  }
  for (const j of m.now) {
    const b = jobButton(j.id, `is-${j.phase}`, onOpen);
    const text = el("span", "card-job-text");
    text.append(el("span", "card-job-title", j.title), el("span", "card-job-meta", `${j.who}${j.visiting ? ", visiting" : ""} · ${PHASE_WORD[j.phase]}`));
    if (j.step) text.append(el("span", "card-job-step", j.step));
    b.append(el("span", "dot"), text);
    const item = el("li");
    item.append(b);
    list.append(item);
  }
  return list;
}

/** The last finished jobs, each opening in the Jobs panel. */
export function recent(m: RoomCardModel, onOpen: (id: string) => void): HTMLElement {
  const list = el("ul", "card-jobs");
  list.setAttribute("aria-label", "Recent jobs");
  if (m.recent.length === 0) {
    list.append(el("li", "is-quiet", "No finished jobs here yet."));
    return list;
  }
  for (const j of m.recent) {
    const b = jobButton(j.id, `is-${j.outcome}`, onOpen);
    const text = el("span", "card-job-text");
    text.append(el("span", "card-job-title", j.title), el("span", "card-job-meta", `${j.who} · ${j.when} · ${j.outcome}`));
    b.append(el("span", j.outcome === "done" ? "dot" : "dot hollow"), text);
    const item = el("li");
    item.append(b);
    list.append(item);
  }
  return list;
}

/** The tools with what each can do today, and the note on what they ask. */
export function tools(m: RoomCardModel): HTMLElement[] {
  const list = el("ul", "card-tools");
  list.setAttribute("aria-label", "Tools");
  for (const t of m.tools) {
    const item = el("li", `is-${t.state}`);
    item.append(el("span", t.state === "runs" ? "dot" : "dot hollow"), el("span", "title", t.title), el("span", "tag", TOOL_WORD[t.state]));
    list.append(item);
  }
  if (m.tools.length === 0) list.append(el("li", "is-empty", "No tools"));
  return m.note ? [list, el("p", "note", m.note)] : [list];
}
