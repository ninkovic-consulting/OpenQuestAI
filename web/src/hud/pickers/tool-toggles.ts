// The tools proposed for a project folder, as toggles. Shared by the add-room
// form, the Rooms group and the wizard's room step.

import type { ProposeResult } from "../../net/types";
import { el } from "../dom";
import { fromProposal, toggle, type ToolPicks } from "../room-form";

const PROPOSE_DELAY_MS = 350;

export interface ToolToggles {
  root: HTMLFieldSetElement;
  /** Ask for the folder's tools after a pause; `on` are the ids switched on at first (a room's tools). */
  setProject(folder: string, on?: readonly string[]): void;
  picks(): ToolPicks | null;
}

export function mountToolToggles(
  propose: (folder: string) => Promise<ProposeResult>,
  note: () => string,
  onPick: () => void = () => {},
): ToolToggles {
  const root = el("fieldset", "tools");
  const legend = el("legend", "caps", "Tools for this project");
  const list = el("div", "tool-list");
  const message = el("p", "tool-note");
  root.append(legend, list, message);
  root.hidden = true;
  let picks: ToolPicks | null = null;
  let folder = "";
  let asked = 0;
  let timer = 0;

  const render = (text?: string): void => {
    root.hidden = folder === "";
    if (text !== undefined || !picks) {
      list.replaceChildren();
      message.textContent = text ?? "";
      return;
    }
    if (picks.tools.length === 0) {
      list.replaceChildren();
      message.textContent = "No project tools recognised here; the room uses its agent's tools.";
      return;
    }
    const current = picks;
    list.replaceChildren(
      ...current.tools.map((tool) => {
        const on = current.on.has(tool.id);
        const button = el("button", `tool-toggle${tool.available ? "" : " is-unavailable"}`);
        button.type = "button";
        button.setAttribute("aria-pressed", String(on));
        button.append(el("span", on ? "dot" : "dot hollow"), el("span", "", tool.title));
        if (!tool.available) button.append(el("span", "tag", "not installed"));
        button.addEventListener("click", () => {
          if (picks) picks = toggle(picks, tool.id);
          render();
          onPick();
        });
        return button;
      }),
    );
    message.textContent = note();
  };

  const ask = async (on: readonly string[] | undefined): Promise<void> => {
    const mine = ++asked;
    if (!folder) {
      picks = null;
      render();
      return;
    }
    if (picks?.project === folder) return;
    picks = null;
    render("Looking at the folder…");
    const result = await propose(folder);
    if (mine !== asked) return; // a newer folder was typed meanwhile
    if (result.ok) {
      picks = fromProposal(folder, result.tools, on);
      render();
    } else {
      render(result.message);
    }
  };

  return {
    root,
    setProject(next: string, on?: readonly string[]): void {
      window.clearTimeout(timer);
      folder = next.trim();
      if (on !== undefined) picks = null;
      asked += 1;
      if (!folder) {
        picks = null;
        render();
        return;
      }
      timer = window.setTimeout(() => void ask(on), on === undefined ? PROPOSE_DELAY_MS : 0);
    },
    picks: () => (picks && picks.project === folder ? picks : null),
  };
}
