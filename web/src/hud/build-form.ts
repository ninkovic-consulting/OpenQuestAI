// The short form that asks for a new room on a clicked free slot and posts it.
// A refusal from the server is shown exactly as it came.

import type { Daemon } from "../net/daemon";
import type { Store } from "../net/store";
import type { Cell, NewRoom } from "../net/types";
import { el } from "./dom";

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
  form.append(title, where, field("Name", name), field("Agent", agent), field("Project folder", project), field("Model (optional)", model), refusal, actions);
  parent.append(form);

  let cell: Cell | null = null;

  const close = (): boolean => {
    if (!form.classList.contains("is-open")) return false;
    form.classList.remove("is-open");
    cell = null;
    return true;
  };

  cancel.addEventListener("click", close);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!cell) return;
    const room: NewRoom = { name: name.value.trim(), agent: agent.value, at: cell };
    if (project.value.trim()) room.project = project.value.trim();
    if (model.value.trim()) room.model = model.value.trim();
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
      form.classList.add("is-open");
      name.focus();
    },
    close,
  };
}

