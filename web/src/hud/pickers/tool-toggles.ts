// The tools proposed for a room's project folders, as toggles. Shared by the
// add-room form, the Rooms group and the wizard's room step. Each folder is
// asked about once; the room is offered the union.

import type { ProposeResult, ToolRef } from "../../net/types";
import { el } from "../dom";
import { sameFolderSet } from "../folders";
import { carriedOn, fromProposal, toggle, unionTools, type ToolPicks } from "../room-form";

export interface ToolToggles {
  root: HTMLFieldSetElement;
  /** Ask for the folders' tools; `on` are the ids switched on at first (a room's tools). */
  setFolders(folders: readonly string[], on?: readonly string[]): void;
  picks(): ToolPicks | null;
}

export function mountToolToggles(
  propose: (folder: string) => Promise<ProposeResult>,
  note: () => string,
  onPick: () => void = () => {},
): ToolToggles {
  const root = el("fieldset", "tools");
  const legend = el("legend", "caps", "Tools for these folders");
  const list = el("div", "tool-list");
  const message = el("p", "tool-note");
  root.append(legend, list, message);
  root.hidden = true;
  let picks: ToolPicks | null = null;
  let folders: readonly string[] = [];
  let asked = 0;
  const known = new Map<string, Promise<ProposeResult>>();

  const render = (text?: string): void => {
    root.hidden = folders.length === 0;
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

  /** A folder's proposal, asked once; a refusal is asked again next time. */
  const proposal = (folder: string): Promise<ProposeResult> => {
    let answer = known.get(folder);
    if (!answer) {
      answer = propose(folder);
      known.set(folder, answer);
      void answer.then((r) => {
        if (!r.ok) known.delete(folder);
      });
    }
    return answer;
  };

  const ask = async (on: readonly string[] | undefined): Promise<void> => {
    const mine = ++asked;
    const previous = picks;
    const wanted = folders;
    picks = null;
    render(wanted.length === 1 ? "Looking at the folder…" : "Looking at the folders…");
    const results = await Promise.all(wanted.map(proposal));
    if (mine !== asked) return; // the folders changed meanwhile
    const tools: ToolRef[] = unionTools(results.flatMap((r) => (r.ok ? [r.tools] : [])));
    const failure = results.find((r) => !r.ok);
    if (tools.length === 0 && failure && !failure.ok) {
      render(failure.message);
      return;
    }
    picks = fromProposal(wanted, tools, on ?? carriedOn(previous, tools));
    render();
  };

  return {
    root,
    setFolders(next: readonly string[], on?: readonly string[]): void {
      const wanted = next.map((f) => f.trim()).filter((f) => f !== "");
      if (on === undefined && picks && sameFolderSet(picks.folders, wanted)) return;
      folders = wanted;
      asked += 1;
      if (wanted.length === 0) {
        picks = null;
        render();
        return;
      }
      void ask(on);
    },
    picks: () => (picks && sameFolderSet(picks.folders, folders) ? picks : null),
  };
}
