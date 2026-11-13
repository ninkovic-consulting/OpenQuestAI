// Any other Hugging Face model, typed by hand: it becomes the local model and
// starts downloading, and then shows among the models with its progress.

import { el } from "../dom";
import { button, fieldRow } from "./fields";

/** `go` makes the repo the local model and starts its download; answers why not, or null. */
export function customForm(go: (repo: string) => Promise<string | null>): HTMLElement {
  const root = el("div", "lm-custom");
  const input = el("input");
  input.placeholder = "mlx-community/…";
  input.autocomplete = "off";
  input.spellcheck = false;
  const said = el("p", "field-error");
  said.hidden = true;
  const start = button("Use and download");
  start.addEventListener("click", () => {
    start.disabled = true;
    said.hidden = true;
    void go(input.value.trim()).then((problem) => {
      start.disabled = false;
      said.hidden = problem === null;
      said.textContent = problem ?? "";
      if (problem === null) input.value = "";
    });
  });
  const actions = el("div", "row-actions");
  actions.append(start);
  root.append(
    fieldRow("Another Hugging Face model", input, {
      note: "Any repo in MLX format, like mlx-community/Qwen3-8B-4bit. It becomes the local model now; offline mode needs it downloaded first.",
    }),
    actions,
    said,
  );
  return root;
}
