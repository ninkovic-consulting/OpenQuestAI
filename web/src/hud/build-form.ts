// The short form that asks for a new room on a clicked free slot and posts it.
// The project folders and the model come from the shared pickers; once a folder
// is added, the tools proposed for the folders appear as toggles. A refusal from the
// server is shown exactly as it came.

import type { Daemon } from "../net/daemon";
import { projectProblem } from "../net/project-name";
import { nativeHelpers } from "../net/native";
import type { Store } from "../net/store";
import type { Cell } from "../net/types";
import { agentChoice } from "./agent-choice";
import { el } from "./dom";
import { mountFolderList, type FolderList } from "./pickers/folder-list";
import { mountModelPicker, OWN_MODEL, type ModelSource } from "./pickers/model-picker";
import { mountProjectField, type ProjectField } from "./pickers/project-field";
import { mountToolToggles } from "./pickers/tool-toggles";
import { agentChoices, newRoom } from "./room-form";

export interface BuildForm {
  open(cell: Cell): void;
  /** Close the form; false when it was not open. */
  close(): boolean;
}

/** The note under the tools: what an agent may do with them. */
/** The note under the project name: what it is for. */
export const PROJECT_NOTE = "What you call the project this room holds, such as the product's name. Agents and the assistant can find the room by it. Optional.";

export const toolsNote = (): string =>
  "Stored with the room. An agent working in the room may run these programs in the room's project folders, each time after your yes.";

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
  const project: ProjectField = mountProjectField({ value: "", folders: [] });
  const foldersSlot = el("div", "folder-slot");
  const noAgents = el("p", "tool-note", "Every agent in this house is busy as the host, so there is nobody to run a new room.");
  const refusal = el("div", "refusal");
  refusal.setAttribute("role", "alert");
  const actions = el("div", "actions");
  const submit = el("button", "primary caps", "Add room");
  submit.type = "submit";
  const cancel = el("button", "caps", "Cancel");
  cancel.type = "button";
  actions.append(submit, cancel);
  const projectLabel = el("div", "label caps", "Project name");
  projectLabel.append(project.root);
  const foldersLabel = el("div", "label caps", "Project folders");
  foldersLabel.append(foldersSlot);
  form.append(title, where, field("Name", name), field("Agent", agent), noAgents, projectLabel, foldersLabel, tools.root, field("Model (optional)", model.root), refusal, actions);
  parent.append(form);

  let cell: Cell | null = null;
  let folders: FolderList | null = null;

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
    const problem = projectProblem(project.value());
    if (problem !== null) {
      project.setError(problem);
      return;
    }
    const room = newRoom({ name: name.value, agent: agent.value, at: cell, project: project.value(), folders: folders?.value() ?? [], model: model.value() }, tools.picks());
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
          const option = el("option", "", agentChoice(a));
          option.value = a.id;
          return option;
        }),
      );
      agent.value = choices.selected ?? "";
      noAgents.hidden = choices.selected !== null;
      submit.disabled = choices.selected === null;
      name.value = "";
      project.set("");
      project.setFolders([]);
      model.set("");
      folders = mountFolderList({
        api: daemon.settings,
        native: nativeHelpers(),
        folders: [],
        max: plan.max_room_folders,
        label: "Project folders",
        onChange: (list) => {
          project.setFolders(list);
          tools.setFolders(list);
        },
      });
      foldersSlot.replaceChildren(folders.root);
      tools.setFolders([]);
      refusal.textContent = "";
      form.classList.add("is-open");
      name.focus();
    },
    close,
  };
}
