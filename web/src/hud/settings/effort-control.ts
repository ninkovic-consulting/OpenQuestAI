// A thinking level as a row of choices that offers only the levels the model
// takes, and says so when a model change moved the level. It shows nothing for
// a model that takes none, unless the daemon refused its level.

import { el } from "../dom";
import { segmented } from "./fields";

export interface EffortControl {
  root: HTMLElement;
  /** Show these levels with this one chosen; `said` is the line to show under them. */
  show(levels: readonly string[], value: string, said?: string | null): void;
}

export function mountEffort(label: string, error: string | undefined, onChange: (level: string) => void): EffortControl {
  const root = el("div", "effort");
  root.hidden = true;
  const caption = el("span", "caps effort-label", label);
  const said = el("p", "field-note effort-said");
  said.setAttribute("role", "status");
  const wrong = el("p", "field-error", error ?? "");
  wrong.setAttribute("role", "alert");
  wrong.hidden = !error;
  return {
    root,
    show(levels, value, line = null) {
      root.hidden = levels.length === 0 && !error;
      if (levels.length === 0) return root.replaceChildren(wrong);
      const choices = segmented(
        label,
        levels.map((l) => ({ value: l, label: l })),
        value,
        onChange,
      );
      said.textContent = line ?? "";
      root.replaceChildren(caption, choices, said, wrong);
    },
  };
}
