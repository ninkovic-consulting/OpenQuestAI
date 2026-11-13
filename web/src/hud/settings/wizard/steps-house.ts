// The wizard's last steps: the assistant's name, a room with project folders, and the summary.

import type { Room } from "../../../net/types";
import { toolsNote } from "../../build-form";
import { el } from "../../dom";
import { mountFolderList } from "../../pickers/folder-list";
import { mountModelPicker, OWN_MODEL } from "../../pickers/model-picker";
import { mountToolToggles } from "../../pickers/tool-toggles";
import { fieldRow } from "../fields";
import { isHostRoom, roomEditFrom, roomPatch } from "../room-edit";
import { summary } from "./flow";
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
  const folders = mountFolderList({
    api: env.api,
    native: env.native,
    folders: room?.folders ?? [],
    max: plan?.max_room_folders ?? 1,
    label: "Project folders",
    onChange: (list) => tools.setFolders(list),
  });
  const showRoom = (): void => {
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
  body.append(fieldRow("Room", select), fieldRow("Project folders", folders.root), tools.root, fieldRow("Model (optional)", models.root), error);

  return {
    heading: "A project room",
    lead: "Give one room project folders, and the agent who runs it works there. Optional; rooms can be changed any time in Settings, Rooms.",
    body,
    finish: async () => {
      if (!plan || !room) return { status: "skipped", text: "No project folders attached." };
      const before = roomEditFrom(plan, room);
      const patch = roomPatch(before, { ...before, folders: folders.value(), model: model ?? before.model }, tools.picks(), touched, false);
      if (patch.folders === undefined) return { status: "skipped", text: "No project folders attached." };
      const r = await env.api.patchRoom(room.id, patch);
      if (r.ok) return { status: "done", text: `${room.name}: ${patch.folders.join(", ")}.` };
      const refusal = r.errors.find((e) => e.field === "folders")?.message;
      folders.setError(refusal ?? "");
      error.textContent = r.message;
      error.hidden = refusal !== undefined;
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
