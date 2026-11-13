// DOM pieces the proposal, tool and procedure details share: a numbered code
// block that scrolls inside itself, a hash, the reach, the confinement, a
// line diff, a refusal line and the state chip.

import type { Confinement, Reach } from "../../net/proposal-types";
import { el } from "../dom";
import { statusLine } from "../settings/fields";
import { confinementProblem, shortHash, type DiffLine } from "./model";

/** Code, every line numbered, never cut: the block scrolls inside itself both ways. */
export function codeBlock(text: string, label: string): HTMLElement {
  const pre = el("pre", "code-block");
  pre.tabIndex = 0;
  pre.setAttribute("aria-label", label);
  const code = el("code");
  const lines = text.replace(/\n$/, "").split("\n");
  code.append(...lines.map((line) => el("span", "code-line", line)));
  pre.append(code);
  return pre;
}

/** A short hash to compare by eye, the whole one on hover and for copying. */
export function hashLine(sha: string): HTMLElement {
  const line = el("p", "hash-line");
  const value = el("code", "hash", shortHash(sha));
  value.title = sha;
  line.append(el("span", "caps", "sha256"), value);
  return line;
}

/** The folders a tool may read and whether it may use the network. */
export function reachList(reach: Reach): HTMLElement {
  const list = el("ul", "reach-list");
  for (const f of reach.folders) {
    const item = el("li");
    item.append(el("span", "reach-name", f.name), el("code", "reach-path", f.path));
    list.append(item);
  }
  if (reach.folders.length === 0) list.append(el("li", "reach-none", "No folders: it reads nothing of yours."));
  const net = el("li", `reach-net${reach.network ? " is-on" : ""}`);
  net.append(el("span", "dot"), el("span", "", reach.network ? "Network: yes, it may connect out to any address." : "Network: no."));
  list.append(net);
  return list;
}

/** What macOS enforces for a run, and what rests on the owner reading the code; or why nothing will run. */
export function confinementBlock(c: Confinement | null): HTMLElement {
  const root = el("div", "confinement");
  if (c === null) {
    root.append(statusLine("idle", "Loading what the confinement enforces…"));
    return root;
  }
  const problem = confinementProblem(c);
  if (problem) {
    root.append(statusLine("bad", problem));
    return root;
  }
  const part = (title: string, lines: readonly string[], tone: string): HTMLElement => {
    const box = el("div", `confine-part is-${tone}`);
    const list = el("ul");
    list.append(...lines.map((l) => el("li", "", l)));
    box.append(el("h5", "caps", title), list);
    return box;
  };
  root.append(part("Enforced by macOS", c.enforced, "ok"), part("Not enforced: rests on your reading", c.not_enforced, "warn"));
  return root;
}

/** Lines removed and added, numbered as in the new text. */
export function diffBlock(lines: readonly DiffLine[], label: string): HTMLElement {
  const pre = el("pre", "code-block diff-block");
  pre.tabIndex = 0;
  pre.setAttribute("aria-label", label);
  const code = el("code");
  const mark = { same: " ", add: "+", del: "−" } as const;
  code.append(...lines.map((l) => el("span", `diff-line is-${l.kind}`, `${mark[l.kind]} ${l.text}`)));
  pre.append(code);
  return pre;
}

/** A refusal from the daemon near the buttons that drew it. */
export function refusalLine(): { node: HTMLElement; say(text: string | null): void } {
  const node = el("p", "field-error proposal-refusal");
  node.setAttribute("role", "alert");
  node.hidden = true;
  return {
    node,
    say(text) {
      node.hidden = text === null;
      node.textContent = text ?? "";
    },
  };
}

/** A dot and a word in a 1px border: where something stands. */
export function stateChip(status: string, word: string, when: string): HTMLElement {
  const chip = el("div", `job-state pr-state is-${status}`);
  chip.append(el("span", "dot"), el("span", "caps", word));
  if (when) chip.append(el("span", "when", when));
  return chip;
}

/** Facts as terms and values, as the job detail shows them. */
export function facts(rows: readonly [string, string | HTMLElement][]): HTMLElement {
  const list = el("dl", "job-facts");
  for (const [term, value] of rows) {
    const row = el("div");
    const dd = el("dd");
    dd.append(value);
    row.append(el("dt", "caps", term), dd);
    list.append(row);
  }
  return list;
}
