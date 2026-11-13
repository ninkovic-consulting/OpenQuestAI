// The field on a room's card: "Give Tink a job here". It starts a job for the
// room's agent in this room through the jobs API and shows the daemon's
// refusal beside the field. The result comes back through the host.

import type { JobsApi } from "../../net/jobs-api";
import type { Store } from "../../net/store";
import { el, setText } from "../dom";
import { newJobBody } from "../jobs/form";

export interface BriefOptions {
  agent: string;
  agentName: string;
  room: string;
  roomName: string;
  /** What "careful" does for this agent, in a few words. */
  careful: string;
  /** The host's name: the report comes back through it. */
  host: string;
}

export function briefField(api: JobsApi, store: Store, o: BriefOptions): HTMLFormElement {
  const form = el("form", "card-brief");
  form.noValidate = true;
  const id = `brief-${o.room}`;
  const label = el("label", "caps kicker", `Give ${o.agentName} a job here`);
  label.htmlFor = id;
  const brief = el("textarea");
  brief.id = id;
  brief.rows = 3;
  brief.placeholder = `What should ${o.agentName} do in the ${o.roomName}?`;
  const careful = el("input");
  careful.type = "checkbox";
  const carefulRow = el("label", "card-careful");
  carefulRow.append(careful, el("span", "", `Careful · ${o.careful}`));
  const send = el("button", "card-send caps", "Give job");
  send.type = "submit";
  const refusal = el("p", "card-refusal");
  refusal.setAttribute("role", "alert");
  const said = el("p", "card-said");
  said.setAttribute("aria-live", "polite");
  const bottom = el("div", "card-brief-row");
  bottom.append(carefulRow, send);
  form.append(label, brief, bottom, refusal, said, el("p", "note", `The result comes back through ${o.host}, in the chat.`));

  brief.addEventListener("input", () => {
    setText(refusal, "");
    setText(said, "");
  });
  brief.addEventListener("keydown", (ev) => {
    if (ev.isComposing) return;
    if (ev.key === "Escape") brief.blur();
    else if (ev.key === "Enter" && !ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      ev.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    send.disabled = true;
    setText(refusal, "");
    setText(said, "");
    void api.start(newJobBody({ agent: o.agent, room: o.room, brief: brief.value, title: "", careful: careful.checked })).then((r) => {
      send.disabled = false;
      if (!r.ok) {
        setText(refusal, r.message);
        return refusal.scrollIntoView({ block: "nearest" });
      }
      brief.value = "";
      careful.checked = false;
      setText(said, r.value.started ? `${o.agentName} is on it.` : `Waiting its turn: it starts when ${o.agentName} and a place are free.`);
      said.scrollIntoView({ block: "nearest" });
      // Shown at once unless the daemon's own announcement of the job got here first.
      if (!store.get().jobs[r.value.job.id]) store.dispatch({ kind: "event", event: { type: "job.changed", ts: Date.now() / 1000, data: r.value.job } });
    });
  });
  return form;
}
