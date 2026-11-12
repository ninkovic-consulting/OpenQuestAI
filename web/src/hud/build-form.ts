// The short form that asks for a new room on a clicked free slot and posts it.
// Once a project folder is entered, the tools proposed for it appear as
// toggles. A refusal from the server is shown exactly as it came.

import type { Daemon } from "../net/daemon";
import type { Store } from "../net/store";
import type { Cell } from "../net/types";
import { el } from "./dom";
import { fromProposal, newRoom, toggle, type ToolPicks } from "./room-form";

const PROPOSE_DELAY_MS = 350;

export interface BuildForm {
  open(cell: Cell): void;
  /** Close the form; false when it was not open. */
  close(): boolean;
}

export function mountBuildForm(parent: HTMLElement, store: Store, daemon: Daemon, onAdded: () => void): BuildForm {
  const form = el("form", "build-form");
  form.setAttribute("aria-label", "New room");
  const title = el("h2", "", "New room");
  const where = el("div", "where caps");
  const field = (label: string, input: HTMLInputElement | HTMLSelectElement): HTMLLabelElement => {
    const node = el("label", "caps", label);
    node.append(input);
    return node;
  };
  const name = el("input");
  name.required = true;
  name.maxLength = 40;
  const agent = el("select");
  const project = el("input");
  project.placeholder = "~/Projects/…";
  const tools = el("fieldset", "tools");
  const toolsLegend = el("legend", "caps", "Tools for this project");
  const toolList = el("div", "tool-list");
  const toolNote = el("p", "tool-note");
  tools.append(toolsLegend, toolList, toolNote);
  const model = el("input");
  model.placeholder = "The agent's own model";
  const refusal = el("div", "refusal");
  refusal.setAttribute("role", "alert");
  const actions = el("div", "actions");
  const submit = el("button", "primary caps", "Add room");
  submit.type = "submit";
  const cancel = el("button", "caps", "Cancel");
  cancel.type = "button";
  actions.append(submit, cancel);
  form.append(title, where, field("Name", name), field("Agent", agent), field("Project folder", project), tools, field("Model (optional)", model), refusal, actions);
  parent.append(form);

  let cell: Cell | null = null;
  let picks: ToolPicks | null = null;
  let asked = 0;
  let timer = 0;

  const assistant = (): string => store.get().plan?.assistant.name ?? "the assistant";

  const renderTools = (message?: string): void => {
    const folder = project.value.trim();
    tools.hidden = folder === "";
    if (message !== undefined || !picks) {
      toolList.replaceChildren();
      toolNote.textContent = message ?? "";
      return;
    }
    if (picks.tools.length === 0) {
      toolList.replaceChildren();
      toolNote.textContent = "No project tools recognised here; the room uses its agent's tools.";
      return;
    }
    const current = picks;
    toolList.replaceChildren(
      ...current.tools.map((tool) => {
        const on = current.on.has(tool.id);
        const button = el("button", `tool-toggle${tool.available ? "" : " is-unavailable"}`);
        button.type = "button";
        button.setAttribute("aria-pressed", String(on));
        button.append(el("span", on ? "dot" : "dot hollow"), el("span", "", tool.title));
        if (!tool.available) button.append(el("span", "tag", "not installed"));
        button.addEventListener("click", () => {
          if (picks) picks = toggle(picks, tool.id);
          renderTools();
        });
        return button;
      }),
    );
    toolNote.textContent = `Stored with the room. Project tools start working when the other agents wake up; for now only ${assistant()}'s built-in tools run.`;
  };

  const propose = async (): Promise<void> => {
    window.clearTimeout(timer);
    const folder = project.value.trim();
    const mine = ++asked;
    if (!folder) {
      picks = null;
      renderTools();
      return;
    }
    if (picks?.project === folder) return;
    picks = null;
    renderTools("Looking at the folder…");
    const result = await daemon.proposeTools(folder);
    if (mine !== asked) return; // a newer folder was typed meanwhile
    if (result.ok) {
      picks = fromProposal(folder, result.tools);
      renderTools();
    } else {
      renderTools(result.message);
    }
  };

  const close = (): boolean => {
    if (!form.classList.contains("is-open")) return false;
    form.classList.remove("is-open");
    cell = null;
    return true;
  };

  project.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void propose(), PROPOSE_DELAY_MS);
  });
  project.addEventListener("change", () => void propose());
  cancel.addEventListener("click", close);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!cell) return;
    const room = newRoom({ name: name.value, agent: agent.value, at: cell, project: project.value, model: model.value }, picks);
    submit.disabled = true;
    refusal.textContent = "";
    void daemon.postRoom(room).then((result) => {
      submit.disabled = false;
      if (result.ok) {
        close();
        onAdded();
      } else {
        refusal.textContent = result.message;
      }
    });
  });
  // Typing here must not reach the global shortcuts (Space is push to talk).
  form.addEventListener("keydown", (ev) => {
    ev.stopPropagation();
    if (ev.key === "Escape") close();
  });

  return {
    open(at: Cell): void {
      const plan = store.get().plan;
      if (!plan) return;
      cell = at;
      where.textContent = `Slot ${at[0]}, ${at[1]}`;
      agent.replaceChildren(
        ...plan.agents.map((a) => {
          const option = el("option", "", a.name);
          option.value = a.id;
          return option;
        }),
      );
      name.value = "";
      project.value = "";
      model.value = "";
      refusal.textContent = "";
      picks = null;
      asked += 1;
      renderTools();
      form.classList.add("is-open");
      name.focus();
    },
    close,
  };
}
