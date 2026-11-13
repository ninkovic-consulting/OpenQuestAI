// A room's project name: one line of text, and, while it is empty and the room
// has folders, the name the first folder suggests as the placeholder with "Use
// this name" beside it. Nothing is filled in until the owner presses it; the
// caller saves the room.

import { MAX_PROJECT_NAME } from "../../net/project-name";
import { el } from "../dom";
import { fieldView } from "../rooms/project";

export interface ProjectField {
  root: HTMLElement;
  /** What is typed, as typed. */
  value(): string;
  /** Replace the text without telling `onChange`. */
  set(text: string): void;
  /** The room's folders changed: the suggestion follows the first. */
  setFolders(folders: readonly string[]): void;
  /** A refusal of the name, shown beside it until the text changes. */
  setError(message: string): void;
}

export interface ProjectFieldOptions {
  value: string;
  folders: readonly string[];
  /** Told of each edit; left out when the caller reads `value()` when it needs it. */
  onChange?: (text: string) => void;
}

export function mountProjectField(opts: ProjectFieldOptions): ProjectField {
  const root = el("div", "project-field");
  const line = el("div", "project-line");
  const input = el("input");
  input.maxLength = MAX_PROJECT_NAME + 20;
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Project name");
  const use = el("button", "small caps", "Use this name");
  use.type = "button";
  const error = el("p", "field-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  line.append(input, use);
  root.append(line, error);

  let folders = [...opts.folders];
  let refused = "";
  /** What "Use this name" fills in now; null while it is not offered. */
  let offer: string | null = null;

  const show = (): void => {
    const view = fieldView(input.value, folders, refused);
    offer = view.offer;
    error.textContent = view.error;
    error.hidden = view.error === "";
    input.placeholder = view.placeholder;
    use.hidden = offer === null;
    use.title = offer === null ? "" : `Fill in ${offer}`;
    use.setAttribute("aria-label", offer === null ? "Use this name" : `Use this name: ${offer}`);
  };

  input.value = opts.value;
  input.addEventListener("input", () => {
    refused = "";
    show();
    opts.onChange?.(input.value);
  });
  use.addEventListener("click", () => {
    if (offer === null) return;
    input.value = offer;
    refused = "";
    show();
    opts.onChange?.(input.value);
    input.focus();
  });
  show();
  return {
    root,
    value: () => input.value,
    set(text: string): void {
      input.value = text;
      refused = "";
      show();
    },
    setFolders(next: readonly string[]): void {
      folders = [...next];
      show();
    },
    setError(message: string): void {
      refused = message;
      show();
    },
  };
}
