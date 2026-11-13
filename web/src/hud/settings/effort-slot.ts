// A thinking level bound to one draft field and to the model it is for. The
// model picker calls `follow` when the model changes: a level the new model
// does not take is dropped back to one it does, and the control says so.

import type { SettingsContext } from "./context";
import { mountEffort } from "./effort-control";
import { droppedWords, fallbackLevel, levelsFor } from "./effort";

export interface EffortSlot {
  root: HTMLElement;
  /** The model this level is for changed. */
  follow(model: string): void;
}

export function effortSlot(ctx: SettingsContext, field: string, label: string, model: string): EffortSlot {
  let current = model;
  let listing: Awaited<ReturnType<SettingsContext["models"]>> = null;
  const control = mountEffort(label, ctx.errorFor(field), (level) => {
    ctx.edit(field, level);
    show(null);
  });
  const levels = (): readonly string[] => levelsFor(current, listing, ctx.store.get().plan);
  const show = (said: string | null): void => control.show(levels(), ctx.draft[field] ?? "", said);
  show(null);
  void ctx.models().then((l) => {
    listing = l;
    show(null);
  });
  return {
    root: control.root,
    follow(next) {
      current = next;
      const before = ctx.draft[field] ?? "";
      const after = fallbackLevel(levels(), before);
      if (after !== null && after !== before) ctx.edit(field, after);
      show(droppedWords(next, before, after));
    },
  };
}
