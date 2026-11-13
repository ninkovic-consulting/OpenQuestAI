// "Where new projects go": the one folder the host makes new project folders
// in when the owner asks it to start a project. Saved on its own, at once,
// like a room; the daemon checks the folder exists and is not the disk or the
// home folder itself.

import { el } from "../dom";
import { mountFolderPicker } from "../pickers/folder-picker";
import type { SettingsContext } from "./context";
import { block, button, fieldRow, note } from "./fields";

export function projectsRootBlock(ctx: SettingsContext): HTMLElement {
  let saved = ctx.settings.projects.root;
  let value = saved;
  const save = button("Save folder", "primary");
  const result = note();
  const picker = mountFolderPicker({
    api: ctx.api,
    native: ctx.native,
    value,
    label: "Where new projects go",
    onChange: (next) => {
      value = next;
      result.textContent = "";
      save.disabled = value.trim() === saved;
    },
  });
  const row = fieldRow("Folder", picker.root, {
    note: `When you ask ${ctx.settings.assistant.name} to start a new project, its folder is made here, with a room for it in the house. The folder must exist; it cannot be the disk or your home folder itself.`,
  });
  save.disabled = true;
  save.addEventListener("click", () => {
    save.disabled = true;
    result.textContent = "Saving…";
    void ctx.api.patchSettings({ projects: { root: value.trim() } }).then((r) => {
      if (r.ok) {
        saved = r.value.settings.projects.root;
        result.textContent = `Saved. New projects go in ${saved}.`;
        void ctx.reload({ redraw: false });
      } else {
        save.disabled = false;
        result.textContent = r.errors.find((e) => e.field === "projects.root")?.message ?? r.message;
      }
    });
  });
  const actions = el("div", "row-actions");
  actions.append(save);
  return block("Where new projects go", row, actions, result);
}
