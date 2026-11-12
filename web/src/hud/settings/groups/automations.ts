import type { Automation, AutomationList } from "../../../net/automation-types";
import { el, setText } from "../../dom";
import { countWords, resultWords, stateWords } from "../automation-edit";
import { automationForm } from "../automation-form";
import type { Group, SettingsContext } from "../context";
import { button, confirmButton, note, statusLine } from "../fields";
import { scheduleWords } from "../schedule-edit";

type Mode = { kind: "list" } | { kind: "form"; editing: Automation | null };

export const automationsGroup: Group = {
  id: "automations",
  title: "Automations",
  blurb: "Instructions the assistant carries out by itself at set times, in the Mac's local time. Changes apply at once. A step that asks first waits for your yes; if nobody answers, it is not done.",
  prefixes: [],
  render(ctx) {
    const root = el("div", "group-body automations");
    const said = note();
    let list: AutomationList | null = null;
    let mode: Mode = { kind: "list" };

    const draw = (): void => {
      if (!list) {
        root.replaceChildren(statusLine("idle", "Loading the automations…"));
        return;
      }
      if (mode.kind === "form") {
        root.replaceChildren(
          automationForm({
            ctx,
            limits: list.limits,
            editing: mode.editing,
            done: (message) => {
              mode = { kind: "list" };
              setText(said, message);
              void load();
            },
            cancel: () => {
              mode = { kind: "list" };
              draw();
            },
          }),
        );
        return;
      }
      const head = el("div", "automations-head");
      const add = button("New automation", "primary");
      add.disabled = list.automations.length >= list.limits.max_automations;
      add.addEventListener("click", () => {
        mode = { kind: "form", editing: null };
        setText(said, "");
        draw();
      });
      head.append(el("p", "field-note", `${countWords(list.automations.length, list.limits)} Times are in ${list.timezone}.`), add);
      const now = Date.now() / 1000;
      const cards = list.automations.map((a) =>
        card(ctx, a, now, {
          edit: () => {
            mode = { kind: "form", editing: a };
            setText(said, "");
            draw();
          },
          report: (message) => {
            setText(said, message);
            void load();
          },
        }),
      );
      root.replaceChildren(head, said, ...(cards.length > 0 ? cards : [el("p", "field-note empty-list", "Ask the assistant, for example: “every weekday at nine, tell me the weather”. Or create one here.")]));
    };

    const load = async (): Promise<void> => {
      const r = await ctx.automations.list();
      if (!r.ok) {
        root.replaceChildren(statusLine("bad", `The automations could not be loaded: ${r.message}`));
        return;
      }
      list = r.value;
      if (mode.kind === "list") draw();
    };

    // Follow the daemon while this group is on screen; stop once it is gone.
    const stop = ctx.store.subscribe((s, prev) => {
      if (!root.isConnected) {
        stop();
        return;
      }
      if (s.automationsRevision !== prev.automationsRevision || s.automation !== prev.automation) void load();
    });
    draw();
    void load();
    return root;
  },
};

interface CardActions {
  edit(): void;
  /** A change went through: show this line and refetch. */
  report(message: string): void;
}

function card(ctx: SettingsContext, a: Automation, now: number, act: CardActions): HTMLElement {
  const node = el("section", `automation-card${a.paused ? " is-paused" : ""}${a.running ? " is-running" : ""}`);
  const head = el("div", "card-head");
  head.append(el("h4", "card-title", a.name), el("span", "tag", a.speak ? "spoken" : "shown only"));
  const state = stateWords(a, now);
  const last = resultWords(a.results.at(-1));
  const facts = el("div", "automation-facts");
  facts.append(el("p", "schedule-words", scheduleWords(a.schedule)), statusLine(state.tone, state.text));
  if (last) facts.append(statusLine(last.tone, `Last: ${last.text}`));
  else facts.append(el("p", "field-note", "Has not run yet."));

  const failed = note();
  const attempt = async (run: () => Promise<{ ok: boolean; message?: string }>, done: string): Promise<void> => {
    const r = await run();
    if (r.ok) act.report(done);
    else setText(failed, r.message ?? "That did not work.");
  };
  const edit = button("Edit");
  edit.addEventListener("click", act.edit);
  const pause = button(a.paused ? "Resume" : "Pause");
  pause.addEventListener("click", () => {
    pause.disabled = true;
    void attempt(() => ctx.automations.update(a.id, { paused: !a.paused }), a.paused ? `Resumed ${a.name}.` : `Paused ${a.name}; it will not run until resumed.`);
  });
  const run = button("Run now");
  run.disabled = a.running;
  run.addEventListener("click", () => {
    run.disabled = true;
    void attempt(() => ctx.automations.run(a.id), `${a.name} runs now, or as soon as the assistant is free.`);
  });
  const remove = confirmButton("Delete", { question: `Delete ${a.name} and its results? This cannot be undone.`, confirm: "Delete", danger: true }, async () => {
    const r = await ctx.automations.remove(a.id);
    if (!r.ok) return r.message;
    act.report(`Deleted ${a.name}.`);
    return "";
  });
  const actions = el("div", "row-actions");
  actions.append(edit, pause, run, remove);
  node.append(head, el("p", "instruction-text", a.instruction), facts, actions, failed);
  return node;
}
