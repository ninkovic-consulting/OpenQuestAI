// Delete all data, in Settings, Reset: what goes and what stays, said first,
// then a two-step confirm like Quit's. The daemon deletes and answers; then
// the Mac app is asked to finish (login item off, the window's stored data
// and its own preferences gone) and quit. A plain browser has no app to ask,
// so the page says the assistant has stopped and the tab can be closed.
//
// `DeleteAllFlow` holds the steps and is tested on its own; `deleteAllBlock`
// draws it.

import type { Result } from "../../net/settings-api";
import type { DeleteAllAnswer, DeleteAllPreview } from "../../net/settings-types";
import { el } from "../dom";
import { button, statusLine, type Tone } from "./fields";
import { formatBytes } from "./format";

export type DeletePhase = "idle" | "asking" | "running" | "failed" | "done";

export interface DeleteAllDeps {
  deleteAll(models: boolean): Promise<Result<DeleteAllAnswer>>;
  /** The Mac app's last step, given what to tell the owner; null in a plain browser. */
  finish: ((summary: string) => Promise<void>) | null;
}

export interface DeleteView {
  phase: DeletePhase;
  /** Shown with Delete everything and Keep it while asking and running. */
  question: string | null;
  /** The first button, Delete all data. */
  canStart: boolean;
  canConfirm: boolean;
  canKeep: boolean;
  tone: Tone;
  message: string;
  /** What stayed in the data folder, one line each. */
  left: string[];
}

export const STOPPED_IN_BROWSER = "The assistant has stopped. You can close this tab.";
export const CLOSING_APP = "The app closes now.";
export const APP_STAYED = "The app did not close by itself. Quit it from its menu bar item, or press Cmd+Q.";

/** The question the first press shows. */
export function deleteQuestion(models: boolean): string {
  const what = models
    ? "the data folder, the API key and the phone's bot token, and the downloaded models"
    : "the data folder, and the API key and the phone's bot token";
  return `Delete ${what}? There is no backup, so this cannot be undone.`;
}

/** The lines for what stayed in the data folder and outside it. */
export function leftLines(answer: DeleteAllAnswer): string[] {
  return [
    ...answer.left.map((x) => `${x.name}: ${x.why}`),
    ...answer.elsewhere.map((path) => `${path}: kept outside the data folder by your settings.`),
    ...(answer.models?.left ?? []).map((m) => `${m.repo}: ${m.why}`),
  ];
}

export class DeleteAllFlow {
  private phase: DeletePhase = "idle";
  private models = false;
  private tone: Tone = "idle";
  private message = "";
  private left: string[] = [];

  constructor(
    private readonly deps: DeleteAllDeps,
    private readonly changed: (view: DeleteView) => void = () => {},
  ) {}

  view(): DeleteView {
    const asking = this.phase === "asking" || this.phase === "running";
    return {
      phase: this.phase,
      question: asking ? deleteQuestion(this.models) : null,
      canStart: this.phase === "idle" || this.phase === "failed",
      canConfirm: this.phase === "asking",
      canKeep: this.phase === "asking",
      tone: this.tone,
      message: this.message,
      left: [...this.left],
    };
  }

  /** The first press: show the question. */
  ask(models: boolean): void {
    if (this.phase !== "idle" && this.phase !== "failed") return;
    this.models = models;
    this.set("asking", "idle", "");
  }

  /** Keep it: back as it was, nothing done. */
  keep(): void {
    if (this.phase === "asking") this.set("idle", "idle", "");
  }

  /** Delete everything: the daemon deletes and answers, then the app finishes. */
  async confirm(): Promise<void> {
    if (this.phase !== "asking") return;
    this.set("running", "warn", "Deleting…");
    const r = await this.deps.deleteAll(this.models);
    if (!r.ok) {
      this.set("failed", "bad", `Delete all data did not finish. ${r.message}`);
      return;
    }
    const answer = r.value;
    this.left = leftLines(answer);
    const tone: Tone = answer.keychain.ok && this.left.length === 0 ? "ok" : "warn";
    const finish = this.deps.finish;
    if (finish === null) {
      this.set("done", tone, `${answer.message} ${STOPPED_IN_BROWSER}`);
      return;
    }
    this.set("done", tone, `${answer.message} ${CLOSING_APP}`);
    const summary = [answer.message, ...this.left].join("\n");
    try {
      await finish(summary);
    } catch {
      this.set("done", tone, `${answer.message} ${APP_STAYED}`);
    }
  }

  private set(phase: DeletePhase, tone: Tone, message: string): void {
    this.phase = phase;
    this.tone = tone;
    this.message = message;
    this.changed(this.view());
  }
}

export interface DeleteAllBlockDeps extends DeleteAllDeps {
  /** The data folder's real path, from the settings answer. */
  home: string;
  preview(): Promise<Result<DeleteAllPreview>>;
}

/** The "Delete all data" block for the Reset group. */
export function deleteAllBlock(deps: DeleteAllBlockDeps): HTMLElement {
  const root = el("section", "reset-card is-delete-all");
  const folder = el("code", "delete-home", deps.home);
  const gone = el("ul", "delete-list");
  const folderLine = el("li");
  folderLine.append("The data folder, with everything the app made in it, the backups too: ", folder);
  gone.append(
    folderLine,
    el("li", "", "The API key and the phone's bot token, in the Keychain."),
    el("li", "", "The LaunchAgent that starts it at login, if you set one up with vision install."),
  );
  const models = el("input");
  models.type = "checkbox";
  models.disabled = true;
  let modelsOffered = false;
  let phase: DeletePhase = "idle";
  const lockModels = (): void => {
    models.disabled = !modelsOffered || phase !== "idle" && phase !== "failed";
  };
  const modelsWords = el("span", "", "Also delete the downloaded speech and local models (checking their size…)");
  const modelsChoice = el("label", "check-choice");
  modelsChoice.append(models, modelsWords);
  void deps.preview().then((r) => {
    if (!r.ok) {
      modelsWords.textContent = `Also delete the downloaded speech and local models (their size is not known: ${r.message})`;
      modelsOffered = true;
      lockModels();
      return;
    }
    if (r.value.models.length === 0) {
      modelsWords.textContent = "No speech or local models of this app are downloaded, so there are none to delete.";
      return;
    }
    const count = r.value.models.length;
    modelsWords.textContent = `Also delete the downloaded speech and local models: ${count} ${count === 1 ? "model" : "models"}, ${formatBytes(r.value.models_bytes)}`;
    modelsOffered = true;
    lockModels();
  });

  const start = button("Delete all data", "danger");
  const question = el("p", "confirm-question");
  const yes = button("Delete everything", "danger");
  const no = button("Keep it");
  const actions = el("div", "row-actions");
  actions.append(yes, no);
  const box = el("div", "confirm-box");
  box.append(question, actions);
  box.hidden = true;
  const result = el("div", "delete-result");
  result.setAttribute("role", "status");

  const draw = (v: DeleteView): void => {
    start.hidden = v.question !== null;
    start.disabled = !v.canStart;
    box.hidden = v.question === null;
    question.textContent = v.question ?? "";
    yes.disabled = !v.canConfirm;
    no.disabled = !v.canKeep;
    phase = v.phase;
    lockModels();
    const lines = v.left.map((line) => el("li", "", line));
    const list = el("ul", "delete-list");
    list.append(...lines);
    result.replaceChildren(...(v.message ? [statusLine(v.tone, v.message)] : []), ...(lines.length ? [el("p", "field-note", "Left where it is:"), list] : []));
    if (v.phase === "done") start.hidden = true;
  };
  const flow = new DeleteAllFlow(deps, draw);
  start.addEventListener("click", () => {
    flow.ask(models.checked && !models.disabled);
    no.focus();
  });
  no.addEventListener("click", () => {
    flow.keep();
    start.focus();
  });
  yes.addEventListener("click", () => void flow.confirm());

  root.append(
    el("h4", "card-title", "Delete all data"),
    el(
      "p",
      "field-note",
      "Dragging the app to the Trash removes only the app. This removes what it keeps on this Mac, for good, with no backup:",
    ),
    gone,
    modelsChoice,
    el(
      "p",
      "field-note",
      "What stays: the app itself, which you can then drag to the Trash; your project folders; anything else in the Hugging Face cache, which other tools share; and anything in the data folder the app did not make, which is listed afterwards. Then the assistant stops and the app closes.",
    ),
    start,
    box,
    result,
  );
  return root;
}
