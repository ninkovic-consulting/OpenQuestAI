// A room's project folders: one per line with a remove control each, and
// "Add folder", which uses the Mac's folder panel when the app has it and
// otherwise a typed path with suggestions. Removing and adding only change the
// list; the caller saves it. At the limit, adding is off and says why.

import type { NativeHelpers } from "../../net/native";
import type { SettingsApi } from "../../net/settings-api";
import { el } from "../dom";
import { foldersNote, limitReason, withFolder, withoutFolder } from "../folders";
import { mountFolderPicker } from "./folder-picker";

export interface FolderList {
  root: HTMLElement;
  value(): string[];
  /** Replace the list without telling `onChange`. */
  set(folders: readonly string[]): void;
  /** A refusal of the list, shown beside it until the list changes. */
  setError(message: string): void;
}

export interface FolderListOptions {
  api: SettingsApi;
  native: NativeHelpers;
  folders: readonly string[];
  /** The most folders a room may have. */
  max: number;
  label: string;
  onChange: (folders: string[]) => void;
}

function button(label: string, ariaLabel?: string): HTMLButtonElement {
  const b = el("button", "small caps", label);
  b.type = "button";
  if (ariaLabel) b.setAttribute("aria-label", ariaLabel);
  return b;
}

export function mountFolderList(opts: FolderListOptions): FolderList {
  const root = el("div", "folder-list");
  const rows = el("ul", "folder-rows");
  rows.setAttribute("aria-label", opts.label);
  const none = el("p", "folder-none", "No folders.");
  const adding = el("div", "folder-adding");
  adding.hidden = true;
  const actions = el("div", "folder-actions");
  const add = button("Add folder");
  const reason = el("span", "folder-limit");
  actions.append(add, reason);
  const note = el("p", "folder-note");
  const error = el("p", "field-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  root.append(rows, none, adding, actions, note, error);

  let folders = [...opts.folders];

  const render = (): void => {
    rows.replaceChildren(
      ...folders.map((path, i) => {
        const row = el("li", "folder-row");
        const remove = button("Remove", `Remove ${path}`);
        remove.addEventListener("click", () => change(withoutFolder(folders, i)));
        row.append(el("span", "folder-path", path), remove);
        return row;
      }),
    );
    none.hidden = folders.length > 0;
    const full = limitReason(folders.length, opts.max);
    add.disabled = full !== null;
    reason.textContent = full ?? "";
    note.textContent = foldersNote(folders.length);
  };

  const change = (next: string[]): void => {
    folders = next;
    error.hidden = true;
    render();
    opts.onChange([...folders]);
  };

  const closeAdding = (): void => {
    adding.hidden = true;
    adding.replaceChildren();
    add.hidden = false;
    add.focus();
  };

  /** Adds the typed path; set while the typed row is open. */
  let commit: () => void = () => {};
  adding.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      ev.stopPropagation();
      commit();
    } else if (ev.key === "Escape") {
      ev.stopPropagation();
      closeAdding();
    }
  });

  const typeOne = (): void => {
    let draft = "";
    const picker = mountFolderPicker({
      api: opts.api,
      native: opts.native,
      value: "",
      label: `${opts.label}: path to add`,
      onChange: (v) => {
        draft = v;
        confirm.disabled = draft.trim() === "";
      },
    });
    const confirm = button("Add");
    confirm.disabled = true;
    const cancel = button("Cancel");
    commit = (): void => {
      if (draft.trim() === "") return;
      closeAdding();
      change(withFolder(folders, draft));
    };
    confirm.addEventListener("click", commit);
    cancel.addEventListener("click", closeAdding);
    const buttons = el("div", "folder-adding-actions");
    buttons.append(confirm, cancel);
    adding.replaceChildren(picker.root, buttons);
    adding.hidden = false;
    add.hidden = true;
    picker.root.querySelector("input")?.focus();
  };

  add.addEventListener("click", () => {
    const choose = opts.native.chooseFolder;
    if (!choose) {
      typeOne();
      return;
    }
    void choose().then((chosen) => {
      if (chosen !== null) change(withFolder(folders, chosen));
    });
  });

  render();
  return {
    root,
    value: () => [...folders],
    set(next: readonly string[]): void {
      folders = [...next];
      error.hidden = true;
      render();
    },
    setError(message: string): void {
      error.textContent = message;
      error.hidden = message === "";
    },
  };
}
