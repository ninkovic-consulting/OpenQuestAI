// The short form that asks for a new room on a clicked free slot and posts it.
// The project folder and the model come from the shared pickers; once a folder
// is chosen, the tools proposed for it appear as toggles. A refusal from the
// server is shown exactly as it came.

import type { Daemon } from "../net/daemon";
import { nativeHelpers } from "../net/native";
import type { Store } from "../net/store";
import type { Cell } from "../net/types";
import { el } from "./dom";
import { mountFolderPicker, type FolderPicker } from "./pickers/folder-picker";
import { mountModelPicker, OWN_MODEL, type ModelSource } from "./pickers/model-picker";
import { mountToolToggles } from "./pickers/tool-toggles";
import { agentChoices, newRoom } from "./room-form";

export interface BuildForm {
  open(cell: Cell): void;
  /** Close the form; false when it was not open. */
  close(): boolean;
}

/** The note under the tools: what an agent may do with them. */
export const toolsNote = (): string =>
  "Stored with the room. An agent working in the room may run these programs in the room's project folder, each time after your yes.";

export function mountBuildForm(parent: HTMLElement, store: Store, daemon: Daemon, models: ModelSource, onAdded: () => void): BuildForm {
  const form = el("form", "build-form");
  form.setAttribute("aria-label", "New room");
  const title = el("h2", "", "New room");
  const where = el("div", "where caps");
  const field = (label: string, control: HTMLElement): HTMLLabelElement => {
    const node = el("label", "caps", label);
    node.append(control);
    return node;
  };
  const name = el("input");
  name.required = true;
  name.maxLength = 40;
  const agent = el("select");
  const tools = mountToolToggles((folder) => daemon.proposeTools(folder), toolsNote);
  const model = mountModelPicker({ source: models, value: "", own: { label: OWN_MODEL, note: "The room uses its agent's model; nothing is sent." } });
  const projectSlot = el("div", "folder-slot");
  const noAgents = el("p", "tool-note", "Every agent in this house is busy as the host, so there is nobody to run a new room.");
  const refusal = el("div", "refusal");
  refusal.setAttribute("role", "alert");
  const actions = el("div", "actions");
  const submit = el("button", "primary caps", "Add room");
  submit.type = "submit";
  const cancel = el("button", "caps", "Cancel");
  cancel.type = "button";
  actions.append(submit, cancel);
  const projectLabel = el("div", "label caps", "Project folder");
  projectLabel.append(projectSlot);
  form.append(title, where, field("Name", name), field("Agent", agent), noAgents, projectLabel, tools.root, field("Model (optional)", model.root), refusal, actions);
  parent.append(form);

  let cell: Cell | null = null;
  let project: FolderPicker | null = null;

  const close = (): boolean => {
    if (!form.classList.contains("is-open")) return false;
    form.classList.remove("is-open");
    cell = null;
    return true;
  };

  cancel.addEventListener("click", close);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!cell || !agent.value) return;
    const room = newRoom({ name: name.value, agent: agent.value, at: cell, project: project?.value() ?? "", model: model.value() }, tools.picks());
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
      const choices = agentChoices(plan);
      agent.replaceChildren(
        ...choices.agents.map((a) => {
          const option = el("option", "", a.name);
          option.value = a.id;
          return option;
        }),
      );
      agent.value = choices.selected ?? "";
      noAgents.hidden = choices.selected !== null;
      submit.disabled = choices.selected === null;
      name.value = "";
      model.set("");
      project = mountFolderPicker({
        api: daemon.settings,
        native: nativeHelpers(),
        value: "",
        label: "Project folder",
        onChange: (folder) => tools.setProject(folder),
      });
      projectSlot.replaceChildren(project.root);
      tools.setProject("");
      refusal.textContent = "";
      form.classList.add("is-open");
      name.focus();
    },
    close,
  };
}
