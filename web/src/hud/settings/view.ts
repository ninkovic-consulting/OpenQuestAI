// The settings screen: a full-height overlay over the scene with the groups
// on the left and the chosen group on the right. Edits stay in a draft until
// the group's Save sends only what changed; Revert drops them.

import type { AutomationsApi } from "../../net/automations-api";
import { nativeHelpers, type NativeHelpers } from "../../net/native";
import type { LibraryApi } from "../../net/library-api";
import type { PhoneApi } from "../../net/phone-api";
import type { SettingsApi } from "../../net/settings-api";
import type { Settings } from "../../net/settings-types";
import type { Store } from "../../net/store";
import type { ProposeResult } from "../../net/types";
import { el, setText } from "../dom";
import type { ModelSource } from "../pickers/model-picker";
import { RESTART_HELP, type Group, type GroupId, type SettingsContext } from "./context";
import { buildPatch, changedFields, draftFrom, placeErrors, rebase, restartLine, saveSummary, type Draft } from "./draft";
import { button, statusLine } from "./fields";
import { agentsGroup } from "./groups/agents";
import { askingGroup } from "./groups/asking";
import { assistantGroup } from "./groups/assistant";
import { automationsGroup } from "./groups/automations";
import { keyGroup } from "./groups/key";
import { displayGroup } from "./groups/display";
import { macGroup } from "./groups/mac";
import { modelsGroup } from "./groups/models";
import { libraryGroup } from "./groups/library";
import { phoneGroup } from "./groups/phone";
import { resetGroup } from "./groups/reset";
import { roomsGroup } from "./groups/rooms";
import { voiceGroup } from "./groups/voice";

const GROUPS: readonly Group[] = [assistantGroup, libraryGroup, modelsGroup, agentsGroup, roomsGroup, voiceGroup, askingGroup, automationsGroup, phoneGroup, keyGroup, macGroup, displayGroup, resetGroup];
const RESTART_POLL_MS = 1500;
const RESTART_WAIT_MS = 30_000;

export interface SettingsDeps {
  api: SettingsApi;
  automations: AutomationsApi;
  phone: PhoneApi;
  library: LibraryApi;
  store: Store;
  models: ModelSource;
  propose(folder: string): Promise<ProposeResult>;
  openWizard(): void;
  /** Hears the screen open and close (the panel's toggle lights up). */
  onShown(open: boolean): void;
}

export interface SettingsView {
  open(group?: GroupId, roomId?: string): void;
  /** Close the screen; false when it was not open. */
  close(): boolean;
  isOpen(): boolean;
}

export function mountSettings(parent: HTMLElement, deps: SettingsDeps): SettingsView {
  const root = el("div", "settings");
  root.hidden = true;
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.setAttribute("aria-label", "Settings");

  const nav = el("nav", "settings-nav");
  const navHead = el("div", "settings-title");
  navHead.append(el("h2", "", "Settings"), el("span", "caps hint", "⌘ ,  ·  Esc"));
  const navList = el("ul", "group-list");
  nav.append(navHead, navList);

  const main = el("section", "settings-main");
  const head = el("header", "settings-head");
  const title = el("h3");
  const blurb = el("p", "blurb");
  const close = el("button", "settings-close caps", "Close");
  close.type = "button";
  const titles = el("div");
  titles.append(title, blurb);
  head.append(titles, close);
  const restartBar = el("div", "restart-bar");
  const body = el("div", "settings-body");
  const foot = el("footer", "settings-foot");
  const footNote = el("p", "foot-note");
  footNote.setAttribute("role", "status");
  const revert = button("Revert");
  const save = button("Save", "primary");
  const footActions = el("div", "row-actions");
  footActions.append(revert, save);
  foot.append(footNote, footActions);
  main.append(head, restartBar, body, foot);
  // The frame is the grid; the root is the size container its narrow layout queries.
  const frame = el("div", "settings-frame");
  frame.append(nav, main);
  root.append(frame);
  parent.append(root);

  let settings: Settings | null = null;
  let saved: Draft = {};
  let draft: Draft = {};
  let errors = new Map<string, string>();
  let current: GroupId = "assistant";
  let roomId: string | null = null;
  let roomsDirty = false;
  let native: NativeHelpers = nativeHelpers();
  let restarting = false;

  const group = (): Group => GROUPS.find((g) => g.id === current) ?? assistantGroup;
  const dirtyIn = (g: Group): boolean => (g.id === "rooms" ? roomsDirty : g.prefixes.length > 0 && changedFields(saved, draft, g.prefixes).length > 0);

  const navButtons = new Map<GroupId, HTMLButtonElement>();
  GROUPS.forEach((g, i) => {
    const item = el("li");
    const b = el("button", "group-link");
    b.type = "button";
    b.append(el("span", "num caps", String(i + 1).padStart(2, "0")), el("span", "label", g.title), el("span", "dot unsaved"));
    b.addEventListener("click", () => goTo(g.id));
    navButtons.set(g.id, b);
    item.append(b);
    navList.append(item);
  });

  const renderNav = (): void => {
    for (const g of GROUPS) {
      const b = navButtons.get(g.id);
      if (!b) continue;
      b.setAttribute("aria-current", String(g.id === current));
      b.classList.toggle("is-dirty", dirtyIn(g));
    }
  };

  const renderFoot = (): void => {
    const g = group();
    foot.hidden = g.prefixes.length === 0 || settings === null;
    const changes = settings ? changedFields(saved, draft, g.prefixes).length : 0;
    save.disabled = changes === 0;
    revert.disabled = changes === 0;
    if (changes > 0) setText(footNote, `${changes} unsaved ${changes === 1 ? "change" : "changes"}.`);
    else if (footNote.textContent === "") setText(footNote, "Edits stay here until you save them.");
    renderNav();
  };

  const renderRestart = (): void => {
    const line = settings ? restartLine(settings) : null;
    restartBar.hidden = line === null;
    if (line === null) return;
    const parts: HTMLElement[] = [statusLine("warn", line)];
    if (native.restartDaemon) {
      const go = button(restarting ? "Restarting…" : "Restart now", "primary");
      go.disabled = restarting;
      go.addEventListener("click", () => void ctx().restart().then((text) => setText(footNote, text)));
      parts.push(go);
    } else {
      parts.push(el("p", "field-note", RESTART_HELP));
    }
    restartBar.replaceChildren(...parts);
  };

  const render = (): void => {
    const g = group();
    setText(title, g.title);
    setText(blurb, g.blurb);
    renderRestart();
    if (!settings) {
      body.replaceChildren(statusLine("idle", "Loading the settings…"));
    } else {
      body.replaceChildren(g.render(ctx()));
    }
    renderFoot();
  };

  const adopt = (next: Settings, reset: readonly string[] = []): void => {
    const nextSaved = draftFrom(next);
    draft = rebase(saved, nextSaved, draft, reset);
    saved = nextSaved;
    settings = next;
  };

  const load = async (opts: { redraw?: boolean; discard?: boolean } = {}): Promise<void> => {
    const r = await deps.api.settings();
    if (!r.ok) {
      if (!settings) body.replaceChildren(statusLine("bad", `The settings could not be loaded: ${r.message}`));
      return;
    }
    adopt(r.value, opts.discard ? [""] : []);
    if (opts.discard) errors = new Map();
    if (opts.redraw ?? true) render();
    else {
      renderRestart();
      renderFoot();
    }
  };

  const restart = async (): Promise<string> => {
    const go = native.restartDaemon;
    if (!go) return RESTART_HELP;
    restarting = true;
    renderRestart();
    try {
      await go();
    } catch {
      restarting = false;
      renderRestart();
      return `The app could not restart the assistant. ${RESTART_HELP}`;
    }
    const until = Date.now() + RESTART_WAIT_MS;
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, RESTART_POLL_MS));
      const r = await deps.api.settings();
      if (r.ok && r.value.restart_pending.length === 0) {
        restarting = false;
        adopt(r.value);
        render();
        return "The assistant restarted; every saved change is in effect.";
      }
    }
    restarting = false;
    renderRestart();
    return "The assistant is still restarting; this window reconnects by itself.";
  };

  const ctx = (): SettingsContext => {
    if (!settings) throw new Error("settings are not loaded");
    return {
      api: deps.api,
      automations: deps.automations,
      phone: deps.phone,
      library: deps.library,
      store: deps.store,
      native,
      models: deps.models,
      settings,
      saved,
      draft,
      edit(field, value) {
        draft[field] = value;
        errors.delete(field);
        footNote.textContent = "";
        renderFoot();
      },
      errorFor: (field) => errors.get(field),
      adopt(next) {
        adopt(next);
        render();
      },
      reload: load,
      restart,
      openWizard() {
        hide();
        deps.openWizard();
      },
      goTo,
      roomId,
      propose: deps.propose,
      markDirty(dirty) {
        roomsDirty = dirty;
        renderNav();
      },
    };
  };

  function goTo(id: GroupId, room?: string): void {
    if (id !== current) footNote.textContent = "";
    current = id;
    if (id === "rooms") roomsDirty = false;
    if (room !== undefined) roomId = room;
    render();
    body.scrollTop = 0;
    navButtons.get(id)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  revert.addEventListener("click", () => {
    for (const f of changedFields(saved, draft, group().prefixes)) {
      draft[f] = saved[f] ?? "";
      errors.delete(f);
    }
    footNote.textContent = "Unsaved changes dropped.";
    render();
  });

  save.addEventListener("click", () => {
    const g = group();
    const built = buildPatch(saved, draft, g.prefixes);
    errors = new Map(built.errors.map((e) => [e.field, e.message]));
    if (built.errors.length > 0) {
      footNote.textContent = "Some values need fixing before they can be saved.";
      render();
      return;
    }
    save.disabled = true;
    footNote.textContent = "Saving…";
    void deps.api.patchSettings(built.patch).then((r) => {
      if (r.ok) {
        errors = new Map();
        adopt(r.value.settings, g.prefixes);
        render();
        footNote.textContent = saveSummary(r.value);
        return;
      }
      const placed = placeErrors(r.errors, Object.keys(draft));
      errors = placed.byField;
      render();
      footNote.textContent = placed.general.length > 0 ? placed.general.join(" ") : r.errors.length > 0 ? "Not saved: see the notes beside the fields." : r.message;
    });
  });

  const hide = (): boolean => {
    if (root.hidden) return false;
    root.hidden = true;
    deps.onShown(false);
    if (root.contains(document.activeElement) && document.activeElement instanceof HTMLElement) document.activeElement.blur();
    return true;
  };
  close.addEventListener("click", hide);

  // Keys typed here stay here: Space must not start push to talk, `/` must not open the composer.
  root.addEventListener("keydown", (ev) => {
    ev.stopPropagation();
    if (ev.key === "Escape") hide();
    else if (ev.key === "," && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      hide();
    }
  });

  // The Rooms group follows the house unless a room has unsaved edits.
  deps.store.subscribe((s, prev) => {
    if (!root.hidden && s.plan !== prev.plan && current === "rooms" && !roomsDirty && settings) render();
  });

  return {
    open(id?: GroupId, room?: string): void {
      native = nativeHelpers();
      if (id) current = id;
      if (room !== undefined) roomId = room;
      root.hidden = false;
      deps.onShown(true);
      render();
      navButtons.get(current)?.focus();
      void load();
    },
    close: hide,
    isOpen: () => !root.hidden,
  };
}
