import type { Backup, ResetLevel } from "../../../net/settings-types";
import { el } from "../../dom";
import { RESTART_HELP, type Group, type SettingsContext } from "../context";
import { block, confirmButton, note, statusLine } from "../fields";
import { backupWords, formatWhen } from "../format";

export const resetGroup: Group = {
  id: "reset",
  title: "Reset",
  blurb: "Put things back if something went wrong. Every reset copies what it changes into a backup first, listed below.",
  prefixes: [],
  render(ctx) {
    const root = el("div", "group-body");
    const backups = el("div", "backup-list");
    const restored = note();
    const refreshBackups = (): void => {
      const report = (text: string): void => {
        restored.textContent = text;
        refreshBackups();
      };
      void ctx.api.backups().then((r) => backups.replaceChildren(...(r.ok ? backupRows(ctx, r.value, report) : [statusLine("bad", r.message)])));
    };
    const name = ctx.settings.assistant.name;
    const removeKey = el("input");
    removeKey.type = "checkbox";
    const keyChoice = el("label", "check-choice");
    keyChoice.append(removeKey, el("span", "", "Also remove the stored API key (it is never in a backup)"));

    const level = (id: ResetLevel, title: string, text: string, button: string, extra: Partial<Parameters<typeof confirmButton>[1]> = {}): HTMLElement => {
      const card = el("section", `reset-card is-${id}`);
      card.append(
        el("h4", "card-title", title),
        el("p", "field-note", text),
        confirmButton(button, { question: `${title}? A backup is made first.`, confirm: button, danger: id === "everything", ...extra }, async () => {
          const r = await ctx.api.reset(id, id === "everything" && removeKey.checked);
          if (!r.ok) return r.message;
          refreshBackups();
          await ctx.reload({ redraw: false, discard: true });
          const after = r.value.restart ? await restartAfter(ctx) : "";
          if (id === "everything") ctx.openWizard();
          return `${r.value.message} ${after}`.trim();
        }),
      );
      return card;
    };

    root.append(
      level("settings", "Reset settings", "Every setting back to its default. Keeps the house, memory notes, conversation log and API key.", "Reset settings"),
      level("house", "Reset the house", "Rooms and agents back to the default house. Keeps settings, memory, the log and the key.", "Reset the house"),
      level("everything", "Start over", "Settings, house, memory notes, conversation log and this month's spend start fresh, then setup runs again. The key stays unless you choose otherwise.", "Start over", {
        typed: name,
        extra: keyChoice,
        question: "Start over with everything fresh? A backup is made first.",
      }),
      block("Backups", restored, backups),
    );
    refreshBackups();
    return root;
  },
};

/** Restart through the app when it can; otherwise say how. */
async function restartAfter(ctx: SettingsContext): Promise<string> {
  if (ctx.native.restartDaemon) return ctx.restart();
  return `Restart the assistant to finish. ${RESTART_HELP}`;
}

/** The backups, newest first, each with Restore; `report` hears how a restore went. */
function backupRows(ctx: SettingsContext, list: readonly Backup[], report: (text: string) => void): HTMLElement[] {
  if (list.length === 0) return [note("No backups yet.")];
  return list.map((b) => {
    const row = el("div", "backup");
    const what = el("div", "backup-what");
    what.append(el("span", "when", formatWhen(b.created_at)), el("span", "", backupWords(b.level)), el("span", "files", b.files.join(", ")));
    row.append(
      what,
      confirmButton("Restore", { question: `Put back ${b.files.join(", ")} from ${formatWhen(b.created_at)}? What is there now is backed up first.`, confirm: "Restore" }, async () => {
        const r = await ctx.api.restore(b.id);
        if (!r.ok) return r.message;
        await ctx.reload({ redraw: false, discard: true });
        const after = r.value.restart ? await restartAfter(ctx) : "";
        report(`Restored ${r.value.restored.join(", ")} from ${formatWhen(b.created_at)}. ${after}`.trim());
        return "";
      }),
    );
    return row;
  });
}
