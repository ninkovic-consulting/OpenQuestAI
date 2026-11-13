// One approved tool: where it stands, Enable or Disable, Delete, who may use
// it and how it runs, its reach, the script in use with its hash, every
// approved version with "Use this version", and the recent runs.

import type { Confinement, MadePatch, MadeRun, MadeTool, MadeToolDetail } from "../../net/proposal-types";
import { el } from "../dom";
import { clock } from "../jobs/model";
import { block, button, confirmButton, segmented, statusLine } from "../settings/fields";
import { exitWords, lastRunWords, lineCount, MADE_STATUS_WORD, networkWarning, seconds, shortHash, TIER_CHOICES, toggleAction, whoChoices, whoWord, TIER_WORD } from "./model";
import { codeBlock, confinementBlock, facts, hashLine, reachList, refusalLine, stateChip } from "./parts";

export interface ToolActions {
  /** Each answers the daemon's refusal, or null when it went through. */
  patch(patch: MadePatch): Promise<string | null>;
  use(version: number): Promise<string | null>;
  remove(): Promise<string | null>;
}

export interface ToolDetailOptions {
  tool: MadeTool;
  detail: MadeToolDetail | null;
  problem: string | null;
  confinement: Confinement | null;
  now: number;
  act: ToolActions;
}

export function toolDetail(o: ToolDetailOptions): HTMLElement {
  const { tool } = o;
  const root = el("div", "group-body job-detail tool-detail");
  const said = refusalLine();
  const top = el("div", "job-top");
  top.append(stateChip(tool.status, MADE_STATUS_WORD[tool.status], `version ${tool.version}`));
  const toggle = toggleAction(tool);
  if (toggle) {
    const b = button(toggle === "enable" ? "Enable" : "Disable", toggle === "enable" ? "primary" : "plain");
    b.addEventListener("click", () => {
      b.disabled = true;
      void o.act.patch({ enabled: toggle === "enable" }).then((problem) => {
        b.disabled = false;
        said.say(problem);
      });
    });
    top.append(b);
  }
  top.append(
    confirmButton("Delete", { question: `Delete ${tool.name}? Its versions and runs go with it, and no agent can use it any more.`, confirm: "Delete", danger: true }, async () => {
      const problem = await o.act.remove();
      said.say(problem);
      return problem === null ? "Deleted." : "";
    }),
  );
  root.append(top, said.node);
  if (tool.disabled_reason) root.append(statusLine(tool.status === "changed" ? "bad" : "warn", tool.disabled_reason));

  root.append(
    facts([
      ["Written by", tool.author_name],
      ["Tool", tool.tool_name],
      ["Runs", lastRunWords(tool.last_run, tool.runs, o.now)],
      ["Approved", clock(tool.created_at, o.now)],
    ]),
  );
  root.append(choices(tool, o, said.say));
  root.append(block("Why", el("p", "job-text", tool.reason)), block("Reach", reachList(tool.reach)));

  if (!o.detail) {
    root.append(statusLine(o.problem ? "bad" : "idle", o.problem ? `The script and runs could not be loaded: ${o.problem}` : "Loading the script and the runs…"));
    return root;
  }
  const d = o.detail.tool;
  const script = d.script ?? "";
  root.append(block(`Script in use · version ${d.version} · ${lineCount(script)} lines`, codeBlock(script, `The script of ${tool.name}`), hashLine(d.sha256)));
  root.append(block(`Versions · ${d.versions.length}`, versions(d, o, said.say)));
  root.append(block(`Recent runs · ${o.detail.runs.length}`, runs(o.detail.runs, o.now)));
  root.append(block("Confinement", confinementBlock(o.confinement)));
  return root;
}

/** Who may use it and how it runs, each applied as soon as it is picked. */
function choices(tool: MadeTool, o: ToolDetailOptions, say: (t: string | null) => void): HTMLElement {
  const root = el("section", "block decide");
  root.append(el("h4", "caps", "Use"));
  const warn = el("p", "field-error decide-warning", networkWarning(tool, tool.tier) ?? "");
  warn.hidden = networkWarning(tool, tool.tier) === null;
  const row = (label: string, control: HTMLElement): HTMLElement => {
    const line = el("div", "decide-row");
    line.append(el("span", "caps decide-label", label), control);
    return line;
  };
  const apply = (patch: MadePatch): void => void o.act.patch(patch).then(say);
  root.append(
    row("Who may use it", segmented("Who may use it", whoChoices(tool.author_name), tool.who, (v) => apply({ who: v === "everyone" ? "everyone" : "author" }))),
    row("How it runs", segmented("How it runs", TIER_CHOICES, tool.tier, (v) => apply({ tier: v === "free" ? "free" : "ask" }))),
    warn,
    el("p", "field-note", `Now: ${whoWord(tool.who, tool.author_name)}, ${TIER_WORD[tool.tier]}.`),
  );
  return root;
}

function versions(d: MadeTool, o: ToolDetailOptions, say: (t: string | null) => void): HTMLElement {
  const list = el("ul", "version-list");
  for (const v of [...d.versions].sort((a, b) => b.version - a.version)) {
    const item = el("li", `version-row${v.version === d.version ? " is-current" : ""}`);
    const text = el("div", "version-text");
    const hash = el("code", "hash", shortHash(v.sha256));
    hash.title = v.sha256;
    const line = el("span", "version-meta");
    line.append(`approved ${clock(v.approved_at, o.now)} · `, hash);
    text.append(el("span", "version-name", `Version ${v.version}`), line);
    item.append(text);
    if (v.version === d.version && d.status !== "changed") item.append(el("span", "tag version-tag", "in use"));
    else if (d.status !== "pending") {
      const use = button("Use this version");
      use.addEventListener("click", () => {
        use.disabled = true;
        void o.act.use(v.version).then((problem) => {
          use.disabled = false;
          say(problem);
        });
      });
      item.append(use);
    }
    if (v.script !== undefined && v.version !== d.version) {
      const peek = el("details", "compare version-peek");
      peek.append(el("summary", "caps", "Read it"), codeBlock(v.script, `Version ${v.version}`));
      item.append(peek);
    }
    list.append(item);
  }
  return list;
}

function runs(list: readonly MadeRun[], now: number): HTMLElement {
  if (list.length === 0) return el("p", "field-note", "It has not run yet.");
  const ol = el("ol", "run-list");
  for (const r of list) {
    const item = el("li", `run-row${r.exit_code === 0 ? " is-ok" : " is-bad"}`);
    const head = el("div", "run-head");
    head.append(el("span", "dot"), el("span", "run-when", clock(r.ts, now)), el("span", "caps run-who", r.agent_name), el("span", "run-exit", exitWords(r.exit_code)), el("span", "run-secs", seconds(r.seconds)), el("span", "run-version", `v${r.version}`));
    const input = el("code", "run-input", r.input);
    const output = el("pre", "code-block run-output", r.output || "(no output)");
    output.tabIndex = 0;
    item.append(head, input, output);
    if (r.truncated) item.append(el("p", "field-note", "The output was longer and was cut."));
    if (r.swept > 0) item.append(el("p", "field-note", `${r.swept} leftover ${r.swept === 1 ? "process was" : "processes were"} stopped after the run.`));
    ol.append(item);
  }
  return ol;
}
