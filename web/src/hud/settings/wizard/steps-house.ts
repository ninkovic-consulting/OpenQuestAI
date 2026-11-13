// The wizard's last steps: the assistant's name, a room with project folders, and the summary.

import { OWNER_LIMITS, OWNER_PARTS, type Owner, type OwnerPart } from "../../../net/owner";
import { projectProblem } from "../../../net/project-name";
import type { Room } from "../../../net/types";
import { PROJECT_NOTE, toolsNote } from "../../build-form";
import { el } from "../../dom";
import { mountFolderList } from "../../pickers/folder-list";
import { mountModelPicker, OWN_MODEL } from "../../pickers/model-picker";
import { mountProjectField } from "../../pickers/project-field";
import { mountToolToggles } from "../../pickers/tool-toggles";
import { fieldRow } from "../fields";
import { isHostRoom, roomEditFrom, roomPatch } from "../room-edit";
import { aboutOutcome, summary } from "./flow";
import type { StepView, WizardEnv } from "./step";

export function nameStep(env: WizardEnv): StepView {
  const before = env.settings.assistant.name;
  const input = el("input");
  input.maxLength = 40;
  input.value = before;
  input.autocomplete = "off";
  const error = el("p", "field-error");
  error.hidden = true;
  const row = fieldRow("Name", input, { note: "The host agent, who runs the Hall, carries this name too. It applies at once." });
  row.append(error);
  return {
    heading: "Its name",
    lead: "What should the assistant be called?",
    body: row,
    finish: async () => {
      const name = input.value.trim();
      if (name === before) return { status: "done", text: `Kept the name ${before}.` };
      const r = await env.api.patchSettings({ assistant: { name } });
      if (r.ok) return { status: "done", text: `Named ${r.value.settings.assistant.name}.` };
      error.textContent = r.errors.find((e) => e.field === "assistant.name")?.message ?? r.message;
      error.hidden = false;
      return null;
    },
  };
}

const QUESTIONS: Record<OwnerPart, { label: string; placeholder: string }> = {
  name: { label: "What should I call you?", placeholder: "Your name, or what you like to be called" },
  business: { label: "What business are we running?", placeholder: "Its name and what it does, in your own words" },
  notes: { label: "Anything else I should know? (optional)", placeholder: "How you like to work, who is who, what matters this year" },
};

export function aboutStep(env: WizardEnv): StepView {
  const before = env.settings.owner;
  const body = el("div", "wizard-about");
  const controls = new Map<OwnerPart, { input: HTMLInputElement | HTMLTextAreaElement; error: HTMLElement }>();
  for (const part of OWNER_PARTS) {
    const input = part === "name" ? el("input") : el("textarea");
    input.maxLength = OWNER_LIMITS[part];
    input.placeholder = QUESTIONS[part].placeholder;
    input.value = before[part];
    if (input instanceof HTMLTextAreaElement) input.rows = part === "business" ? 3 : 2;
    else input.autocomplete = "off";
    const row = fieldRow(QUESTIONS[part].label, input);
    const error = row.querySelector<HTMLElement>(".field-error") ?? el("p", "field-error");
    controls.set(part, { input, error });
    body.append(row);
  }
  body.append(el("p", "field-note", "I keep this in mind in every conversation, and so do the other agents at work. Change it any time in Settings, Assistant, or just tell me."));
  return {
    heading: "About you",
    lead: "A few words, so I know who I work for. Everything here is optional.",
    body,
    finish: async () => {
      const now: Owner = { name: "", business: "", notes: "" };
      const changes: Partial<Owner> = {};
      for (const part of OWNER_PARTS) {
        const value = (controls.get(part)?.input.value ?? "").trim();
        now[part] = value;
        if (value !== before[part]) changes[part] = value;
      }
      if (Object.keys(changes).length === 0) return aboutOutcome(now, false);
      const r = await env.api.patchSettings({ owner: changes });
      if (r.ok) return aboutOutcome(r.value.settings.owner, true);
      for (const [part, c] of controls) {
        const message = r.errors.find((e) => e.field === `owner.${part}`)?.message;
        c.error.textContent = message ?? "";
        c.error.hidden = !message;
      }
      if (!r.errors.some((e) => e.field.startsWith("owner."))) {
        const first = controls.get("name");
        if (first) {
          first.error.textContent = r.message;
          first.error.hidden = false;
        }
      }
      return null;
    },
  };
}

export function roomStep(env: WizardEnv): StepView {
  const plan = env.store.get().plan;
  const rooms = plan ? plan.rooms.filter((r) => !isHostRoom(plan, r)) : [];
  const body = el("div", "wizard-room");
  let room: Room | undefined = rooms.find((r) => r.folders.length === 0) ?? rooms[0];
  let model: string | null = null;
  let touched = false;
  const error = el("p", "field-error");
  error.hidden = true;

  const select = el("select");
  select.append(
    ...rooms.map((r) => {
      const option = el("option", "", `${r.name} · ${plan?.agents.find((a) => a.id === r.agent)?.name ?? r.agent}`);
      option.value = r.id;
      return option;
    }),
  );
  if (room) select.value = room.id;
  const tools = mountToolToggles(env.propose, toolsNote, () => (touched = true));
  const project = mountProjectField({ value: room?.project ?? "", folders: room?.folders ?? [] });
  const folders = mountFolderList({
    api: env.api,
    native: env.native,
    folders: room?.folders ?? [],
    max: plan?.max_room_folders ?? 1,
    label: "Project folders",
    onChange: (list) => {
      project.setFolders(list);
      tools.setFolders(list);
    },
  });
  const showRoom = (): void => {
    project.set(room?.project ?? "");
    project.setFolders(room?.folders ?? []);
    folders.set(room?.folders ?? []);
    touched = false;
    tools.setFolders(room?.folders ?? [], room?.tools.map((t) => t.id));
  };
  select.addEventListener("change", () => {
    room = rooms.find((r) => r.id === select.value);
    showRoom();
  });
  showRoom();
  const models = mountModelPicker({ source: env.models, value: "", own: { label: OWN_MODEL, note: "The room uses its agent's model." }, onChange: (v) => (model = v) });
  // Only a model picked here is sent; the room keeps its own otherwise.
  body.append(fieldRow("Room", select), fieldRow("Project name", project.root, { note: PROJECT_NOTE }), fieldRow("Project folders", folders.root), tools.root, fieldRow("Model (optional)", models.root), error);

  return {
    heading: "A project room",
    lead: "Give one room a project name and project folders, and the agent who runs it works there. Optional; rooms can be changed any time in Settings, Rooms.",
    body,
    finish: async () => {
      if (!plan || !room) return { status: "skipped", text: "No project folders attached." };
      if (projectProblem(project.value()) !== null) return null;
      const before = roomEditFrom(plan, room);
      const edit = { ...before, project: project.value(), folders: folders.value(), model: model ?? before.model };
      const patch = roomPatch(before, edit, tools.picks(), touched, false);
      if (patch.folders === undefined && patch.project === undefined) return { status: "skipped", text: "No project folders attached." };
      const r = await env.api.patchRoom(room.id, patch);
      if (r.ok) return { status: "done", text: `${room.name}: ${[edit.project.trim(), ...(patch.folders ?? [])].filter((t) => t !== "").join(", ")}.` };
      const refusal = r.errors.find((e) => e.field === "folders")?.message;
      const named = r.errors.find((e) => e.field === "project")?.message;
      folders.setError(refusal ?? "");
      project.setError(named ?? "");
      error.textContent = r.message;
      error.hidden = refusal !== undefined || named !== undefined;
      return null;
    },
  };
}

export function doneStep(env: WizardEnv): StepView {
  const list = el("ul", "wizard-summary");
  for (const item of summary(env.flow)) {
    const li = el("li", `is-${item.outcome.status}`);
    li.append(el("span", item.outcome.status === "done" ? "dot" : "dot hollow"), el("span", "title caps", item.title), el("span", "text", item.outcome.text));
    list.append(li);
  }
  const skipped = summary(env.flow).some((i) => i.outcome.status === "skipped");
  return {
    heading: "Ready",
    lead: skipped ? "Here is what is set up. What was skipped can be done in Settings (⌘ ,) at any time." : "Everything is set up.",
    body: list,
    next: "Finish",
    finish: async () => {
      const r = await env.api.patchSettings({ setup: { completed: true } });
      return r.ok ? { status: "done", text: "" } : null;
    },
  };
}
