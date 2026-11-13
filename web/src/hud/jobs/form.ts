// The "New job" form: a resident, a room (any but the Hall, the resident's
// own first), the brief, an optional title and "careful". The daemon checks
// it; its refusal shows beside the form.

import type { JobLimits, NewJob, Started } from "../../net/job-types";
import type { JobsApi } from "../../net/jobs-api";
import { hostAgentId, hostRoom } from "../../net/plan";
import type { Agent, Plan, Room } from "../../net/types";
import { el, setText } from "../dom";
import { button, fieldRow, statusLine } from "../settings/fields";

export interface JobFields {
  agent: string;
  /** Empty for the default, the resident's first room: then the daemon picks. */
  room: string;
  brief: string;
  title: string;
  careful: boolean;
}

/** The residents a job can go to: every agent but the host. */
export function residentsOf(plan: Plan): Agent[] {
  const host = hostAgentId(plan);
  return plan.agents.filter((a) => a.id !== host);
}

/**
 * The rooms a job for `agent` can go to: every room but the Hall, the
 * agent's own first (in plan order), then the others.
 */
export function roomChoices(plan: Plan, agent: string): { own: Room[]; others: Room[] } {
  const hall = hostRoom(plan)?.id;
  const open = plan.rooms.filter((r) => r.id !== hall);
  return { own: open.filter((r) => r.agent === agent), others: open.filter((r) => r.agent !== agent) };
}

/** The body of `POST /api/jobs`: text trimmed, empty optional fields left out. The brief goes as typed, so the daemon judges it. */
export function newJobBody(f: JobFields): NewJob {
  const body: NewJob = { agent: f.agent, brief: f.brief.trim() };
  if (f.room) body.room = f.room;
  if (f.title.trim()) body.title = f.title.trim();
  if (f.careful) body.careful = true;
  return body;
}

/** What "careful" does for this agent. */
export function carefulNote(agent: Agent | undefined): string {
  if (!agent) return "";
  return agent.heavy_model
    ? `Uses ${agent.name}'s heavier model, ${agent.heavy_model}, and thinks longer. It costs more.`
    : `${agent.name} has no heavier model, so careful only makes it think longer.`;
}

export interface JobFormOptions {
  api: JobsApi;
  plan: Plan;
  limits: JobLimits | null;
  /** Accepted: show the job, with this line. */
  done(started: Started): void;
  cancel(): void;
}

export function jobForm(o: JobFormOptions): HTMLElement {
  const residents = residentsOf(o.plan);
  const f: JobFields = { agent: residents[0]?.id ?? "", room: "", brief: "", title: "", careful: false };
  const form = el("form", "job-form");
  form.noValidate = true;

  const agent = el("select");
  for (const a of residents) agent.append(new Option(a.name, a.id));
  const room = el("select");
  const roomNote = el("p", "field-note");
  const brief = el("textarea");
  brief.rows = 5;
  brief.placeholder = "Read the engine's README and tell me how to run its tests.";
  brief.setAttribute("aria-label", "Brief");
  const title = el("input");
  title.placeholder = "Taken from the brief's first line";
  if (o.limits) {
    brief.maxLength = o.limits.brief_max;
    title.maxLength = o.limits.title_max;
  }
  const careful = el("input");
  careful.type = "checkbox";
  const carefulText = el("p", "field-note");
  const carefulRow = el("label", "check-choice");
  carefulRow.append(careful, el("span", "", "Careful"));

  const refusal = el("div", "job-refusal");
  refusal.setAttribute("role", "alert");
  const start = button("Start job", "primary");
  start.type = "submit";
  const back = button("Cancel");
  const actions = el("div", "row-actions");
  actions.append(start, back);

  const pickAgent = (): void => {
    f.agent = agent.value;
    const { own, others } = roomChoices(o.plan, f.agent);
    const name = residents.find((a) => a.id === f.agent)?.name ?? f.agent;
    // The first choice is the default: it sends no room, and the daemon picks the resident's first.
    const first = new Option(own[0] ? own[0].name : "No room", "");
    const group = (label: string, rooms: Room[], skip: number): HTMLOptGroupElement => {
      const g = el("optgroup");
      g.label = label;
      g.append(...(skip ? [first] : []), ...rooms.slice(skip).map((r) => new Option(r.name, r.id)));
      return g;
    };
    room.replaceChildren(group(`${name}'s rooms`, own, 1), group("Other rooms", others, 0));
    room.value = "";
    f.room = "";
    setText(roomNote, own.length === 0 ? `${name} has no room of its own; left as it is, it works without one.` : "Any room but the Hall. Another resident's room is lent for the job.");
    setText(carefulText, carefulNote(residents.find((a) => a.id === f.agent)));
  };
  agent.addEventListener("change", pickAgent);
  room.addEventListener("change", () => (f.room = room.value));
  brief.addEventListener("input", () => (f.brief = brief.value));
  title.addEventListener("input", () => (f.title = title.value));
  careful.addEventListener("change", () => (f.careful = careful.checked));
  back.addEventListener("click", () => o.cancel());
  pickAgent();

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    start.disabled = true;
    refusal.replaceChildren();
    void o.api.start(newJobBody(f)).then((r) => {
      start.disabled = false;
      if (r.ok) o.done(r.value);
      else refusal.replaceChildren(statusLine("bad", r.message));
    });
  });

  const where = el("div", "two-up");
  where.append(fieldRow("Resident", agent), fieldRow("Room", room));
  where.lastElementChild?.append(roomNote);
  const carefulField = el("div", "field");
  carefulField.append(carefulRow, carefulText);
  form.append(
    where,
    fieldRow("Brief", brief, { note: "What to do, in plain words. The resident sees only this and its room's project folder." }),
    fieldRow("Title", title, { note: "Optional: a short name for the job in this list." }),
    carefulField,
    refusal,
    actions,
  );
  return form;
}
