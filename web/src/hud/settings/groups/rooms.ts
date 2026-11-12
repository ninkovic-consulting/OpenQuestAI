import type { Plan, Room } from "../../../net/types";
import { toolsNote } from "../../build-form";
import { el } from "../../dom";
import { mountFolderPicker } from "../../pickers/folder-picker";
import { mountModelPicker, OWN_MODEL } from "../../pickers/model-picker";
import { mountToolToggles } from "../../pickers/tool-toggles";
import type { Group, SettingsContext } from "../context";
import { button, confirmButton, fieldRow, note } from "../fields";
import { agentsFor, isHostRoom, roomEditFrom, roomPatch, type RoomEdit } from "../room-edit";

export const roomsGroup: Group = {
  id: "rooms",
  title: "Rooms",
  blurb: "Each room's name, who runs it, its project folder, model and tools. Saved per room; changes apply at once.",
  prefixes: [],
  render(ctx) {
    const root = el("div", "group-body");
    const plan = ctx.store.get().plan;
    if (!plan) {
      root.append(el("p", "field-note", "The house has not loaded yet."));
      return root;
    }
    const chosen = plan.rooms.find((r) => r.id === ctx.roomId) ?? plan.rooms[0];
    const list = el("div", "room-list");
    list.setAttribute("role", "tablist");
    list.setAttribute("aria-label", "Rooms");
    for (const room of plan.rooms) {
      const tab = el("button", "room-tab", room.name);
      tab.type = "button";
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(room === chosen));
      if (room.kind === "extra") tab.append(el("span", "tag", "added"));
      tab.addEventListener("click", () => ctx.goTo("rooms", room.id));
      list.append(tab);
    }
    root.append(list);
    if (chosen) root.append(roomEditor(ctx, plan, chosen));
    return root;
  },
};

function roomEditor(ctx: SettingsContext, plan: Plan, room: Room): HTMLElement {
  const card = el("section", "room-editor");
  const hostRoom = isHostRoom(plan, room);
  const before = roomEditFrom(plan, room);
  const edit: RoomEdit = { ...before };
  let toolsTouched = false;

  const result = note();
  const save = button("Save room", "primary");
  const revert = button("Revert");
  const dirty = (): void => {
    const changed = Object.keys(roomPatch(before, edit, tools.picks(), toolsTouched, hostRoom)).length > 0;
    save.disabled = !changed;
    revert.disabled = !changed;
    ctx.markDirty(changed);
  };

  const head = el("div", "card-head");
  head.append(el("h4", "card-title", room.name), el("span", "tag", room.kind === "extra" ? "added room" : "the house's own room"));

  const name = el("input");
  name.maxLength = 40;
  name.value = edit.name;
  name.addEventListener("input", () => {
    edit.name = name.value;
    dirty();
  });

  let agentControl: HTMLElement;
  if (hostRoom) {
    const host = plan.agents.find((a) => a.id === room.agent)?.name ?? room.agent;
    agentControl = el("p", "fixed-value", `${host}, the host. The Hall is always the host's.`);
  } else {
    const select = el("select");
    select.append(
      ...agentsFor(plan, room).map((a) => {
        const option = el("option", "", a.name);
        option.value = a.id;
        return option;
      }),
    );
    select.value = edit.agent;
    select.addEventListener("change", () => {
      edit.agent = select.value;
      dirty();
    });
    agentControl = select;
  }

  const tools = mountToolToggles(
    (folder) => ctx.propose(folder),
    () => toolsNote(plan.assistant.name),
    () => {
      toolsTouched = true;
      dirty();
    },
  );
  const folder = mountFolderPicker({
    api: ctx.api,
    native: ctx.native,
    value: edit.project,
    label: "Project folder",
    onChange: (v) => {
      edit.project = v;
      tools.setProject(v);
      dirty();
    },
  });
  if (edit.project) tools.setProject(edit.project, room.tools.map((t) => t.id));

  const model = mountModelPicker({
    source: ctx.models,
    value: edit.model,
    own: { label: OWN_MODEL, note: "The room uses its agent's model." },
    onChange: (v) => {
      edit.model = v;
      dirty();
    },
  });

  save.addEventListener("click", () => {
    const patch = roomPatch(before, edit, tools.picks(), toolsTouched, hostRoom);
    save.disabled = true;
    result.textContent = "Saving…";
    void ctx.api.patchRoom(room.id, patch).then((r) => {
      if (r.ok) {
        ctx.markDirty(false);
        result.textContent = "Saved. The house shows it now.";
      } else {
        save.disabled = false;
        result.textContent = r.message;
      }
    });
  });
  revert.addEventListener("click", () => {
    ctx.markDirty(false);
    ctx.goTo("rooms", room.id);
  });

  const actions = el("div", "row-actions");
  actions.append(save, revert);
  card.append(
    head,
    fieldRow("Name", name),
    fieldRow("Agent", agentControl),
    fieldRow("Project folder", folder.root, { note: hostRoom ? "The Hall can work in a folder too." : "" }),
    tools.root,
    fieldRow("Model", model.root),
    actions,
    result,
  );
  if (room.kind === "extra") {
    card.append(
      el("hr"),
      confirmButton("Remove room", { question: `Remove ${room.name}? Its slot becomes free again. The agent and its memory stay.`, confirm: "Remove", danger: true }, async () => {
        const r = await ctx.api.removeRoom(room.id);
        if (!r.ok) return r.message;
        ctx.markDirty(false);
        return `${room.name} was removed.`;
      }),
    );
  }
  dirty();
  return card;
}

