// A project folder: "Choose…" opens the Mac's folder panel when the app has
// it; otherwise a text field suggests folders from `GET /api/fs/dirs` as you
// type.

import type { NativeHelpers } from "../../net/native";
import type { SettingsApi } from "../../net/settings-api";
import { el } from "../dom";

const SUGGEST_DELAY_MS = 200;
const MAX_SHOWN = 8;

export interface FolderPicker {
  root: HTMLElement;
  value(): string;
  set(value: string): void;
}

export interface FolderPickerOptions {
  api: SettingsApi;
  native: NativeHelpers;
  value: string;
  onChange: (value: string) => void;
  label: string;
}

export function mountFolderPicker(opts: FolderPickerOptions): FolderPicker {
  const choose = opts.native.chooseFolder;
  return choose ? nativePicker(opts, choose) : typedPicker(opts);
}

function nativePicker(opts: FolderPickerOptions, choose: () => Promise<string | null>): FolderPicker {
  const root = el("div", "folder-picker is-native");
  const path = el("span", "folder-path");
  const pick = el("button", "small caps", "Choose…");
  const clear = el("button", "small caps", "Clear");
  pick.type = clear.type = "button";
  pick.setAttribute("aria-label", `${opts.label}: choose a folder`);
  root.append(path, pick, clear);
  let value = opts.value;
  const render = (): void => {
    path.textContent = value || "No folder";
    path.classList.toggle("is-empty", value === "");
    clear.hidden = value === "";
  };
  const set = (next: string): void => {
    value = next;
    render();
    opts.onChange(value);
  };
  pick.addEventListener("click", () => {
    void choose().then((chosen) => {
      if (chosen !== null) set(chosen);
    });
  });
  clear.addEventListener("click", () => set(""));
  render();
  return {
    root,
    value: () => value,
    set(next: string): void {
      value = next;
      render();
    },
  };
}

function typedPicker(opts: FolderPickerOptions): FolderPicker {
  const root = el("div", "folder-picker");
  const input = el("input");
  input.value = opts.value;
  input.placeholder = "~/Projects/my-app";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("aria-label", opts.label);
  const list = el("ul", "folder-suggestions");
  list.setAttribute("role", "listbox");
  list.hidden = true;
  root.append(input, list);
  let timer = 0;
  let asked = 0;

  const show = (dirs: { name: string; path: string }[]): void => {
    list.replaceChildren(
      ...dirs.slice(0, MAX_SHOWN).map((d) => {
        const item = el("li");
        const button = el("button");
        button.type = "button";
        button.setAttribute("role", "option");
        button.append(el("span", "name", d.name), el("span", "path", d.path));
        // Pressing here must not blur the field before the click lands.
        button.addEventListener("mousedown", (ev) => ev.preventDefault());
        button.addEventListener("click", () => {
          input.value = d.path;
          list.hidden = true;
          opts.onChange(d.path);
          input.focus();
        });
        item.append(button);
        return item;
      }),
    );
    list.hidden = dirs.length === 0 || document.activeElement !== input;
  };

  const suggest = async (): Promise<void> => {
    const mine = ++asked;
    const answer = await opts.api.folders(input.value);
    if (mine !== asked) return; // something newer was typed meanwhile
    show(answer.ok ? answer.value : []);
  };

  input.addEventListener("input", () => {
    opts.onChange(input.value);
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void suggest(), SUGGEST_DELAY_MS);
  });
  input.addEventListener("focus", () => {
    if (input.value.trim() !== "") void suggest();
  });
  input.addEventListener("blur", () => {
    list.hidden = true;
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !list.hidden) {
      ev.stopPropagation();
      list.hidden = true;
    }
  });
  return {
    root,
    value: () => input.value,
    set(next: string): void {
      input.value = next;
      list.hidden = true;
    },
  };
}
