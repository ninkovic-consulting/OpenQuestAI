// Display: how much of this Mac's graphics the 3D house uses. The choices
// belong to this window and act at once; they are kept in the page's own
// storage (scene/display-prefs.ts), not in the assistant's settings.

import { displayPrefs } from "../../../scene/display-prefs";
import { LEVELS, QUALITIES, type Quality } from "../../../scene/quality";
import { el, setText } from "../../dom";
import type { Group } from "../context";
import { block, fieldRow, note, segmented } from "../fields";

export const displayGroup: Group = {
  id: "display",
  title: "Display",
  blurb: "How much of this Mac's graphics the house uses. Changes apply at once and stay with this window.",
  prefixes: [],
  render() {
    const prefs = displayPrefs();
    const root = el("div", "group-body");
    const summary = note(LEVELS[prefs.get().quality].summary);
    const quality = segmented(
      "Quality",
      QUALITIES.map((q) => ({ value: q, label: LEVELS[q].label })),
      prefs.get().quality,
      (value) => {
        const q = value as Quality;
        prefs.set({ quality: q });
        setText(summary, LEVELS[q].summary);
      },
    );
    const stepBack = checkbox("Step back while the assistant is working on this Mac", prefs.get().stepBack, (on) => prefs.set({ stepBack: on }));
    const readout = checkbox("Show the frame readout over the house", prefs.get().readout, (on) => prefs.set({ readout: on }));
    root.append(
      block(
        "The house",
        fieldRow("Quality", quality),
        summary,
        stepBack,
        note("While the local model answers or the voice speaks, the house draws less often and less sharply, so they get the graphics chip; it eases back afterwards."),
        readout,
        note("Frames a second, frame time, resolution and draw calls, in the scene's corner. Add ?stats=1 to the address for the same."),
      ),
    );
    return root;
  },
};

function checkbox(label: string, checked: boolean, onChange: (on: boolean) => void): HTMLElement {
  const choice = el("label", "check-choice");
  const input = el("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  choice.append(input, el("span", "", label));
  return choice;
}
